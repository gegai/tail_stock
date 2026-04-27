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

# ProgressCallback(percent, stage, current_date)
# The service layer stays independent from FastAPI. The API can pass a callback
# to publish progress, while tests and scripts can call run_backtest directly.
ProgressCallback = Callable[[int, str, str | None], None]


def _market_tail_is_weak(day: pd.Timestamp, params: BacktestParams) -> bool:
    """Return whether the benchmark weakens during the tail session.

    This implements the sell table's "尾盘大盘走弱，减仓或清仓，避免隔夜".
    Because a backtest should not sell at 14:30 using information from 15:00,
    the action is applied at the final bar once the tail-session weakness is
    observable. The strategy is already a T+1 workflow, so this is a defensive
    close rather than a fresh overnight hold.
    """
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
    """Compute an intraday running VWAP from minute bars.

    Some market files use different amount units, but stock minute files are
    internally consistent enough for an exit-line check. If volume is missing,
    callers fall back to close-level behavior rather than crashing a backtest.
    """
    vol = bars["vol"].replace(0, pd.NA).cumsum()
    return (bars["amount"].cumsum() / vol).ffill().fillna(bars["close"])


def _trend_broken(bars_so_far: pd.DataFrame, params: BacktestParams) -> bool:
    """Detect whether next-day price shape has deteriorated.

    The table says "趋势完成、价格形态走坏，落袋为安" but does not prescribe a
    formula. Here it becomes deterministic: after enough bars are available,
    close must be below both the running VWAP and a short moving average, and
    the latest close must also be lower than the prior close. That combination
    catches a fading intraday trend without treating ordinary small pullbacks
    as a sell signal.
    """
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
    """Apply the sell table across a 3-5 day style holding window.

    The sell table contains five scenarios, all converted into reproducible
    rules:

    1. 高开或冲高: if high touches the take-profit target, sell there.
    2. 个股跌破预设止损位: if low touches stop_loss_pct, stop out.
    3. 单笔亏损达到最大承受额度: if low touches max_trade_loss_pct, exit.
    4. 趋势完成、价格形态走坏: close below VWAP and short MA, sell at close.
    5. 尾盘大盘走弱: if benchmark tail return is weak, clear at that day close.

    Loss exits are checked before profit exits inside the same 15-minute bar,
    a conservative tie-break because intrabar order is not known. Trend exits
    start only after trend_exit_after_days, so a T+1 shakeout does not
    immediately cancel the 3-5 day experiment.
    """
    target = buy_price * (1 + params.take_profit_pct / 100)
    stop = buy_price * (1 - params.stop_loss_pct / 100) if params.stop_loss_pct > 0 else None
    max_loss = buy_price * (1 - params.max_trade_loss_pct / 100) if params.max_trade_loss_pct > 0 else None
    days = trading_days()
    pos = days.searchsorted(pd.Timestamp(buy_day).normalize())
    future_days = days[pos + 1: pos + 1 + params.max_hold_days]
    last_seen: tuple[float, str, str] | None = None

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
            if loss_triggers:
                price, reason = max(loss_triggers, key=lambda item: item[0])
                return round(price, 4), reason, sell_date, sell_time
            if float(row["high"]) >= target:
                return round(target, 4), "take_profit", sell_date, sell_time
            if hold_day >= params.trend_exit_after_days and _trend_broken(bars.iloc[:bar_pos], params):
                return round(float(row["close"]), 4), "trend_broken", sell_date, sell_time

        final_row = bars.iloc[-1]
        final_time = pd.Timestamp(final_row["trade_time"]).strftime("%H:%M")
        if _market_tail_is_weak(day, params):
            return round(float(final_row["close"]), 4), "market_tail_weak", str(pd.Timestamp(day).date()), final_time

    if last_seen is None:
        return buy_price, "no_next_day", "N/A", "N/A"
    price, sell_date, sell_time = last_seen
    return price, "close", sell_date, sell_time


def _sell_next_day(code: str, next_day: pd.Timestamp, buy_price: float, params: BacktestParams) -> tuple[float, str, str]:
    """Backward-compatible helper for tests that need the old T+1 shape."""
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
    """Convert a cash allocation into A-share board-lot shares.

    A-shares normally trade in lots of 100 shares. Rounding down prevents the
    backtest from spending more cash than the configured position cap allows.
    """
    if price <= 0:
        return 0
    return int(allocation / price / 100) * 100


def _close_price_on_day(code: str, day: pd.Timestamp, fallback: float) -> float:
    """Return a stock's final intraday close for mark-to-market accounting."""
    bars = load_stock_minutes(code, day, "15min")
    if bars.empty:
        return fallback
    return float(bars.iloc[-1]["close"])


def _benchmark_nav(start: str, end: str, nav_index: pd.DatetimeIndex) -> pd.Series:
    """Return沪深300 normalized NAV aligned to strategy dates."""
    bench = load_index_daily(settings.benchmark_code, start, end)
    if bench.empty:
        return pd.Series(1.0, index=nav_index)
    close = bench.set_index("trade_date")["close"].reindex(nav_index, method="ffill")
    if close.dropna().empty:
        return pd.Series(1.0, index=nav_index)
    close = close.ffill().bfill()
    return close / close.iloc[0]


def _metrics(nav: pd.Series, benchmark_nav: pd.Series, trades: list[TradeRecord]) -> Metrics:
    """Compute the compact performance numbers shown by the frontend."""
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
    """Run the full article-style backtest.

    The simulation follows the article's short-term workflow rather than a
    weekly/monthly rebalance:

    - T day: run big-market, daily-screen, trend, and tail-session checks.
    - T day tail close: buy selected stocks, capped by max_position_pct.
    - D+1..D+max_hold_days: apply the sell table: take-profit, stop-loss,
      max-loss, trend-broken exit, market-tail-weak clear, otherwise close.

    The optional progress callback is called after each trading day so the API
    can expose real-time progress to the UI. It has no side effects on results.
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

        marked_positions = 0.0
        for pos in open_positions:
            mark = _close_price_on_day(pos["code"], day, pos["last_mark"])
            pos["last_mark"] = mark
            marked_positions += pos["shares"] * mark
        equity_before_buys = cash + marked_positions

        if pd.Timestamp(day).normalize() not in buy_day_set:
            nav_by_day[day] = equity_before_buys / params.initial_capital
            continue

        selection = select_for_date(day, params)
        selections.append(selection)

        picks = [s for s in selection.selected if s.buy_price and s.buy_price > 0]
        if not picks:
            nav_by_day[day] = equity_before_buys / params.initial_capital
            continue

        # When several stocks are selected, split available capital equally, but
        # never exceed the article-inspired single-stock cap (default 30%).
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

        marked_after_buys = 0.0
        for pos in open_positions:
            mark = _close_price_on_day(pos["code"], day, pos["last_mark"])
            pos["last_mark"] = mark
            marked_after_buys += pos["shares"] * mark
        nav_by_day[day] = (cash + marked_after_buys) / params.initial_capital

    if progress:
        progress(96, "计算净值、回撤和基准", None)

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
