from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class StrategyParams(BaseModel):
    """选股策略参数。

    这些字段对应文章里的大盘过滤、日线过滤、尾盘分时确认和最大持仓数。
    前端“选股”和“回测”共用这组基础参数。
    """
    max_float_mktcap: float = Field(default=80.0, ge=1, description="流通市值上限，亿元")
    min_turnover_rate: float = Field(default=3.0, ge=0, description="换手率下限，%")
    min_volume_ratio: float = Field(default=1.2, ge=0, description="量比下限")
    max_volume_ratio: float = Field(default=1.3, ge=0, description="量比上限")
    max_amplitude: float = Field(default=4.0, ge=0, description="日内振幅上限，%")
    limitup_lookback: int = Field(default=20, ge=1, le=120, description="涨停回看交易日数")

    require_market_up: bool = True
    require_intraday_checks: bool = True
    require_index_above_ma20: bool = True
    min_market_tail_return_pct: float = Field(default=0.05, ge=0, description="大盘14:30后最低涨幅，%")
    min_tail_return_pct: float = Field(default=0.20, ge=0, description="个股14:30后最低涨幅，%")
    min_close_vs_vwap_pct: float = Field(default=0.10, ge=0, description="收盘价高于均价线的最低幅度，%")
    max_recent_amplitude_pct: float = Field(default=7.0, ge=0, description="近期平均振幅上限，%")
    recent_amplitude_lookback: int = Field(default=5, ge=2, le=20, description="近期振幅回看交易日数量")
    max_morning_vwap_band_pct: float = Field(default=1.0, ge=0, description="围绕均价线震荡阈值，%")
    tail_volume_multiplier: float = Field(default=1.0, ge=0, description="尾盘放量倍数")
    max_positions: int = Field(default=2, ge=1, le=100)


class BacktestParams(StrategyParams):
    """回测参数。

    继承 StrategyParams 后，额外加入资金、仓位、止盈止损、持有天数、
    手续费等交易模拟参数。
    """
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
    commission_rate: float = Field(default=0.001, ge=0, le=0.05)


class RuleResult(BaseModel):
    """单条规则的执行结果。

    前端用它展示“规则名称、是否通过、实际值、阈值、备注”，便于复盘。
    """
    name: str
    passed: bool
    actual: float | str | None = None
    threshold: str | None = None
    note: str = ""


class SelectedStock(BaseModel):
    """单日选股结果中的一只股票。"""
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
    """单日选股接口响应。"""
    trade_date: str
    benchmark_code: str
    market_rules: list[RuleResult]
    total_candidates: int
    selected: list[SelectedStock]


class TradeRecord(BaseModel):
    """一笔完整买卖交易记录。"""
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
    """净值曲线上的一个交易日点位。"""
    date: str
    nav: float
    benchmark_nav: float
    drawdown: float


class Metrics(BaseModel):
    """回测核心绩效指标。"""
    total_return: float
    annualized_return: float
    max_drawdown: float
    win_rate: float
    trade_count: int
    benchmark_total_return: float


class BacktestResponse(BaseModel):
    """完整回测结果，包括参数、指标、净值、交易和每日选股。"""
    params: BacktestParams
    metrics: Metrics
    nav_series: list[NavPoint]
    trades: list[TradeRecord]
    selections: list[SelectionResponse]


class BacktestRecordSummary(BaseModel):
    """本地回测记录列表里展示的摘要信息。"""
    id: str
    created_at: str
    start_date: str
    end_date: str
    total_return: float
    annualized_return: float = 0.0
    max_drawdown: float
    win_rate: float
    trade_count: int


class BacktestStartResponse(BaseModel):
    """启动后台回测后返回给前端的任务编号。"""
    job_id: str


class BacktestProgress(BaseModel):
    """后台回测任务的轮询状态。"""
    job_id: str
    status: Literal["queued", "running", "done", "error"]
    percent: int = 0
    stage: str = "等待开始"
    current_date: str | None = None
    result: BacktestResponse | None = None
    error: str | None = None


class SweepRange(BaseModel):
    """参数优化中某一个字段的候选值列表。"""
    name: str
    values: list[float | int | bool]


class OptimizationParams(BaseModel):
    """参数优化请求。

    base_params 是基础回测参数；ranges 定义哪些字段需要遍历；
    并行进程数控制同时运行的子进程数量；组合上限用于防止候选参数爆炸。
    """
    base_params: BacktestParams
    ranges: list[SweepRange]
    max_workers: int = Field(default=6, ge=1, le=12)
    max_combinations: int = Field(default=6000, ge=1, le=10000)
    min_trade_count: int = Field(default=80, ge=0)
    max_drawdown_limit: float = Field(default=-0.20, le=0)
    top_n: int = Field(default=20, ge=1, le=100)


class OptimizationResultItem(BaseModel):
    """参数优化中单组参数的回测摘要和评分。"""
    params: dict[str, Any]
    total_return: float
    annualized_return: float
    max_drawdown: float
    win_rate: float
    trade_count: int
    benchmark_total_return: float
    score: float
    yearly_returns: dict[str, float] = Field(default_factory=dict)


class OptimizationStartResponse(BaseModel):
    """启动参数优化后返回给前端的任务编号。"""
    job_id: str


class OptimizationProgress(BaseModel):
    """参数优化任务的轮询状态和当前前若干名结果。"""
    job_id: str
    status: Literal["queued", "running", "done", "error", "cancelled"]
    percent: int = 0
    completed: int = 0
    total: int = 0
    stage: str = "等待开始"
    best: list[OptimizationResultItem] = Field(default_factory=list)
    error: str | None = None


class OptimizationRecord(BaseModel):
    """本地保存的一次参数优化任务，包含请求、进度和已完成结果。"""
    id: str
    created_at: str
    updated_at: str
    request: OptimizationParams
    progress: OptimizationProgress
    results: list[OptimizationResultItem] = Field(default_factory=list)


class OptimizationRecordSummary(BaseModel):
    """参数优化历史列表摘要。"""
    id: str
    created_at: str
    updated_at: str
    status: Literal["queued", "running", "done", "error", "cancelled"]
    start_date: str
    end_date: str
    completed: int
    total: int
    best_score: float | None = None
    best_total_return: float | None = None
    best_annualized_return: float | None = None
    error: str | None = None


class DataInfo(BaseModel):
    """本地数据目录概况。"""
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
    """前端分钟图使用的一根 K 线。"""
    dt: str
    open: float
    high: float
    low: float
    close: float
    vol: float
    vwap: float


class MinuteResponse(BaseModel):
    """单日分钟图接口响应。"""
    code: str
    trade_date: str
    bars: list[MinuteBar]


class StockWindowDay(BaseModel):
    """股票前后 N 天分钟图中的单日数据。"""
    trade_date: str
    bars: list[MinuteBar]


class StockWindowResponse(BaseModel):
    """股票前后 N 天分钟图接口响应。"""
    code: str
    name: str | None = None
    center_date: str
    days: list[StockWindowDay]
