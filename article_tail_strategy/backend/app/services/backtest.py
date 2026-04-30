from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from app.config import settings
from app.models import BacktestParams, BacktestResponse, Metrics, NavPoint, TradeRecord
from app.services.data import (
    load_index_daily,
    load_index_minutes,
    load_stock_minutes,
    trading_days,
)
from app.services.strategy import select_for_date

# 回测进度回调格式：进度百分比、当前阶段、当前日期。
# 服务层不依赖网页框架；接口层可以传入回调发布进度，测试和脚本也可以
# 直接调用回测入口，不需要模拟网络请求环境。
ProgressCallback = Callable[[int, str, str | None], None]


def _market_tail_is_weak(day: pd.Timestamp, params: BacktestParams) -> bool:
    """判断基准指数尾盘是否走弱。

    这对应卖出表里的“尾盘大盘走弱，减仓或清仓，避免隔夜”。
    回测不能在 14:30 使用 15:00 才知道的信息，所以只有当最后一根尾盘 K 线
    已经可见后，才按收盘价执行防守性清仓。
    """
    # 卖出阶段也要看大盘尾盘。如果大盘 14:30 后继续走弱，就触发防守性清仓。
    bars = load_index_minutes(settings.benchmark_code, day, "15min")
    if bars.empty:
        return False
    times = pd.to_datetime(bars["trade_time"]).dt.strftime("%H:%M")
    tail = bars[times >= "14:30"]
    if len(tail) < 2:
        return False
    tail_ret = (float(tail.iloc[-1]["close"]) / float(tail.iloc[0]["close"]) - 1) * 100
    return tail_ret <= params.market_tail_weak_pct


def _cumulative_vwap(bars: pd.DataFrame) -> pd.Series:
    """根据分钟线计算日内累计均价线。

    部分行情文件的成交额单位可能不同，但股票分钟文件内部通常一致，足够用于
    趋势退出判断。成交量缺失时会退化到收盘价附近，避免回测直接崩溃。
    """
    # 使用累计成交额除以累计成交量计算运行中的均价线；成交量为 0 时做缺失处理。
    vol = bars["vol"].replace(0, pd.NA).cumsum()
    return (bars["amount"].cumsum() / vol).ffill().fillna(bars["close"])


def _trend_broken(bars_so_far: pd.DataFrame, params: BacktestParams) -> bool:
    """判断持仓日内价格形态是否走坏。

    卖出表里写的是“趋势完成、价格形态走坏，落袋为安”，但没有给公式。
    这里将它固定成可复现规则：分钟线数量足够后，最新收盘价同时低于
    累计均价线和短均线，并且低于上一根 K 线收盘价。
    这能捕捉日内趋势衰退，同时避免普通小回调就触发卖出。
    """
    # 趋势退出是可开关规则；分钟线数量不足时不判断，避免均线窗口不完整。
    if not params.enable_trend_exit or len(bars_so_far) < params.trend_break_ma_window:
        return False
    close = bars_so_far["close"].astype(float)
    last_close = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    short_ma = float(close.rolling(params.trend_break_ma_window).mean().iloc[-1])
    vwap = float(_cumulative_vwap(bars_so_far).iloc[-1])
    return last_close < prev_close and last_close < short_ma and last_close < vwap


