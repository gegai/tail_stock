from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.config import settings
from app.models import RuleResult, SelectedStock, SelectionResponse, StrategyParams
from app.services.data import (
    enrich_daily,
    load_daily_date,
    load_daily_range,
    load_index_daily,
    load_index_minutes,
    load_stock_minutes,
    previous_trading_dates,
)


def rule(name: str, passed: bool, actual=None, threshold: str | None = None, note: str = "") -> RuleResult:
    """创建一条可展示的规则结果。

    所有选股条件都用 RuleResult 返回给前端，用户可以看到每条规则是否通过、
    实际值是多少、阈值是多少，而不是只得到一个黑盒选股列表。
    """
    if isinstance(actual, (float, np.floating)) and math.isfinite(float(actual)):
        actual = round(float(actual), 4)
    return RuleResult(name=name, passed=bool(passed), actual=actual, threshold=threshold, note=note)


def _time_part(series: pd.Series) -> pd.Series:
    """把分钟线时间转换成 HH:MM 字符串，便于筛选 14:30 后数据。"""
    return pd.to_datetime(series).dt.strftime("%H:%M")


def market_tail_rules(day: str | pd.Timestamp, params: StrategyParams) -> list[RuleResult]:
    """把文章里的大盘条件转换成可复现的机器规则。

    文章要求 14:30 后观察大盘，弱势或放量下跌时不进场。这里拆成两类判断：

    - 沪深300 14:30 到收盘的涨幅必须达到参数要求。
    - 放量大跌必须同时满足三项：全天跌幅不小、尾盘继续下跌、尾盘量能明显放大。
    """
    df = load_index_minutes(settings.benchmark_code, day, "15min")
    if df.empty:
        return [rule("大盘15分钟数据可用", False, "missing", note="未找到沪深30015分钟数据")]

    # 文章强调“14:30 后大盘不能走弱”，所以这里单独切出尾盘区间。
    times = _time_part(df["trade_time"])
    tail = df[times >= "14:30"].copy()
    if len(tail) < 2:
        return [rule("大盘14:30后K线完整", False, len(tail), ">=2")]

    first_close = float(tail.iloc[0]["close"])
    last_close = float(tail.iloc[-1]["close"])
    tail_ret = (last_close / first_close - 1) * 100

    day_open = float(df.iloc[0]["open"])
    day_close = float(df.iloc[-1]["close"])
    day_ret = (day_close / day_open - 1) * 100

    pre_tail = df[times < "14:30"]
    pre_tail_avg_vol = float(pre_tail["vol"].mean()) if not pre_tail.empty else 0.0
    tail_avg_vol = float(tail["vol"].mean())
    tail_vol_ratio = tail_avg_vol / pre_tail_avg_vol if pre_tail_avg_vol else 0.0
    # “放量大跌”使用用户确认过的三条件定义：
    # 当日跌幅 <= -1.5%，且 14:30 后继续跌 <= -0.3%，且尾盘量能 >= 前面均量 1.5 倍。
    crash = day_ret <= -1.5 and tail_ret <= -0.3 and tail_vol_ratio >= 1.5
    index_trend_rule = _index_ma20_rule(day, params)

    # 早期版本只要求尾盘涨幅大于 0。复盘后发现很多“勉强翻红”的大盘尾盘，
    # 次日个股表现仍然偏弱，所以这里改成可配置的最低尾盘涨幅门槛。
    rules = [
        rule(
            "大盘14:30后15分钟K线有效上升",
            tail_ret >= params.min_market_tail_return_pct,
            tail_ret,
            f">= {params.min_market_tail_return_pct}%",
        ),
        rule(
            "大盘未放量大跌",
            not crash,
            f"day={day_ret:.2f}%, tail={tail_ret:.2f}%, tail_vol_ratio={tail_vol_ratio:.2f}",
            "当日跌幅>-1.5% 或 14:30后跌幅>-0.3% 或 尾盘量比<1.5",
        ),
    ]
    if index_trend_rule is not None:
        rules.append(index_trend_rule)
    return rules


def _index_ma20_rule(day: str | pd.Timestamp, params: StrategyParams) -> RuleResult | None:
    """要求基准指数收盘站上 20 日均线后才允许买入。

    复盘发现沪深300低于 MA20 时买入，胜率和盈亏表现明显更差。
    这是一道市场状态过滤，和 14:30 后尾盘规则互相独立：
    大盘尾盘可以反弹，但更大级别趋势仍可能不健康。
    """
    if not params.require_index_above_ma20:
        return None
    lookback = previous_trading_dates(day, 40)
    if len(lookback) < 20:
        return rule("沪深300站上MA20", False, len(lookback), ">=20日")
    hist = load_index_daily(settings.benchmark_code, str(lookback[0].date()), str(pd.Timestamp(day).date()))
    if len(hist) < 20:
        return rule("沪深300站上MA20", False, len(hist), ">=20日")
    close = hist["close"].astype(float)
    ma20 = float(close.rolling(20).mean().iloc[-1])
    last = float(close.iloc[-1])
    return rule("沪深300站上MA20", last > ma20, f"close={last:.2f}, ma20={ma20:.2f}", "close > MA20")


