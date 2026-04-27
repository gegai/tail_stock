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
    if isinstance(actual, (float, np.floating)) and math.isfinite(float(actual)):
        actual = round(float(actual), 4)
    return RuleResult(name=name, passed=bool(passed), actual=actual, threshold=threshold, note=note)


def _time_part(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.strftime("%H:%M")


def market_tail_rules(day: str | pd.Timestamp, params: StrategyParams) -> list[RuleResult]:
    """Translate the article's market condition into two machine rules.

    The article says to check the market after 14:30 and avoid entering when the
    index is weak or dumping on volume. We implement that as:

    - 沪深300 14:30-to-close close return must be positive.
    - 放量大跌 means three conditions happen together: full-day return <= -1.5%,
      14:30-to-close return <= -0.3%, and tail-session volume is at least 1.5x
      the earlier intraday average volume.
    """
    df = load_index_minutes(settings.benchmark_code, day, "15min")
    if df.empty:
        return [rule("大盘15分钟数据可用", False, "missing", note="未找到沪深30015分钟数据")]

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
    crash = day_ret <= -1.5 and tail_ret <= -0.3 and tail_vol_ratio >= 1.5
    index_trend_rule = _index_ma20_rule(day, params)

    # The first versions accepted any positive tail return. Backtest review
    # showed that many "barely red-to-green" index tails still led to weak
    # next-day trades, so this quality version requires a configurable minimum
    # tail-session index gain before allowing new positions.
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
    """Require the benchmark to close above MA20 before buying.

    The recent record review showed that buying when HS300 was below MA20 had
    much worse win rate and PnL. This is a market-regime gate, separate from
    the 14:30 tail rule: the tail can bounce while the broader index trend is
    still unhealthy.
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
    """Apply the article's five objective daily filters.

    This function deliberately keeps only rules that can be known at the T-day
    close: daily amplitude, current-day circulating market cap, turnover,
    volume ratio, and recent limit-up history.
    """
    raw = load_daily_date(day)
    df = enrich_daily(raw)
    if df.empty:
        return df, 0

    df = df[df["list_status"].fillna("L") == "L"].copy()
    df = df[~df["is_st"].fillna(False).astype(bool)]
    # Historical is_st flags can be stale. The name guard prevents ST/*ST rows
    # from slipping into selection when the daily flag is missing or wrong.
    df = df[~df["name"].fillna("").astype(str).str.upper().str.contains("ST", regex=False)]
    df = df[df["suspend_type"].fillna("N") == "N"]
    df = df[df["listed_days"].fillna(0) >= 60]
    df = df[df["close"].notna() & (df["close"] > 0)]
    base_count = len(df)

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
    limitup_codes = set(hist.loc[hist["pct_chg"] >= 9.9, "ts_code"].unique())
    df = df[df["ts_code"].isin(limitup_codes)]
    return df, base_count


def stock_tail_metrics(code: str, day: str | pd.Timestamp, params: StrategyParams) -> tuple[list[RuleResult], dict]:
    """Quantify the article's tail-session price/volume description.

    The article's language is discretionary: "回踩均价线不破", "分时上升",
    "持续有大单买入". Because the data does not include order-book large-order
    tags, large-order buying is approximated by tail-session volume expansion.
    Each approximation is returned as a visible rule so users can audit it.
    """
    df = load_stock_minutes(code, day, "15min")
    if df.empty:
        return [rule("个股15分钟数据可用", False, "missing")], {}

    times = _time_part(df["trade_time"])
    amount_cum = df["amount"].cumsum()
    vol_cum = df["vol"].replace(0, pd.NA).cumsum()
    vwap = (amount_cum / vol_cum).ffill().fillna(df["close"])
    df = df.copy()
    df["vwap"] = vwap

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

    # These are the core quality gates for the stock's final 30 minutes.
    # A small positive tick is not enough: price must have a meaningful
    # 14:30-to-close rise and finish above the intraday VWAP by a buffer.
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
    """Approximate the article's medium-term uptrend requirement.

    The article prefers stocks in a clear medium-term uptrend after short-term
    washout. We model this with close > MA20 > MA60 and a recent pullback that
    is not already overheated.
    """
    lookback = previous_trading_dates(day, 80)
    if len(lookback) < 60:
        return [rule("中期趋势数据足够", False, len(lookback), ">=60")]
    hist = load_daily_range(str(lookback[0].date()), str(pd.Timestamp(day).date()), ["close", "high", "low", "pre_close"])
    hist = hist[hist["ts_code"] == code].sort_values("trade_date")
    if len(hist) < 60:
        return [rule("中期趋势数据足够", False, len(hist), ">=60")]
    close = hist["close"]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    last = close.iloc[-1]
    prev5 = close.iloc[-6:-1].max()
    pullback = (last / prev5 - 1) * 100 if prev5 else 0.0
    # Avoid chasing stocks whose recent swings are already too wide. The
    # strategy buys near the close and then holds overnight, so high recent
    # amplitude usually means the stop-loss is easier to hit before take-profit.
    recent = hist.tail(params.recent_amplitude_lookback)
    recent_amp = ((recent["high"] - recent["low"]) / recent["pre_close"].replace(0, np.nan) * 100).mean()
    return [
        rule("中期上升趋势", last > ma20 > ma60, f"close={last:.2f}, ma20={ma20:.2f}, ma60={ma60:.2f}", "close > MA20 > MA60"),
        rule("短期回调未过热", pullback <= 5.0, pullback, "<= 5%"),
        rule("近几日波动不过大", recent_amp <= params.max_recent_amplitude_pct, recent_amp, f"<= {params.max_recent_amplitude_pct}%"),
    ]


def score_row(row: pd.Series, metrics: dict) -> float:
    s_turn = min(float(row["turnover_rate"]) / 6.0, 1.0) * 25
    # The latest history review showed that very high volume_ratio was often
    # late-stage heat rather than clean accumulation. Score the 1.2-1.3 area
    # highest and taper down if users relax max_volume_ratio in experiments.
    s_vr = max(1 - abs(float(row["volume_ratio"]) - 1.25) / 0.75, 0) * 20
    s_mkt = max(1 - float(row["float_mktcap"]) / 80.0, 0) * 15
    s_amp = max(1 - float(row["amplitude"]) / 4.0, 0) * 10
    s_tail = max(min(metrics.get("tail_return_pct", 0) / 2.0, 1.0), 0) * 20
    s_vol = min(metrics.get("tail_volume_ratio", 0) / 2.0, 1.0) * 10
    return round(s_turn + s_vr + s_mkt + s_amp + s_tail + s_vol, 2)


def select_for_date(day: str | pd.Timestamp, params: StrategyParams) -> SelectionResponse:
    """Run the complete article-style selection pipeline for one day.

    Pipeline order:
    1. Market filter.
    2. Daily five-condition pool.
    3. Trend checks.
    4. Tail-session intraday checks.
    5. Score and cap to max_positions.

    The response includes every rule result so the frontend can show exactly why
    a stock passed or failed.
    """
    day_ts = pd.Timestamp(day).normalize()
    market = market_tail_rules(day_ts, params)
    market_ok = all(r.passed for r in market) if params.require_market_up else True

    screened, base_count = daily_screen(day_ts, params)
    selected: list[SelectedStock] = []
    if market_ok and not screened.empty:
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

    selected.sort(key=lambda x: x.score, reverse=True)
    return SelectionResponse(
        trade_date=str(day_ts.date()),
        benchmark_code=settings.benchmark_code,
        market_rules=market,
        total_candidates=base_count,
        selected=selected[: params.max_positions],
    )
