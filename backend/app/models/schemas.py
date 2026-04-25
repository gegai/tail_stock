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
    # 买入：T日尾盘 14:50 买入，用收盘价
    buy_date: str
    buy_time: str = "14:50"
    buy_price: float
    shares: int = 0
    lots: int = 0
    buy_amount: float = 0.0
    # 卖出：T+1日开盘 09:30 卖出，用开盘价
    sell_date: str | None = None
    sell_time: str | None = None
    sell_price: float | None = None
    # 结果
    hold_days: int | None = None
    profit: float | None = None
    return_pct: float | None = None


class TradeStock(BaseModel):
    code: str
    name: str


class TradeRecord(BaseModel):
    rebalance_date: str         # T日：选股+买入日（14:50收盘价买入）
    exec_date: str              # T+1日：卖出日（09:30开盘价卖出）
    bought: list[StockTradeDetail]
    sold: list[StockTradeDetail]
    held: list[TradeStock]
    portfolio_size: int
    turnover_ratio: float
    trade_cost_pct: float


class BacktestResult(BaseModel):
    params: BacktestParams
    metrics: PerformanceMetrics
    nav_series: list[NavPoint]
    current_holdings: list[HoldingStock]
    trade_records: list[TradeRecord]
