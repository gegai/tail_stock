from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    app_name: str = "Article Tail Strategy"
    data_root: Path = Path("D:/股票数据")
    storage_root: Path = Path("storage")
    cors_origins: list[str] = [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    benchmark_code: str = "000300.SH"
    default_lookback_days: int = 20
    default_take_profit_pct: float = 3.0
    default_stop_loss_pct: float = 3.0
    default_max_trade_loss_pct: float = 5.0
    default_max_position_pct: float = 0.30
    default_commission_rate: float = 0.0015


settings = Settings()
