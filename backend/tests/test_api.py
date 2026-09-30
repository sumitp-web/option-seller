import os

os.environ["DEMO_MODE"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)


def test_portfolio_endpoint():
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    body = r.json()
    assert {"totals", "underlyings", "alerts"} <= body.keys()


def test_websocket_streams_portfolio():
    with client.websocket_connect("/ws/portfolio") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "portfolio"