def _sell_holding_period(
    code: str,
    buy_day: pd.Timestamp,
    buy_price: float,
    params: BacktestParams,
) -> tuple[float, str, str, str]:
    """在 3 到 5 日风格持仓窗口内执行卖出规则。

    卖出表包含五类场景，这里全部转换为可复现规则：

    1. 高开或冲高：最高价触及止盈线就止盈卖出。
    2. 个股跌破预设止损位：最低价触及止损线就止损卖出。
    3. 单笔亏损达到最大承受额度：最低价触及最大亏损线就清仓。
    4. 趋势完成、价格形态走坏：跌破均价线和短均线后按当前收盘价卖出。
    5. 尾盘大盘走弱：基准指数尾盘转弱时按当天收盘价防守性清仓。

    同一根 15 分钟 K 线内无法知道先到高点还是先到低点，所以亏损类规则优先。
    趋势退出从 trend_exit_after_days 之后才启用，避免 T+1 普通震荡立刻结束持仓。
    """
    # 预先计算止盈、止损、最大单笔亏损三条价格线。
    target = buy_price * (1 + params.take_profit_pct / 100)
    stop = buy_price * (1 - params.stop_loss_pct / 100) if params.stop_loss_pct > 0 else None
    max_loss = buy_price * (1 - params.max_trade_loss_pct / 100) if params.max_trade_loss_pct > 0 else None
    # 开仓日期是允许开新仓的日期；模拟日期会额外向后延伸最大持有天数，
    # 这样最后一个买入日后的卖出和盯市也能被完整计入。
    days = trading_days()
    pos = days.searchsorted(pd.Timestamp(buy_day).normalize())
    future_days = days[pos + 1: pos + 1 + params.max_hold_days]
    last_seen: tuple[float, str, str] | None = None

    # 从买入日后的第一个交易日开始，最多观察参数规定的最大持有交易日数。
    for hold_day, day in enumerate(future_days, start=1):
        bars = load_stock_minutes(code, day, "15min")
        if bars.empty:
            continue

        for bar_pos, (_, row) in enumerate(bars.iterrows(), start=1):
            sell_date = str(pd.Timestamp(day).date())
            sell_time = pd.Timestamp(row["trade_time"]).strftime("%H:%M")
            last_seen = (round(float(row["close"]), 4), sell_date, sell_time)
            low = float(row["low"])
            loss_triggers: list[tuple[float, str]] = []
            if stop is not None and low <= stop:
                loss_triggers.append((stop, "stop_loss"))
            if max_loss is not None and low <= max_loss:
                loss_triggers.append((max_loss, "max_loss"))
            # 同一根 15 分钟 K 线内无法知道先触发高点还是低点。
            # 为了保守，亏损类触发优先于止盈触发。
            if loss_triggers:
                price, reason = max(loss_triggers, key=lambda item: item[0])
                return round(price, 4), reason, sell_date, sell_time
            # 次日高开或冲高达到止盈线，按止盈价卖出。
            if float(row["high"]) >= target:
                return round(target, 4), "take_profit", sell_date, sell_time
            # 趋势走坏退出从持有若干天后才启用，避免刚买入就被普通震荡洗掉。
            if hold_day >= params.trend_exit_after_days and _trend_broken(bars.iloc[:bar_pos], params):
                return round(float(row["close"]), 4), "trend_broken", sell_date, sell_time

        final_row = bars.iloc[-1]
        final_time = pd.Timestamp(final_row["trade_time"]).strftime("%H:%M")
        # 每个持仓日收盘前复核大盘尾盘，走弱则清仓避免继续隔夜。
        if _market_tail_is_weak(day, params):
            return round(float(final_row["close"]), 4), "market_tail_weak", str(pd.Timestamp(day).date()), final_time

    if last_seen is None:
        return buy_price, "no_next_day", "N/A", "N/A"
    price, sell_date, sell_time = last_seen
    return price, "close", sell_date, sell_time


def _sell_next_day(code: str, next_day: pd.Timestamp, buy_price: float, params: BacktestParams) -> tuple[float, str, str]:
    """兼容旧版 T+1 卖出测试的辅助函数。"""
    bars = load_stock_minutes(code, next_day, "15min")
    if bars.empty:
        return buy_price, "no_next_day", "N/A"

    target = buy_price * (1 + params.take_profit_pct / 100)
    stop = buy_price * (1 - params.stop_loss_pct / 100) if params.stop_loss_pct > 0 else None
    max_loss = buy_price * (1 - params.max_trade_loss_pct / 100) if params.max_trade_loss_pct > 0 else None

    for pos, (_, row) in enumerate(bars.iterrows(), start=1):
        sell_time = pd.Timestamp(row["trade_time"]).strftime("%H:%M")
        low = float(row["low"])
        loss_triggers: list[tuple[float, str]] = []
        if stop is not None and low <= stop:
            loss_triggers.append((stop, "stop_loss"))
        if max_loss is not None and low <= max_loss:
            loss_triggers.append((max_loss, "max_loss"))
        if loss_triggers:
            price, reason = max(loss_triggers, key=lambda item: item[0])
            return round(price, 4), reason, sell_time
        if float(row["high"]) >= target:
            return round(target, 4), "take_profit", sell_time
        if _trend_broken(bars.iloc[:pos], params):
            return round(float(row["close"]), 4), "trend_broken", sell_time

    final_row = bars.iloc[-1]
    final_time = pd.Timestamp(final_row["trade_time"]).strftime("%H:%M")
    if _market_tail_is_weak(next_day, params):
        return round(float(final_row["close"]), 4), "market_tail_weak", final_time
    return round(float(final_row["close"]), 4), "close", final_time


def _shares_for(allocation: float, price: float) -> int:
    """把可用资金转换成 A 股整手股数。

    A 股通常按 100 股一手交易，向下取整可以避免实际买入金额超过仓位上限。
    """
    # A 股按 100 股一手交易，向下取整可以保证不会超出可用资金。
    if price <= 0:
        return 0
    return int(allocation / price / 100) * 100