def daily_screen(day: str | pd.Timestamp, params: StrategyParams) -> tuple[pd.DataFrame, int]:
    """执行文章中客观可量化的日线过滤条件。

    这里刻意只使用 T 日收盘时已经能知道的数据：当日振幅、当日流通市值、
    当日换手率、当日量比、近期涨停历史。这样可以避免未来函数。
    """
    raw = load_daily_date(day)
    df = enrich_daily(raw)
    if df.empty:
        return df, 0

    # 基础可交易性过滤：只保留正常上市、非 ST、未停牌、上市满 60 天的股票。
    # 这些不是文章核心条件，但属于回测必须有的现实交易约束。
    df = df[df["list_status"].fillna("L") == "L"].copy()
    df = df[~df["is_st"].fillna(False).astype(bool)]
    # 历史 is_st 标记可能缺失或滞后，所以再用股票名称做一层兜底过滤，
    # 避免 ST/*ST 股票因为日线标记异常而混入候选池。
    df = df[~df["name"].fillna("").astype(str).str.upper().str.contains("ST", regex=False)]
    df = df[df["suspend_type"].fillna("N") == "N"]
    df = df[df["listed_days"].fillna(0) >= 60]
    df = df[df["close"].notna() & (df["close"] > 0)]
    base_count = len(df)

    # 文章里的日线五条件在这里落地：振幅、市值、换手、量比、近期涨停记忆。
    df = df[df["amplitude"].notna() & (df["amplitude"] <= params.max_amplitude)]
    df = df[df["float_mktcap"].notna() & (df["float_mktcap"] <= params.max_float_mktcap)]
    df = df[df["turnover_rate"].notna() & (df["turnover_rate"] >= params.min_turnover_rate)]
    df = df[df["volume_ratio"].notna() & (df["volume_ratio"] >= params.min_volume_ratio)]
    df = df[df["volume_ratio"].notna() & (df["volume_ratio"] <= params.max_volume_ratio)]
    if df.empty:
        return df, base_count

    lookback_days = previous_trading_dates(day, params.limitup_lookback)
    start = str(lookback_days[0].date()) if lookback_days else str(pd.Timestamp(day).date())
    end = str(pd.Timestamp(day).date())
    hist = load_daily_range(start, end, ["pct_chg"])
    # 涨停历史用“当日涨跌幅不低于 9.9%”近似。不同股票涨跌停制度不同，
    # 这里先用保守统一阈值表达“近期有涨停记忆”。
    limitup_codes = set(hist.loc[hist["pct_chg"] >= 9.9, "ts_code"].unique())
    df = df[df["ts_code"].isin(limitup_codes)]
    return df, base_count


