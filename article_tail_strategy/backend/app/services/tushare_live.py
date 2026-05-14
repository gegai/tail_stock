from __future__ import annotations

import json
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.config import settings
from app.models import SelectionResponse, StrategyParams, TushareQuote
from app.services.strategy import select_for_date

TUSHARE_URL = "http://api.tushare.pro"


class TushareError(RuntimeError):
    """Raised when the live Tushare selection path cannot get market data."""


def _require_token() -> None:
    if not settings.tushare_token.strip():
        raise TushareError("未配置 TUSHARE_TOKEN，无法运行真实选股。请在后端环境变量或 .env 中配置 Tushare Pro token。")


def _call_tushare(api_name: str, params: dict[str, Any], fields: str = "") -> list[dict[str, Any]]:
    _require_token()
    token = settings.tushare_token.strip()

    payload = json.dumps({
        "api_name": api_name,
        "token": token,
        "params": params,
        "fields": fields,
    }).encode("utf-8")
    request = Request(TUSHARE_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise TushareError(f"Tushare 请求失败：{exc}") from exc

    if body.get("code") != 0:
        raise TushareError(body.get("msg") or "Tushare 返回错误")

    data = body.get("data") or {}
    fields_list = data.get("fields") or []
    items = data.get("items") or []
    return [dict(zip(fields_list, item)) for item in items]


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _quote_from_row(row: dict[str, Any]) -> TushareQuote:
    price = _number(row.get("PRICE") or row.get("price") or row.get("close"))
    pre_close = _number(row.get("PRE_CLOSE") or row.get("pre_close"))
    pct_chg = _number(row.get("PCT_CHANGE") or row.get("pct_chg"))
    if pct_chg is None and price is not None and pre_close:
        pct_chg = (price / pre_close - 1) * 100
    return TushareQuote(
        ts_code=str(row.get("TS_CODE") or row.get("ts_code") or ""),
        name=row.get("NAME") or row.get("name"),
        price=price,
        open=_number(row.get("OPEN") or row.get("open")),
        high=_number(row.get("HIGH") or row.get("high")),
        low=_number(row.get("LOW") or row.get("low")),
        pre_close=pre_close,
        volume=_number(row.get("VOLUME") or row.get("vol")),
        amount=_number(row.get("AMOUNT") or row.get("amount")),
        pct_chg=pct_chg,
        trade_time=str(row.get("TIME") or row.get("trade_time") or "") or None,
    )


def fetch_realtime_quotes(codes: list[str]) -> list[TushareQuote]:
    if not codes:
        return []
    # Tushare 的 realtime_quote 接口支持逗号分隔 ts_code。不同权限返回字段大小写可能有差异，
    # 后续统一在 _quote_from_row 做兼容。
    rows = _call_tushare("realtime_quote", {"ts_code": ",".join(codes)})
    return [_quote_from_row(row) for row in rows if row.get("TS_CODE") or row.get("ts_code")]


def run_live_selection(day: str, params: StrategyParams) -> SelectionResponse:
    """Run the normal strategy and attach Tushare live quotes.

    The strategy rules remain exactly the same as local selection/backtest. Tushare is used as
    the live market data source for the visible quote snapshot, so the page can show the market
    and selected-stock details during real selection.
    """
    _require_token()
    selection = select_for_date(day, params)
    codes = [settings.benchmark_code, *[stock.code for stock in selection.selected]]
    quotes = fetch_realtime_quotes(codes)
    by_code = {quote.ts_code.upper(): quote for quote in quotes}
    return selection.model_copy(update={
        "source": "tushare",
        "market_quote": by_code.get(settings.benchmark_code.upper()),
        "selected_quotes": [by_code[stock.code.upper()] for stock in selection.selected if stock.code.upper() in by_code],
    })