def _close_price_on_day(code: str, day: pd.Timestamp, fallback: float) -> float:
    """返回某只股票当天最后一根分钟线收盘价，用于每日盯市。"""
    bars = load_stock_minutes(code, day, "15min")
    if bars.empty:
        return fallback
    return float(bars.iloc[-1]["close"])


def _benchmark_nav(start: str, end: str, nav_index: pd.DatetimeIndex) -> pd.Series:
    """返回与策略日期对齐的沪深300归一化净值。"""
    # 基准使用沪深300日线，并对齐策略净值日期。缺失时退化为 1.0，
    # 避免页面崩溃，但指标解释时要知道基准数据可能缺失。
    bench = load_index_daily(settings.benchmark_code, start, end)
    if bench.empty:
        return pd.Series(1.0, index=nav_index)
    close = bench.set_index("trade_date")["close"].reindex(nav_index, method="ffill")
    if close.dropna().empty:
        return pd.Series(1.0, index=nav_index)
    close = close.ffill().bfill()
    return close / close.iloc[0]


def _metrics(nav: pd.Series, benchmark_nav: pd.Series, trades: list[TradeRecord]) -> Metrics:
    """计算前端展示的核心回测指标。"""
    # 总收益、年化、最大回撤、胜率、交易数、基准收益是前端卡片展示的核心指标。
    total = float(nav.iloc[-1] / nav.iloc[0] - 1) if len(nav) else 0.0
    years = max(len(nav) / 252, 0.01)
    ann = (1 + total) ** (1 / years) - 1 if total > -1 else -1.0
    dd = ((nav - nav.cummax()) / nav.cummax()).min() if len(nav) else 0.0
    wins = [t for t in trades if t.profit > 0]
    bench_total = float(benchmark_nav.iloc[-1] / benchmark_nav.iloc[0] - 1) if len(benchmark_nav) else 0.0
    return Metrics(
        total_return=round(total, 4),
        annualized_return=round(float(ann), 4),
        max_drawdown=round(float(dd), 4),
        win_rate=round(len(wins) / len(trades), 4) if trades else 0.0,
        trade_count=len(trades),
        benchmark_total_return=round(bench_total, 4),
    )


