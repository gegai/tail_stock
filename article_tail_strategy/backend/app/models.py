from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class StrategyParams(BaseModel):
    max_float_mktcap: float = Field(default=80.0, ge=1, description="流通市值上限，亿元")
    min_turnover_rate: float = Field(default=3.0, ge=0, description="换手率下限，%")
    min_volume_ratio: float = Field(default=1.2, ge=0, description="量比下限")
    max_volume_ratio: float = Field(default=1.3, ge=0, description="量比上限")
    max_amplitude: float = Field(default=4.0, ge=0, description="日内振幅上限，%")
    limitup_lookback: int = Field(default=20, ge=1, le=120, description="涨停回看交易日数")

    require_market_up: bool = True
    require_intraday_checks: bool = True
    require_index_above_ma20: bool = True
    min_market_tail_return_pct: float = Field(default=0.15, ge=0, description="Minimum index return after 14:30, %")
    min_tail_return_pct: float = Field(default=0.30, ge=0, description="Minimum stock return after 14:30, %")
    min_close_vs_vwap_pct: float = Field(default=0.10, ge=0, description="Minimum close premium versus VWAP, %")
    max_recent_amplitude_pct: float = Field(default=7.0, ge=0, description="Recent average amplitude limit, %")
    recent_amplitude_lookback: int = Field(default=5, ge=2, le=20, description="Recent amplitude lookback days")
    max_morning_vwap_band_pct: float = Field(default=1.0, ge=0, description="围绕均价线震荡阈值，%")
    tail_volume_multiplier: float = Field(default=1.0, ge=0, description="尾盘放量倍数")
    max_positions: int = Field(default=2, ge=1, le=100)


class BacktestParams(StrategyParams):
    start_date: date
    end_date: date
    initial_capital: float = Field(default=100_000.0, ge=10_000)
    max_position_pct: float = Field(default=0.30, gt=0, le=1)
    take_profit_pct: float = Field(default=5.0, ge=0)
    stop_loss_pct: float = Field(default=5.0, ge=0)
    max_trade_loss_pct: float = Field(default=5.0, ge=0, description="单笔最大可承受亏损，%")
    market_tail_weak_pct: float = Field(default=-0.3, le=0, description="大盘尾盘走弱阈值，%")
    trend_break_ma_window: int = Field(default=5, ge=2, le=20, description="趋势走坏短均线窗口")
    trend_exit_after_days: int = Field(default=3, ge=1, le=20, description="持有满几天后启用趋势走坏卖出")
    max_hold_days: int = Field(default=5, ge=1, le=20, description="最多持有交易日数")
    enable_trend_exit: bool = True
    commission_rate: float = Field(default=0.0015, ge=0, le=0.05)


class RuleResult(BaseModel):
    name: str
    passed: bool
    actual: float | str | None = None
    threshold: str | None = None
    note: str = ""


class SelectedStock(BaseModel):
    code: str
    name: str
    trade_date: str
    score: float
    buy_price: float | None = None
    rules: list[RuleResult]

    float_mktcap: float | None = None
    turnover_rate: float | None = None
    volume_ratio: float | None = None
    amplitude: float | None = None
    tail_return_pct: float | None = None
    close_vs_vwap_pct: float | None = None
    tail_volume_ratio: float | None = None


class SelectionResponse(BaseModel):
    trade_date: str
    benchmark_code: str
    market_rules: list[RuleResult]
    total_candidates: int
    selected: list[SelectedStock]


class TradeRecord(BaseModel):
    code: str
    name: str
    buy_date: str
    buy_time: str
    sell_date: str
    sell_time: str
    buy_price: float
    sell_price: float
    shares: int
    buy_amount: float
    sell_amount: float
    return_pct: float
    profit: float
    exit_reason: Literal[
        "take_profit",
        "stop_loss",
        "max_loss",
        "market_tail_weak",
        "trend_broken",
        "close",
        "no_next_day",
    ]


class NavPoint(BaseModel):
    date: str
    nav: float
    benchmark_nav: float
    drawdown: float


class Metrics(BaseModel):
    total_return: float
    annualized_return: float
    max_drawdown: float
    win_rate: float
    trade_count: int
    benchmark_total_return: float


class BacktestResponse(BaseModel):
    params: BacktestParams
    metrics: Metrics
    nav_series: list[NavPoint]
    trades: list[TradeRecord]
    selections: list[SelectionResponse]


class BacktestRecordSummary(BaseModel):
    id: str
    created_at: str
    start_date: str
    end_date: str
    total_return: float
    max_drawdown: float
    win_rate: float
    trade_count: int


class BacktestStartResponse(BaseModel):
    job_id: str


class BacktestProgress(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "error"]
    percent: int = 0
    stage: str = "等待开始"
    current_date: str | None = None
    result: BacktestResponse | None = None
    error: str | None = None


class DataInfo(BaseModel):
    data_root: str
    daily_available: bool
    stock_basic_available: bool
    stock_15min_count: int
    stock_1min_count: int
    index_15min_count: int
    index_1min_count: int
    daily_start: str | None = None
    daily_end: str | None = None
    stock_count: int | None = None


class MinuteBar(BaseModel):
    dt: str
    open: float
    high: float
    low: float
    close: float
    vol: float
    vwap: float


class MinuteResponse(BaseModel):
    code: str
    trade_date: str
    bars: list[MinuteBar]


class StockWindowDay(BaseModel):
    trade_date: str
    bars: list[MinuteBar]


class StockWindowResponse(BaseModel):
    code: str
    name: str | None = None
    center_date: str
    days: list[StockWindowDay]
