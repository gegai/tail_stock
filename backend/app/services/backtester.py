"""
回测引擎：尾盘30分钟隔夜短线策略。

时序：
  T日 14:50  按5个条件选股，用收盘价买入
  T+1日 09:30 开盘卖出

每个rebalance日既是买入日也是卖出日（先卖后买）：
  09:30 - 卖出昨日持仓（open价格）
  14:50 - 买入今日新仓（close价格）
"""
import logging
import pandas as pd
import numpy as np

from ..models.schemas import (
    BacktestParams, BacktestResult, PerformanceMetrics,
    NavPoint, HoldingStock, TradeRecord, TradeStock, StockTradeDetail,
)
from .data_fetcher import (
    get_stock_universe, build_ohlcv_panels, get_benchmark_hist,
    build_volume_ratio, build_recent_limitup, build_benchmark_volume_ratio,
)
from .strategy import (
    get_rebalance_dates, is_market_crash, select_by_conditions,
)
from ..core.config import settings

logger = logging.getLogger(__name__)


# -- Performance metrics --------------------------------------------------

def calc_performance(
    nav: pd.Series,
    benchmark: pd.Series,
    params: BacktestParams,
) -> PerformanceMetrics:
    trading_days_per_year = 252
    ret = nav.pct_change().dropna()
    bench_ret = benchmark.pct_change().dropna()
    ret, bench_ret = ret.align(bench_ret, join="inner")

    total_ret = nav.iloc[-1] / nav.iloc[0] - 1
    n_years = len(nav) / trading_days_per_year
    ann_ret = (1 + total_ret) ** (1 / max(n_years, 0.01)) - 1

    bench_total = benchmark.iloc[-1] / benchmark.iloc[0] - 1
    bench_ann = (1 + bench_total) ** (1 / max(n_years, 0.01)) - 1

    ann_vol = ret.std() * np.sqrt(trading_days_per_year)
    rolling_max = nav.cummax()
    max_dd = ((nav - rolling_max) / rolling_max).min()

    sharpe = (ann_ret - settings.risk_free_rate) / ann_vol if ann_vol > 0 else 0.0
    calmar = ann_ret / abs(max_dd) if max_dd < 0 else 0.0
    win_rate = float((ret > 0).mean())

    if len(bench_ret) > 10 and bench_ret.std() > 0:
        cov = np.cov(ret.values, bench_ret.values)
        beta = cov[0, 1] / cov[1, 1]
        alpha = ann_ret - (settings.risk_free_rate + beta * (bench_ann - settings.risk_free_rate))
    else:
        beta, alpha = 1.0, ann_ret - bench_ann

    return PerformanceMetrics(
        annualized_return=round(ann_ret, 4),
        annualized_volatility=round(ann_vol, 4),
        max_drawdown=round(max_dd, 4),
        sharpe_ratio=round(sharpe, 4),
        calmar_ratio=round(calmar, 4),
        win_rate=round(win_rate, 4),
        total_return=round(total_ret, 4),
        alpha=round(alpha, 4),
        beta=round(float(beta), 4),
        benchmark_annualized_return=round(bench_ann, 4),
    )


# -- Main backtest engine -------------------------------------------------

