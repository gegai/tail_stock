from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    app_name: str = "TailSock"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # Parquet data directory (contains stock_daily.parquet, stock_basic_data.parquet)
    data_dir: Path = Path("D:/行情数据")

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    risk_free_rate: float = 0.03
    default_commission: float = 0.0015


settings = Settings()
