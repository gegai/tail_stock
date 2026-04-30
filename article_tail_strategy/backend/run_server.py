from __future__ import annotations

import os
from multiprocessing import freeze_support
from pathlib import Path

import uvicorn

from app.main import app


def _default_storage_root() -> str:
    """选择一个开发环境和可执行程序打包环境都可写的存储目录。

    优先使用用户配置的存储目录环境变量；如果没有，则在视窗系统下写入用户应用数据目录。
    这样打包成可执行程序后不会把回测记录写到安装目录，避免权限问题。
    """
    if os.getenv("STORAGE_ROOT"):
        return os.environ["STORAGE_ROOT"]
    appdata = os.getenv("APPDATA")
    if appdata:
        return str(Path(appdata) / "article-tail-strategy" / "storage")
    return str(Path.cwd() / "storage")


if __name__ == "__main__":
    # 视窗系统打包后运行多进程参数优化时必须调用这个函数，
    # 否则打包工具和桌面壳场景下子进程可能无法正确启动。
    freeze_support()
    os.environ.setdefault("STORAGE_ROOT", _default_storage_root())

    # 允许通过环境变量改监听地址和端口，桌面壳主进程可按需覆盖。
    host = os.getenv("ARTICLE_STRATEGY_HOST", "127.0.0.1")
    port = int(os.getenv("ARTICLE_STRATEGY_PORT", "8001"))
    uvicorn.run(app, host=host, port=port, reload=False, workers=1)