def run_backtest(params: BacktestParams) -> BacktestResult:
    start_str = params.start_date.strftime("%Y-%m-%d")
    end_str = params.end_date.strftime("%Y-%m-%d")
    logger.info(f"Backtest {start_str}->{end_str} freq={params.frequency}")

    # 1. Universe & OHLCV panels
    universe = get_stock_universe()
    all_codes = universe["code"].tolist()
    panels = build_ohlcv_panels(all_codes, start_str, end_str)

    panel_close = panels.get("close", pd.DataFrame())
    panel_open  = panels.get("open",  pd.DataFrame())
    panel_turnover   = panels.get("turnover",     pd.DataFrame())
    panel_amplitude  = panels.get("amplitude",    pd.DataFrame())
    panel_pct_chg    = panels.get("pct_chg",      pd.DataFrame())

    if panel_close.empty:
        raise ValueError("价格数据为空，请检查 DATA_DIR 路径和 parquet 文件")

    # 2. Derived panels
    panel_volume_ratio = panels.get("volume_ratio", pd.DataFrame())
    if panel_volume_ratio.empty:
        panel_volume_ratio = build_volume_ratio(panels.get("volume", pd.DataFrame()))

    panel_had_limitup = build_recent_limitup(panel_pct_chg, lookback=params.limitup_lookback)

    # 3. Benchmark (optional)
    benchmark_raw = get_benchmark_hist(start_str, end_str)
    if benchmark_raw.empty:
        benchmark_df = pd.DataFrame()
    else:
        benchmark_df = benchmark_raw.set_index("date").sort_index()
        benchmark_df["vol_ratio"] = build_benchmark_volume_ratio(benchmark_df)

    # 4. Rebalance dates
    trading_days = panel_close.index
    rebalance_dates = get_rebalance_dates(
        trading_days, params.start_date, params.end_date, params.frequency
    )
    rebalance_set = set(rebalance_dates)

    all_trading_days = trading_days[
        (trading_days >= pd.Timestamp(params.start_date)) &
        (trading_days <= pd.Timestamp(params.end_date))
    ]

    # 5. Main simulation loop
    nav_value = 1.0
    portfolio: list = []          # current overnight holdings
    daily_nav: dict = {}
    trade_records: list = []
    # code -> (buy_date_str, buy_price, shares)
    position_entry: dict[str, tuple[str, float, int]] = {}

    name_map: dict[str, str] = dict(zip(universe["code"], universe["name"]))

    def _name(code: str) -> str:
        return str(name_map.get(code, code))

    def _safe_price(series: pd.Series, code: str) -> float:
        v = series.get(code, float("nan"))
        return float(v) if pd.notna(v) and float(v) > 0 else 0.0

    for i, td in enumerate(all_trading_days):
        td_str = str(td.date())

        open_row = (
            panel_open.loc[td]
            if (not panel_open.empty and td in panel_open.index)
            else pd.Series(dtype=float)
        )
        close_row = (
            panel_close.loc[td]
            if (not panel_close.empty and td in panel_close.index)
            else pd.Series(dtype=float)
        )

        # ── Step A: 09:30 卖出昨日持仓（overnight return: close_{T-1} → open_T） ──
        if portfolio and i > 0:
            prev_td = all_trading_days[i - 1]
            if prev_td in panel_close.index:
                close_prev = panel_close.loc[prev_td]
                codes_c = [c for c in portfolio if c in close_prev.index and c in open_row.index]
                if codes_c:
                    c_prev = close_prev[codes_c].dropna()
                    o_cur  = open_row[codes_c].dropna()
                    common = c_prev.index.intersection(o_cur.index)
                    if len(common) > 0:
                        overnight_ret = float((o_cur[common] / c_prev[common] - 1).mean())
                        nav_value *= (1 + overnight_ret)
                        logger.debug(f"{td_str} overnight ret={overnight_ret:.4%}")

        # ── Step B: 14:50 选股（rebalance日） ──
        new_portfolio = portfolio  # 默认保持不变（非换仓日持现金或不操作）

        if td in rebalance_set:
            if not is_market_crash(td, benchmark_df):
                new_portfolio = select_by_conditions(
                    date=td,
                    universe=universe,
                    panel_close=panel_close,
                    panel_turnover=panel_turnover,
                    panel_volume_ratio=panel_volume_ratio,
                    panel_amplitude=panel_amplitude,
                    panel_had_limitup=panel_had_limitup,
                    params=params,
                )
            else:
                new_portfolio = []  # 大盘放量大跌：当日不买，空仓过夜

        # ── Step C: 换仓记账 & 14:50 买入新仓 ──
        if td in rebalance_set:
            prev_set = set(portfolio)
            new_set  = set(new_portfolio)
            all_involved = prev_set | new_set

            if all_involved:
                changed = len(prev_set.symmetric_difference(new_set))
                turnover_ratio = changed / len(all_involved)
                cost_pct = turnover_ratio * params.commission_rate * 100
                nav_value *= (1 - turnover_ratio * params.commission_rate)
            else:
                turnover_ratio = cost_pct = 0.0

            sold_codes   = sorted(prev_set - new_set)
            bought_codes = sorted(new_set  - prev_set)
            held_codes   = sorted(prev_set & new_set)

            portfolio_value  = nav_value * params.initial_capital
            per_stock_alloc  = portfolio_value / len(new_portfolio) if new_portfolio else 0.0

            # 买入明细（close价格，14:50）
            bought_details: list[StockTradeDetail] = []
            for code in bought_codes:
                buy_price = _safe_price(close_row, code)
                if buy_price > 0:
                    lots   = int(per_stock_alloc / buy_price / 100)
                    shares = lots * 100
                    buy_amount = round(shares * buy_price, 2)
                else:
                    lots = shares = 0
                    buy_amount = 0.0
                bought_details.append(StockTradeDetail(
                    code=code, name=_name(code),
                    buy_date=td_str, buy_time="14:50",
                    buy_price=round(buy_price, 3),
                    shares=shares, lots=lots, buy_amount=buy_amount,
                ))
                position_entry[code] = (td_str, buy_price, shares)

            # 卖出明细（open价格，09:30）
            sold_details: list[StockTradeDetail] = []
            for code in sold_codes:
                sell_price = _safe_price(open_row, code)
                buy_date_str, buy_price, shares = position_entry.pop(code, (td_str, 0.0, 0))
                lots       = shares // 100
                buy_amount = round(shares * buy_price, 2)
                if buy_price > 0 and sell_price > 0 and shares > 0:
                    profit    = round(shares * sell_price - buy_amount, 2)
                    ret       = round((sell_price / buy_price - 1) * 100, 2)
                    hold_days = (td - pd.Timestamp(buy_date_str)).days
                else:
                    profit = ret = hold_days = None
                sold_details.append(StockTradeDetail(
                    code=code, name=_name(code),
                    buy_date=buy_date_str, buy_time="14:50",
                    buy_price=round(buy_price, 3),
                    shares=shares, lots=lots, buy_amount=buy_amount,
                    sell_date=td_str, sell_time="09:30",
                    sell_price=round(sell_price, 3) if sell_price > 0 else None,
                    hold_days=hold_days, profit=profit, return_pct=ret,
                ))

            if bought_details or sold_details:
                trade_records.append(TradeRecord(
                    rebalance_date=td_str,
                    exec_date=td_str,   # 同一天：09:30卖出，14:50买入
                    bought=bought_details,
                    sold=sold_details,
                    held=[TradeStock(code=c, name=_name(c)) for c in held_codes],
                    portfolio_size=len(new_portfolio),
                    turnover_ratio=round(turnover_ratio, 4),
                    trade_cost_pct=round(cost_pct, 4),
                ))

            portfolio = new_portfolio

        daily_nav[td] = nav_value

    # 6. NAV series
    nav_series = pd.Series(daily_nav).sort_index()
    if nav_series.empty:
        raise ValueError("回测结果为空，请检查参数或数据")
    nav_series = nav_series / nav_series.iloc[0]

    # 7. Benchmark NAV
    if not benchmark_df.empty and "close" in benchmark_df.columns:
        bench_close = benchmark_df["close"].reindex(nav_series.index, method="ffill")
        benchmark_nav = bench_close / bench_close.iloc[0]
    else:
        benchmark_nav = pd.Series(1.0, index=nav_series.index)

    # 8. Drawdown
    drawdown_series = (nav_series - nav_series.cummax()) / nav_series.cummax()

    # 9. Performance metrics
    metrics = calc_performance(nav_series, benchmark_nav, params)

    # 10. NavPoint list
    nav_points = [
        NavPoint(
            date=str(ts.date()),
            strategy_nav=round(float(nav_series[ts]), 4),
            benchmark_nav=round(float(benchmark_nav[ts]), 4),
            drawdown=round(float(drawdown_series[ts]), 4),
        )
        for ts in nav_series.index
        if ts in benchmark_nav.index and not np.isnan(float(benchmark_nav[ts]))
    ]

    # 11. Current holdings (最后一次选股结果)
    last_rebal = max(rebalance_dates) if rebalance_dates else all_trading_days[-1]
    current_codes = portfolio  # 最后持仓即当前持仓
    u_idx = universe.set_index("code")
    weight = 1.0 / len(current_codes) if current_codes else 0.0
    avail_turn = panel_turnover.index[panel_turnover.index <= last_rebal]
    last_turn_date = avail_turn[-1] if not avail_turn.empty else None

    holdings = []
    for code in current_codes:
        name   = str(u_idx.loc[code, "name"]) if code in u_idx.index else code
        mktcap = float(u_idx.loc[code, "float_mktcap"]) if (
            code in u_idx.index and "float_mktcap" in u_idx.columns
        ) else 0.0
        turn = float(panel_turnover.loc[last_turn_date, code]) if (
            last_turn_date is not None and code in panel_turnover.columns
        ) else 0.0
        holdings.append(HoldingStock(
            code=code, name=name,
            market_cap=round(mktcap, 2),
            turnover_rate=round(turn, 2),
            weight=round(weight, 4),
        ))
    holdings.sort(key=lambda x: x.turnover_rate, reverse=True)

    logger.info(
        f"Done. ann_ret={metrics.annualized_return:.2%}, "
        f"holdings={len(holdings)}, trades={len(trade_records)}"
    )
    return BacktestResult(
        params=params, metrics=metrics,
        nav_series=nav_points, current_holdings=holdings,
        trade_records=list(reversed(trade_records)),
    )
