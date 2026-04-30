from fastapi.testclient import TestClient

from app.main import app


def test_health():
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_data_info_endpoint():
    client = TestClient(app)
    res = client.get("/api/data/info")
    assert res.status_code == 200
    body = res.json()
    assert body["daily_available"] is True
    assert body["stock_15min_count"] > 0


def test_backtest_progress_unknown_job():
    client = TestClient(app)
    res = client.get("/api/backtest/progress/not-a-job")
    assert res.status_code == 404


def test_optimization_progress_unknown_job():
    client = TestClient(app)
    res = client.get("/api/optimize/progress/not-a-job")
    assert res.status_code == 404


def test_minute_detail_stock_uses_one_minute_data():
    client = TestClient(app)
    res = client.get("/api/minute/detail", params={
        "asset_type": "stock",
        "query": "平安银行",
        "trade_date": "2026-04-24",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == "000001.SZ"
    assert len(body["bars"]) > 100


def test_minute_detail_index_defaults_to_hs300_one_minute_data():
    client = TestClient(app)
    res = client.get("/api/minute/detail", params={
        "asset_type": "index",
        "query": "大盘",
        "trade_date": "2026-04-24",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == "000300.SH"
    assert len(body["bars"]) > 100
    assert body["bars"][0]["vwap"] > 1000


def test_stock_window_endpoint_returns_centered_trading_days():
    client = TestClient(app)
    res = client.get("/api/stocks/000001.SZ/window", params={
        "center_date": "2026-04-24",
        "radius": 2,
        "freq": "1min",
        "name": "平安银行",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["code"] == "000001.SZ"
    assert body["name"] == "平安银行"
    assert body["center_date"] == "2026-04-24"
    assert len(body["days"]) == 3
    assert body["days"][-1]["trade_date"] == "2026-04-24"
    assert len(body["days"][-1]["bars"]) > 100
