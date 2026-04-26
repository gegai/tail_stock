from pydantic import BaseModel, Field
from datetime import date
from typing import Literal


class BacktestParams(BaseModel):
    start_date: date = Field(default=date(2020, 1, 1))
    end_date: date = Field(default=date(2024, 12, 31))

    max_float_mktcap: float = Field(default=200.0, ge=10, le=5000, description="流通市值上限（亿元）")
    min_turnover_rate: float = Field(default=3.0, ge=0, le=50, description="换手率下限（%）")
    min_volume_ratio: float = Field(default=1.2, ge=0.1, le=10, description="量比下限")
    max_amplitude: float = Field(default=5.0, ge=0.1, le=20, description="振幅上限（%）")
    limitup_lookback: int = Field(default=20, ge=5, le=60, description="涨停回看天数")
    max_positions: int = Field(default=5, ge=1, le=100, description="最大持仓数量")

    frequency: Literal["daily", "weekly", "monthly"] = Field(default="daily")
    buy_timing: Literal["t1_open", "t_close"] = Field(
        default="t1_open",
        description="t1_open=T+1日09:30开盘价；t_close=T日收盘价（近似14:30尾盘）",
    )
    initial_capital: float = Field(default=100_000.0, ge=10_000)
    commission_rate: float = Field(default=0.0015, ge=0, le=0.01, description="单边手续费率")


class PerformanceMetrics(BaseModel):
    annualized_return: float
    annualized_volatility: float
    max_drawdown: float
    sharpe_ratio: float
    calmar_ratio: float
    win_rate: float
    total_return: float
    alpha: float
    beta: float
    benchmark_annualized_return: float


class NavPoint(BaseModel):
    date: str
    strategy_nav: float
    benchmark_nav: float
    drawdown: float


class HoldingStock(BaseModel):
    code: str
    name: str
    market_cap: float
    turnover_rate: float
    weight: float


class StockTradeDetail(BaseModel):
    code: str
    name: str
    # 买入
    buy_date: str
    buy_time: str = "09:30"     # 开盘集合竞价成交时间
    buy_price: float            # T+1 开盘价
    shares: int = 0             # 买入股数（100的倍数）
    lots: int = 0               # 手数（shares / 100）
    buy_amount: float = 0.0     # 买入金额（元）
    # 卖出（None 表示仍持有）
    sell_date: str | None = None
    sell_time: str | None = None
    sell_price: float | None = None
    sell_amount: float | None = None   # 卖出金额（元）
    # 结果
    hold_days: int | None = None
    profit: float | None = None        # 绝对收益（元）
    return_pct: float | None = None    # 收益率（%）


class TradeStock(BaseModel):
    code: str
    name: str


class SelectionEntry(BaseModel):
    code: str
    name: str
    status: str              # "买入" | "持有"
    float_mktcap: float      # 亿元
    turnover_rate: float     # %
    volume_ratio: float
    amplitude: float         # %
    score: float = 0.0       # 综合评分 0-100


class SelectionRecord(BaseModel):
    date: str                # 选股日（T日）
    stocks: list[SelectionEntry]


class TradeRecord(BaseModel):
    rebalance_date: str         # T日：选股日（收盘后）
    exec_date: str              # T+1日：执行日（开盘买卖）
    bought: list[StockTradeDetail]   # 新买入（含买入价）
    sold: list[StockTradeDetail]     # 卖出（含买入价、卖出价、收益）
    held: list[TradeStock]           # 持续持有（不动）
    portfolio_size: int
    turnover_ratio: float       # 换手比例 0-1
    trade_cost_pct: float       # 交易成本占净值比例（%）


class BacktestResult(BaseModel):
    params: BacktestParams
    metrics: PerformanceMetrics
    nav_series: list[NavPoint]
    current_holdings: list[HoldingStock]
    trade_records: list[TradeRecord]
    selection_log: list[SelectionRecord]  # 每个换仓日的完整选股快照（含筛选指标）