def stock_tail_metrics(code: str, day: str | pd.Timestamp, params: StrategyParams) -> tuple[list[RuleResult], dict]:
    """量化文章里的个股尾盘价格和成交量描述。

    文章的表达偏交易经验，例如“回踩均价线不破”“分时上升”“持续有大单买入”。
    当前数据没有逐笔大单标签，所以用尾盘成交量放大近似“大单买入”。
    每个近似规则都会返回给前端，用户可以逐条审计。
    """
    df = load_stock_minutes(code, day, "15min")
    if df.empty:
        return [rule("个股15分钟数据可用", False, "missing")], {}

    times = _time_part(df["trade_time"])
    # 用当日累计成交额除以累计成交量近似分时均价线，用于判断尾盘是否站上均价线。
    amount_cum = df["amount"].cumsum()
    vol_cum = df["vol"].replace(0, pd.NA).cumsum()
    vwap = (amount_cum / vol_cum).ffill().fillna(df["close"])
    df = df.copy()
    df["vwap"] = vwap

    # 核心买点只看 14:30 之后：文章强调尾盘确认，而不是全天任意时刻追涨。
    tail = df[times >= "14:30"]
    pre_tail = df[times < "14:30"]
    morning = df[times < "14:30"]
    if len(tail) < 2:
        return [rule("个股14:30后K线完整", False, len(tail), ">=2")], {}

    tail_ret = (float(tail.iloc[-1]["close"]) / float(tail.iloc[0]["close"]) - 1) * 100
    close_vs_vwap = (float(tail.iloc[-1]["close"]) / float(tail.iloc[-1]["vwap"]) - 1) * 100

    avg_pre_vol = float(pre_tail["vol"].tail(8).mean()) if not pre_tail.empty else 0.0
    avg_tail_vol = float(tail["vol"].mean()) if not tail.empty else 0.0
    tail_vol_ratio = avg_tail_vol / avg_pre_vol if avg_pre_vol > 0 else 0.0

    morning_band = 999.0
    if not morning.empty:
        dev_high = (morning["high"] / morning["vwap"] - 1).abs()
        dev_low = (morning["low"] / morning["vwap"] - 1).abs()
        morning_band = float(pd.concat([dev_high, dev_low], axis=1).max(axis=1).median() * 100)

    # 这些是个股尾盘质量的核心门槛。只是微涨不够，必须 14:30 到收盘有
    # 明确涨幅，并且收盘价相对当日均价线有一定缓冲。
    rules = [
        rule("个股14:30后分时有效上升", tail_ret >= params.min_tail_return_pct, tail_ret, f">= {params.min_tail_return_pct}%"),
        rule("尾盘收盘站上均价线", close_vs_vwap >= params.min_close_vs_vwap_pct, close_vs_vwap, f">= {params.min_close_vs_vwap_pct}%"),
        rule("尾盘成交量放大", tail_vol_ratio >= params.tail_volume_multiplier, tail_vol_ratio, f">= {params.tail_volume_multiplier}"),
        rule("盘中围绕均价线平稳震荡", morning_band <= params.max_morning_vwap_band_pct, morning_band, f"<= {params.max_morning_vwap_band_pct}%"),
    ]
    return rules, {
        "tail_return_pct": tail_ret,
        "close_vs_vwap_pct": close_vs_vwap,
        "tail_volume_ratio": tail_vol_ratio,
        "morning_vwap_band_pct": morning_band,
        "buy_price": float(tail.iloc[-1]["close"]),
    }


def trend_rules(code: str, day: str | pd.Timestamp, params: StrategyParams) -> list[RuleResult]:
    """近似表达文章里的中期上升趋势要求。

    文章偏好中期趋势清晰、短期经过整理但尚未过热的股票。
    这里用 close > MA20 > MA60 表达中期趋势，用短期回调和近期振幅控制过热程度。
    """
    lookback = previous_trading_dates(day, 80)
    if len(lookback) < 60:
        return [rule("中期趋势数据足够", False, len(lookback), ">=60")]
    hist = load_daily_range(str(lookback[0].date()), str(pd.Timestamp(day).date()), ["close", "high", "low", "pre_close"])
    hist = hist[hist["ts_code"] == code].sort_values("trade_date")
    if len(hist) < 60:
        return [rule("中期趋势数据足够", False, len(hist), ">=60")]
    # 中期趋势用“收盘价高于二十日均线，二十日均线高于六十日均线”表达；这不是文章原文的唯一解释，
    # 但它把“中期上升趋势”固定成了可复现规则。
    close = hist["close"]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    last = close.iloc[-1]
    prev5 = close.iloc[-6:-1].max()
    pullback = (last / prev5 - 1) * 100 if prev5 else 0.0
    # 避免追入近期波动已经过大的股票。策略在尾盘买入并隔夜持有，
    # 如果最近振幅过大，通常更容易先触发止损而不是止盈。
    recent = hist.tail(params.recent_amplitude_lookback)
    recent_amp = ((recent["high"] - recent["low"]) / recent["pre_close"].replace(0, np.nan) * 100).mean()
    return [
        rule("中期上升趋势", last > ma20 > ma60, f"close={last:.2f}, ma20={ma20:.2f}, ma60={ma60:.2f}", "close > MA20 > MA60"),
        rule("短期回调未过热", pullback <= 5.0, pullback, "<= 5%"),
        rule("近几日波动不过大", recent_amp <= params.max_recent_amplitude_pct, recent_amp, f"<= {params.max_recent_amplitude_pct}%"),
    ]


