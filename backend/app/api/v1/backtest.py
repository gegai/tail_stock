from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.concurrency import run_in_threadpool
import logging

from ...models.schemas import BacktestParams, BacktestResult
from ...services.backtester import run_backtest

router = APIRouter(prefix="/backtest", tags=["backtest"])
logger = logging.getLogger(__name__)

# 简单内存缓存（避免重复计算相同参数）
_result_cache: dict[str, BacktestResult] = {}


def _cache_key(params: BacktestParams) -> str:
    return (
        f"{params.start_date}_{params.end_date}"
        f"_{params.max_float_mktcap}_{params.min_turnover_rate}"
        f"_{params.min_volume_ratio}_{params.max_amplitude}"
        f"_{params.limitup_lookback}_{params.max_positions}"
        f"_{params.frequency}_{params.commission_rate}"
    )


@router.post("/run", response_model=BacktestResult)
async def run_backtest_api(params: BacktestParams):
    """
    运行回测。首次调用会拉取 AKShare 数据并构建价格面板（耗时较长），
    后续调用会使用本地缓存，速度明显加快。
    """
    key = _cache_key(params)
    if key in _result_cache:
        logger.info(f"Cache hit for key: {key}")
        return _result_cache[key]

    try:
        result = await run_in_threadpool(run_backtest, params)
        _result_cache[key] = result
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Backtest failed")
        raise HTTPException(status_code=500, detail=f"回测失败: {str(e)}")


@router.delete("/cache")
async def clear_cache():
    """清除回测结果缓存（用于强制重新拉取数据）"""
    _result_cache.clear()
    return {"message": "缓存已清除"}
