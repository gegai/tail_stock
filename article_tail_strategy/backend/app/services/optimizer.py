from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from itertools import product
from threading import Event
from typing import Any

import pandas as pd

from app.models import BacktestParams, OptimizationParams, OptimizationResultItem, SweepRange
from app.services.backtest import run_backtest

# 参数优化任务会在后台线程里启动，在子进程池里执行。
# 这个回调只负责把“进度百分比、已完成数量、总数量、阶段文案、当前最优结果”
# 交回接口层保存；优化器本身不依赖网页接口框架，方便测试和脚本复用。
OptimizeProgressCallback = Callable[[int, int, int, str, list[OptimizationResultItem]], None]
OptimizeCheckpointCallback = Callable[[OptimizationResultItem], None]


def combo_key(params_data: dict[str, Any]) -> str:
    """为一组完整回测参数生成稳定 key，用于断点续跑时跳过已完成组合。"""
    import json

    return json.dumps(params_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_param_combinations(request: OptimizationParams) -> list[dict[str, Any]]:
    """把前端填写的多个候选参数展开成一组组完整回测参数。

    例如：
    - 市值上限有 3 个候选值
    - 止盈有 2 个候选值

    那么这里只会生成 3 * 2 = 6 套 BacktestParams。其它没有进入
    ranges 的参数，全部继承 base_params。这样做可以避免前端重复传一堆
    完整对象，也让“组合数量为什么这么多”在后端有一个唯一计算入口。
    """
    base = request.base_params.model_dump(mode="json")

    # 只展开候选值非空的参数。空数组表示该参数不参与优化，继续使用基础参数。
    names = [item.name for item in request.ranges if item.values]
    values = [item.values for item in request.ranges if item.values]
    if not names:
        return [base]

    combos: list[dict[str, Any]] = []

    # 笛卡尔积：每个参数的每个候选值都会和其它参数的
    # 每个候选值组合一次。默认前端 8 个参数范围会产生 1296 组。
    for value_set in product(*values):
        combo = dict(base)
        for name, value in zip(names, value_set, strict=True):
            combo[name] = value
        combos.append(combo)

        # 组合数量失控会让本机长时间满载，甚至吃光内存。所以后端必须有硬上限，
        # 不能只相信前端输入。
        if len(combos) > request.max_combinations:
            raise ValueError(f"参数组合数量超过上限：{request.max_combinations}")
    return combos


def _yearly_returns(nav_points: list[dict[str, Any]]) -> dict[str, float]:
    """按自然年计算收益率，用来观察策略是不是只在某一年有效。

    这里不是用每年 1 月 1 日到 12 月 31 日的完整行情，而是用该回测区间内
    每个自然年的第一条/最后一条净值。因此如果回测从 2023-06 开始，
    2023 年收益就是 2023-06 到 2023-12 的区间收益。
    """
    if not nav_points:
        return {}
    nav = pd.DataFrame(nav_points)
    nav["date"] = pd.to_datetime(nav["date"])
    yearly: dict[str, float] = {}
    for year, group in nav.groupby(nav["date"].dt.year):
        first = float(group.iloc[0]["nav"])
        last = float(group.iloc[-1]["nav"])
        yearly[str(year)] = round(last / first - 1, 4) if first else 0.0
    return yearly


def _score_item(
    total_return: float,
    annualized_return: float,
    max_drawdown: float,
    win_rate: float,
    trade_count: int,
    yearly_returns: dict[str, float],
    request_data: dict[str, Any],
) -> float:
    """给单组参数的回测结果打分。

    评分目标不是单纯追求胜率，而是优先寻找“能赚钱、回撤可控、交易数量不太少”
    的组合。因此权重设计为：
    - 年化收益和总收益是主项；
    - 胜率、交易数量、年度稳定性是辅助项；
    - 年化或总收益为负会被硬惩罚，避免亏钱策略因为胜率高而排在前面。

    注意：这只是参数筛选的排序分，不是金融意义上的标准指标。真正决策时仍然
    要结合交易明细、年度收益和样本数量人工复核。
    """
    min_trade_count = int(request_data.get("min_trade_count", 80))
    max_drawdown_limit = float(request_data.get("max_drawdown_limit", -0.20))

    # 卡玛比率近似衡量“承担一单位回撤换来了多少年化收益”。
    # 最大回撤是负数，所以这里使用绝对值。
    calmar = annualized_return / abs(max_drawdown) if max_drawdown < 0 else annualized_return

    # 交易数不是越多越好，但太少会过拟合；达到目标交易数后继续加分有限。
    trade_score = min(trade_count / max(min_trade_count, 1), 1.5) * 10

    # 年度稳定性只看正收益年份占比，避免某个组合只靠一个年份的大行情撑起来。
    stability = 0.0
    if yearly_returns:
        yearly_values = list(yearly_returns.values())
        positive_years = sum(1 for value in yearly_values if value > 0)
        stability = positive_years / len(yearly_values) * 10

    # 主分：收益占 65%，风险收益比占 15%，胜率/样本量/稳定性占 20%。
    score = (
        annualized_return * 100 * 0.45
        + total_return * 100 * 0.20
        + win_rate * 100 * 0.10
        + calmar * 10 * 0.15
        + trade_score * 0.05
        + stability * 0.05
    )

    # 硬惩罚：亏钱策略不能因为胜率高、交易多就排到前面。
    if annualized_return <= 0:
        score -= 50 + abs(annualized_return) * 100 * 0.50
    if total_return <= 0:
        score -= 30 + abs(total_return) * 100 * 0.30

    # 样本不足按比例扣分。比如目标 80 笔，只有 40 笔，就扣一半惩罚。
    if trade_count < min_trade_count:
        shortfall = 1 - trade_count / max(min_trade_count, 1)
        score -= 30 * shortfall

    # 回撤超过用户设置的红线时额外扣分。
    if max_drawdown < max_drawdown_limit:
        score -= 30
    return round(score, 4)


def run_one_combo(params_data: dict[str, Any], request_data: dict[str, Any]) -> OptimizationResultItem:
    """在一个子进程里执行一组参数的完整回测。

    Windows 的 multiprocessing 需要能够 pickle 目标函数，所以这个函数必须放在
    模块顶层，不能写成 run_parameter_sweep 里面的内部函数。
    """
    params = BacktestParams.model_validate(params_data)

    # 这里调用的是完整回测逻辑，因此每组参数都会独立读取行情、选股、卖出、
    # 计算净值。进程之间不共享表格对象，换来的是更稳的并行隔离。
    result = run_backtest(params)
    nav_points = [point.model_dump(mode="json") for point in result.nav_series]
    yearly = _yearly_returns(nav_points)
    metrics = result.metrics
    return OptimizationResultItem(
        params=params.model_dump(mode="json"),
        total_return=metrics.total_return,
        annualized_return=metrics.annualized_return,
        max_drawdown=metrics.max_drawdown,
        win_rate=metrics.win_rate,
        trade_count=metrics.trade_count,
        benchmark_total_return=metrics.benchmark_total_return,
        yearly_returns=yearly,
        score=_score_item(
            metrics.total_return,
            metrics.annualized_return,
            metrics.max_drawdown,
            metrics.win_rate,
            metrics.trade_count,
            yearly,
            request_data,
        ),
    )


def _top_results(results: list[OptimizationResultItem], top_n: int) -> list[OptimizationResultItem]:
    """按评分从高到低截取前 N 个结果，供进度页实时展示。"""
    return sorted(results, key=lambda item: item.score, reverse=True)[:top_n]


def run_parameter_sweep(
    request: OptimizationParams,
    cancel_event: Event | None = None,
    progress: OptimizeProgressCallback | None = None,
    initial_results: list[OptimizationResultItem] | None = None,
    checkpoint: OptimizeCheckpointCallback | None = None,
) -> list[OptimizationResultItem]:
    """执行多进程参数遍历，并返回评分最高的若干组结果。

    调度方式是“固定窗口”：
    - 同时最多运行 max_workers 个子进程任务；
    - 每完成一个任务，就补交下一个组合；
    - 每秒检查一次取消信号和已完成任务；
    - 每轮都把当前 Top N 回报给 API 层。

    这样可以避免一次性提交几千个 Future 占用过多内存，也能让取消操作更快生效。
    """
    combos = build_param_combinations(request)
    total = len(combos)
    results: list[OptimizationResultItem] = list(initial_results or [])
    completed_keys = {combo_key(item.params) for item in results}
    pending_combos = [combo for combo in combos if combo_key(combo) not in completed_keys]
    if progress:
        percent = int(len(results) / total * 100) if total else 100
        progress(percent, len(results), total, "准备参数组合", _top_results(results, request.top_n))

    top_n = request.top_n
    request_data = request.model_dump(mode="json")
    max_workers = min(request.max_workers, len(pending_combos))
    pending_index = 0

    if not pending_combos:
        if progress:
            progress(100, len(results), total, "已完成", _top_results(results, top_n))
        return _top_results(results, top_n)

    # 多进程可以绕开解释器全局锁，适合表格计算这种处理器和内存都较重的任务。
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures: set[Future[OptimizationResultItem]] = set()

        def submit_more() -> None:
            nonlocal pending_index

            # 补足“正在运行的任务窗口”。待提交下标指向下一组尚未提交的参数。
            while pending_index < len(pending_combos) and len(futures) < max_workers:
                futures.add(pool.submit(run_one_combo, pending_combos[pending_index], request_data))
                pending_index += 1

        submit_more()
        while futures:
            if cancel_event and cancel_event.is_set():
                # 已经开始运行的子进程任务不一定能立刻中断，但尚未开始的任务会被取消。
                # 接口层会把任务状态标为已取消，前端停止轮询即可。
                for future in futures:
                    future.cancel()
                pool.shutdown(cancel_futures=True)
                raise InterruptedError("参数优化已取消")

            # 一秒超时让循环定期醒来检查取消信号；完成一个就处理一个。
            done, futures = wait(futures, timeout=1.0, return_when=FIRST_COMPLETED)
            for future in done:
                item = future.result()
                results.append(item)
                if checkpoint:
                    checkpoint(item)
            submit_more()

            completed = len(results)
            percent = int(completed / total * 100) if total else 100
            if progress:
                # 进度里只传当前最优前若干名，不把所有结果都传给前端，避免响应体越来越大。
                progress(
                    percent,
                    completed,
                    total,
                    f"已完成 {completed}/{total} 组",
                    _top_results(results, top_n),
                )

    return _top_results(results, top_n)