def run_backtest(params: BacktestParams, progress: ProgressCallback | None = None) -> BacktestResponse:
    """执行完整的文章版尾盘策略回测。

    这个模拟遵循文章里的短线尾盘交易流程，而不是周度或月度调仓：

    - T 日：执行大盘、日线、趋势、尾盘分时检查。
    - T 日尾盘：按尾盘买入价买入入选股票，单股仓位受 max_position_pct 限制。
    - T+1 到 T+max_hold_days：按卖出表依次检查止盈、止损、最大亏损、
      趋势走坏、大盘尾盘走弱；都不触发则到期收盘卖出。

    可选进度回调会在逐日模拟时触发，接口层用它给前端展示进度条；
    回调本身不参与计算，不会影响回测结果。
    """
    days = trading_days()
    buy_mask = (days >= pd.Timestamp(params.start_date)) & (days <= pd.Timestamp(params.end_date))
    buy_days = pd.DatetimeIndex(days[buy_mask])
    if buy_days.empty:
        raise ValueError("回测区间没有交易日")

    start_pos = int(days.searchsorted(buy_days[0]))
    end_pos = int(days.searchsorted(buy_days[-1]))
    sim_end_pos = min(len(days) - 1, end_pos + params.max_hold_days)
    sim_days = pd.DatetimeIndex(days[start_pos: sim_end_pos + 1])
    buy_day_set = set(pd.Timestamp(day).normalize() for day in buy_days)

    if progress:
        progress(1, "准备交易日与数据", None)

    # 现金记录可用资金；未平仓持仓保存已经买入但尚未到卖出日的持仓。
    # 每日净值字典在每天收盘后记录一次组合净值。
    cash = float(params.initial_capital)
    nav_by_day: dict[pd.Timestamp, float] = {}
    trades: list[TradeRecord] = []
    selections = []
    open_positions: list[dict] = []
    total_days = len(sim_days)

    for idx, day in enumerate(sim_days, start=1):
        if progress:
            percent = max(1, min(95, int(idx / total_days * 95)))
            progress(percent, "逐日选股、持仓盯市与卖出模拟", str(day.date()))

        # 先处理今天应该卖出的旧持仓，把卖出资金和利润落到账上。
        still_open: list[dict] = []
        for pos in open_positions:
            if pos["sell_date"] == str(day.date()):
                sell_amount = pos["shares"] * pos["sell_price"]
                sell_commission = sell_amount * params.commission_rate
                cash += sell_amount - sell_commission
                profit = sell_amount - sell_commission - pos["buy_amount"] - pos["buy_commission"]
                trades.append(TradeRecord(
                    code=pos["code"],
                    name=pos["name"],
                    buy_date=pos["buy_date"],
                    buy_time="15:00",
                    sell_date=pos["sell_date"],
                    sell_time=pos["sell_time"],
                    buy_price=round(pos["buy_price"], 4),
                    sell_price=round(pos["sell_price"], 4),
                    shares=pos["shares"],
                    buy_amount=round(pos["buy_amount"], 2),
                    sell_amount=round(sell_amount, 2),
                    return_pct=round((pos["sell_price"] / pos["buy_price"] - 1) * 100, 4),
                    profit=round(profit, 2),
                    exit_reason=pos["reason"],  # type: ignore[arg-type]
                ))
            else:
                still_open.append(pos)
        open_positions = still_open

        # 对仍未卖出的持仓按当天收盘价盯市，得到买入前的组合权益。
        marked_positions = 0.0
        for pos in open_positions:
            mark = _close_price_on_day(pos["code"], day, pos["last_mark"])
            pos["last_mark"] = mark
            marked_positions += pos["shares"] * mark
        equity_before_buys = cash + marked_positions

        # 超出开仓区间的延伸交易日只做卖出和盯市，不再开新仓。
        if pd.Timestamp(day).normalize() not in buy_day_set:
            nav_by_day[day] = equity_before_buys / params.initial_capital
            continue

        # 当天收盘前运行选股逻辑，买入价使用选股结果里的尾盘收盘价。
        selection = select_for_date(day, params)
        selections.append(selection)

        picks = [s for s in selection.selected if s.buy_price and s.buy_price > 0]
        if not picks:
            nav_by_day[day] = equity_before_buys / params.initial_capital
            continue

        # 多只股票同时入选时，资金等分，但单股不超过参数规定的单股仓位。
        # 分配金额同时受组合权益和当前现金约束，避免现金不够时仍按满仓买入。
        per_stock_pct = min(params.max_position_pct, 1.0 / len(picks))
        held_codes = {pos["code"] for pos in open_positions}
        for stock_index, stock in enumerate(picks):
            if stock.code in held_codes:
                continue
            buy_price = float(stock.buy_price or 0)
            remaining_slots = max(1, len(picks) - stock_index)
            allocation = min(equity_before_buys * per_stock_pct, cash / remaining_slots)
            max_buy_amount = allocation / (1 + params.commission_rate)
            shares = _shares_for(max_buy_amount, buy_price)
            if shares <= 0:
                continue

            buy_amount = shares * buy_price
            buy_commission = buy_amount * params.commission_rate
            # 买入时就根据未来分钟线模拟完整卖出路径。这里是回测允许的“事后计算”，
            # 但卖出规则本身只使用每个卖出时点之前已经发生的分钟数据。
            sell_price, reason, sell_date, sell_time = _sell_holding_period(stock.code, day, buy_price, params)
            if sell_date == "N/A":
                sell_date = str(day.date())
                sell_time = "15:00"
            cash -= buy_amount + buy_commission
            open_positions.append({
                "code": stock.code,
                "name": stock.name,
                "buy_date": str(day.date()),
                "sell_date": sell_date,
                "sell_time": sell_time,
                "buy_price": buy_price,
                "sell_price": sell_price,
                "shares": shares,
                "buy_amount": buy_amount,
                "buy_commission": buy_commission,
                "reason": reason,
                "last_mark": buy_price,
            })
            held_codes.add(stock.code)

        # 当天买入后，再按当天收盘价盯市一次，形成当日收盘净值。
        marked_after_buys = 0.0
        for pos in open_positions:
            mark = _close_price_on_day(pos["code"], day, pos["last_mark"])
            pos["last_mark"] = mark
            marked_after_buys += pos["shares"] * mark
        nav_by_day[day] = (cash + marked_after_buys) / params.initial_capital

    if progress:
        progress(96, "计算净值、回撤和基准", None)

    # 将每日净值补齐到完整模拟交易日，便于和基准净值、回撤序列对齐。
    nav = pd.Series(nav_by_day).sort_index()
    nav = nav.reindex(sim_days, method="ffill").fillna(1.0)
    bench = _benchmark_nav(str(params.start_date), str(sim_days[-1].date()), nav.index)
    drawdown = (nav - nav.cummax()) / nav.cummax()
    nav_points = [
        NavPoint(
            date=str(ts.date()),
            nav=round(float(nav.loc[ts]), 4),
            benchmark_nav=round(float(bench.loc[ts]), 4),
            drawdown=round(float(drawdown.loc[ts]), 4),
        )
        for ts in nav.index
    ]

    response = BacktestResponse(
        params=params,
        metrics=_metrics(nav, bench, trades),
        nav_series=nav_points,
        trades=trades,
        selections=selections,
    )
    if progress:
        progress(100, "完成", None)
    return response
