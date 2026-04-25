"""
回测引擎：驱动尾盘30分钟选股策略。
选股日 T（收盘后）-> 执行日 T+1（开盘价成交），消除未来函数。
"""
import logging
from datetime import date
import pandas as pd
import numpy as np

from ..models.schemas import (
    BacktestParams, BacktestResult, PerformanceMetrics,
    NavPoint, HoldingStock,
)
from .data_fetcher import (
    get_stock_universe, build_ohlcv_panels, get_benchmark_hist,
    build_volume_ratio, build_recent_limitup, build_benchmark_volume_ratio,
)
from .strategy import (
    get_rebalance_dates, build_execution_map,
    is_market_crash, select_by_conditions,
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
    panel_open = panels.get("open", pd.DataFrame())
    panel_turnover = panels.get("turnover", pd.DataFrame())
    panel_amplitude = panels.get("amplitude", pd.DataFrame())
    panel_pct_chg = panels.get("pct_chg", pd.DataFrame())

    if panel_close.empty:
        raise ValueError("价格数据为空，请检查 DATA_DIR 路径和 parquet 文件")

    # 2. Derived panels
    panel_volume_ratio = panels.get("volume_ratio", pd.DataFrame())
    if panel_volume_ratio.empty:
        panel_volume_ratio = build_volume_ratio(panels.get("volume", pd.DataFrame()))

    panel_had_limitup = build_recent_limitup(panel_pct_chg, lookback=params.limitup_lookback)

    # 3. Benchmark (optional — empty means skip market crash filter)
    benchmark_raw = get_benchmark_hist(start_str, end_str)
    if benchmark_raw.empty:
        logger.info("No benchmark data; market crash filter disabled")
        benchmark_df = pd.DataFrame()
    else:
        benchmark_df = benchmark_raw.set_index("date").sort_index()
        bench_vol_ratio = build_benchmark_volume_ratio(benchmark_df)
        benchmark_df["vol_ratio"] = bench_vol_ratio

    # 4. Rebalance / execution dates
    trading_days = panel_close.index
    rebalance_dates = get_rebalance_dates(
        trading_days, params.start_date, params.end_date, params.frequency
    )
    execution_map = build_execution_map(rebalance_dates, trading_days)

    rebalance_set = set(rebalance_dates)
    execution_set = set(execution_map.values())

    all_trading_days = trading_days[
        (trading_days >= pd.Timestamp(params.start_date)) &
        (trading_days <= pd.Timestamp(params.end_date))
    ]

    # 5. Main simulation loop
    nav_value = 1.0
    portfolio: list = []
    prev_portfolio: list = []
    daily_nav: dict = {}
    pending_map: dict = {}  # exec_date -> new_portfolio

    for i, td in enumerate(all_trading_days):

        # T day: select stocks after close
        if td in rebalance_set:
            if not is_market_crash(td, benchmark_df):
                new_codes = select_by_conditions(
                    date=td,
                    universe=universe,
                    panel_close=panel_close,
                    panel_turnover=panel_turnover,
                    panel_volume_ratio=panel_volume_ratio,
                    panel_amplitude=panel_amplitude,
                    panel_had_limitup=panel_had_limitup,
                    params=params,
                )
                exec_date = execution_map.get(td, td)
                pending_map[exec_date] = new_codes

        # T+1 day: execute rebalance at open prices
        if td in execution_set and td in pending_map:
            new_portfolio = pending_map.pop(td)
            if new_portfolio:
                prev_set = set(prev_portfolio)
                new_set = set(new_portfolio)
                if prev_set | new_set:
                    turnover = len(prev_set.symmetric_difference(new_set)) / len(prev_set | new_set)
                    nav_value *= (1 - turnover * params.commission_rate)

                prev_portfolio = new_portfolio
                portfolio = new_portfolio

                if (not panel_open.empty and not panel_close.empty
                        and td in panel_open.index and td in panel_close.index):
                    opens = panel_open.loc[td, portfolio].dropna()
                    closes = panel_close.loc[td, portfolio].dropna()
                    common = opens.index.intersection(closes.index)
                    if len(common) > 0:
                        open_to_close = (closes[common] / opens[common] - 1).mean()
                        nav_value *= (1 + open_to_close)
                    daily_nav[td] = nav_value
                    continue

        # Non-execution day: close-to-close return
        if portfolio and i > 0:
            prev_td = all_trading_days[i - 1]
            if prev_td in panel_close.index and td in panel_close.index:
                prev_p = panel_close.loc[prev_td, portfolio].dropna()
                curr_p = panel_close.loc[td, portfolio].dropna()
                common = prev_p.index.intersection(curr_p.index)
                if len(common) > 0:
                    daily_ret = (curr_p[common] / prev_p[common] - 1).mean()
                    nav_value *= (1 + daily_ret)

        daily_nav[td] = nav_value

    # 6. NAV series
    nav_series = pd.Series(daily_nav).sort_index()
    if nav_series.empty:
        raise ValueError("回测结果为空，请检查参数或数据")
    nav_series = nav_series / nav_series.iloc[0]

    # 7. Benchmark NAV (flat 1.0 when no benchmark available)
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

    # 11. Current holdings (last rebalance date)
    last_rebal = max(rebalance_dates) if rebalance_dates else all_trading_days[-1]
    current_codes = select_by_conditions(
        date=last_rebal,
        universe=universe,
        panel_close=panel_close,
        panel_turnover=panel_turnover,
        panel_volume_ratio=panel_volume_ratio,
        panel_amplitude=panel_amplitude,
        panel_had_limitup=panel_had_limitup,
        params=params,
    )

    u_idx = universe.set_index("code")
    weight = 1.0 / len(current_codes) if current_codes else 0.0
    avail_turn = panel_turnover.index[panel_turnover.index <= last_rebal]
    last_turn_date = avail_turn[-1] if not avail_turn.empty else None

    holdings = []
    for code in current_codes:
        name = str(u_idx.loc[code, "name"]) if code in u_idx.index else code
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

    logger.info(f"Done. ann_ret={metrics.annualized_return:.2%}, holdings={len(holdings)}")
    return BacktestResult(
        params=params, metrics=metrics,
        nav_series=nav_points, current_holdings=holdings,
    )
