from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。

    配置优先级：环境变量 / .env > 这里的默认值。
    打包成 exe 后也可以通过环境变量覆盖数据目录、存储目录或端口。
    """
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    # 应用名称会显示在接口文档和健康检查里。
    app_name: str = "Article Tail Strategy"

    # 本地行情数据根目录。用户当前数据源是 D:/股票数据。
    data_root: Path = Path("D:/股票数据")

    # 回测记录等应用生成数据的存储目录。开发环境默认写到项目内存储目录。
    storage_root: Path = Path("storage")

    # 前端开发服务、预览服务、桌面壳都会通过浏览器访问后端，
    # 所以需要把这些本机地址加入跨域白名单。
    cors_origins: list[str] = [
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4175",
        "http://127.0.0.1:4175",
    ]

    # 默认基准指数，目前使用沪深300。
    benchmark_code: str = "000300.SH"

    # 以下默认参数主要作为后端兜底。前端表单通常会显式传入对应值。
    default_lookback_days: int = 20
    default_take_profit_pct: float = 3.0
    default_stop_loss_pct: float = 3.0
    default_max_trade_loss_pct: float = 5.0
    default_max_position_pct: float = 0.30
    default_commission_rate: float = 0.0015


settings = Settings()
