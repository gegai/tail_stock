"""
数据信息路由：读取本地 parquet 文件状态（无需从外部拉取数据）。
"""
import logging

from fastapi import APIRouter

from ...services.data_fetcher import get_data_info

router = APIRouter(prefix="/data", tags=["data"])
logger = logging.getLogger(__name__)


@router.get("/cache-info")
async def get_cache_info():
    """
    返回本地 parquet 文件的数据量、日期范围和文件大小。
    前端用 files > 10 判断数据是否就绪。
    """
    info = get_data_info()
    return info