def score_row(row: pd.Series, metrics: dict) -> float:
    """给通过全部硬条件的股票打排序分。

    硬条件决定“能不能买”，score 只决定“最多持仓数有限时优先买谁”。
    分数偏好：换手适中、量比在 1.2~1.3 附近、市值更小、振幅更低、
    尾盘涨幅和尾盘放量更明显。
    """
    s_turn = min(float(row["turnover_rate"]) / 6.0, 1.0) * 25
    # 最近几组历史复盘显示，过高量比经常不是干净吸筹，而是偏后排的情绪热度。
    # 因此 1.2 到 1.3 附近给最高分；如果用户放宽量比上限，分数会逐步衰减。
    s_vr = max(1 - abs(float(row["volume_ratio"]) - 1.25) / 0.75, 0) * 20
    s_mkt = max(1 - float(row["float_mktcap"]) / 80.0, 0) * 15
    s_amp = max(1 - float(row["amplitude"]) / 4.0, 0) * 10
    s_tail = max(min(metrics.get("tail_return_pct", 0) / 2.0, 1.0), 0) * 20
    s_vol = min(metrics.get("tail_volume_ratio", 0) / 2.0, 1.0) * 10
    return round(s_turn + s_vr + s_mkt + s_amp + s_tail + s_vol, 2)


def select_for_date(day: str | pd.Timestamp, params: StrategyParams) -> SelectionResponse:
    """执行某一天完整的文章版选股流程。

    流程顺序：
    1. 大盘环境过滤。
    2. 日线五条件过滤。
    3. 中期趋势检查。
    4. 尾盘分时检查。
    5. 打分排序，并按最大持仓数截断。

    响应里包含每条规则的结果，前端可以展示股票为什么通过或为什么失败。
    """
    day_ts = pd.Timestamp(day).normalize()

    # 第一步先判断大盘环境。大盘不过关时直接返回空选股，避免在弱市场里硬选。
    market = market_tail_rules(day_ts, params)
    market_ok = all(r.passed for r in market) if params.require_market_up else True

    # 第二步做日线条件过滤，得到基础候选池。
    screened, base_count = daily_screen(day_ts, params)
    selected: list[SelectedStock] = []
    if market_ok and not screened.empty:
        # 第三步逐只股票做趋势和尾盘分时检查。分钟数据是按股票单文件读取的，
        # 所以只有经过日线过滤的少量候选才进入这里，避免全市场分钟数据扫描过慢。
        for _, row in screened.iterrows():
            code = str(row["ts_code"])
            rules = [
                rule("日内振幅上限", row["amplitude"] <= params.max_amplitude, row["amplitude"], f"<= {params.max_amplitude}%"),
                rule("流通市值上限", row["float_mktcap"] <= params.max_float_mktcap, row["float_mktcap"], f"<= {params.max_float_mktcap}亿"),
                rule("换手率3%以上", row["turnover_rate"] >= params.min_turnover_rate, row["turnover_rate"], f">= {params.min_turnover_rate}%"),
                rule("量比1.2以上", row["volume_ratio"] >= params.min_volume_ratio, row["volume_ratio"], f">= {params.min_volume_ratio}"),
                rule("量比不过热", row["volume_ratio"] <= params.max_volume_ratio, row["volume_ratio"], f"<= {params.max_volume_ratio}"),
                rule("近期出现涨停", True, "yes", f"近{params.limitup_lookback}日 pct_chg>=9.9%"),
            ]
            trend = trend_rules(code, day_ts, params)
            intraday, metrics = stock_tail_metrics(code, day_ts, params)
            all_rules = rules + trend + intraday
            if (not params.require_intraday_checks or all(r.passed for r in trend + intraday)):
                # 通过全部硬条件后才进入已选列表。这里同时保存关键指标，前端表格
                # 就能直接展示市值、换手、量比、尾盘涨幅等复盘信息。
                selected.append(SelectedStock(
                    code=code,
                    name=str(row.get("name", code)),
                    trade_date=str(day_ts.date()),
                    score=score_row(row, metrics),
                    buy_price=round(metrics.get("buy_price"), 4) if metrics.get("buy_price") else None,
                    rules=all_rules,
                    float_mktcap=round(float(row["float_mktcap"]), 4),
                    turnover_rate=round(float(row["turnover_rate"]), 4),
                    volume_ratio=round(float(row["volume_ratio"]), 4),
                    amplitude=round(float(row["amplitude"]), 4),
                    tail_return_pct=round(metrics.get("tail_return_pct", 0.0), 4),
                    close_vs_vwap_pct=round(metrics.get("close_vs_vwap_pct", 0.0), 4),
                    tail_volume_ratio=round(metrics.get("tail_volume_ratio", 0.0), 4),
                ))

    # 持仓数量有限时，按排序分从高到低取参数规定数量的股票。
    selected.sort(key=lambda x: x.score, reverse=True)
    return SelectionResponse(
        trade_date=str(day_ts.date()),
        benchmark_code=settings.benchmark_code,
        market_rules=market,
        total_candidates=base_count,
        selected=selected[: params.max_positions],
    )
