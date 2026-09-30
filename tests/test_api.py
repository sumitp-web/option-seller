from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app
from tests.fakes import FakeBroker


def test_trade_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "state_file", str(tmp_path / "s.json"))
    b = FakeBroker()
    client = TestClient(create_app(b))
    exp = client.get("/api/expiries", params={"underlying": "NIFTY"}).json()
    assert exp["lot_size"] == 75
    risk = {"underlying": "NIFTY", "expiry": "2026-10-06", "lots": 1, "leg_sl_points": 30,
            "max_loss": 5000, "square_off": "23:59"}
    assert client.post("/api/sell", json={**risk, "type": "CE", "strike": 26000}).status_code == 200
    r = client.post("/api/sell", json={**risk, "type": "PE", "strike": 25000})
    assert len(r.json()["legs"]) == 2
    bad = client.post("/api/sell", json={**risk, "type": "PE", "strike": 25010})
    assert bad.status_code == 400 and "not listed" in bad.json()["detail"]
    assert client.post("/api/buy", json={"type": "CE"}).json()["status"] == "running"
    assert client.post("/api/close-all").json()["status"] == "closed"
    assert client.get("/api/status").json()["user"] == "AB1234"
    assert client.get("/").status_code == 200
def test_order_book(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "state_file", str(tmp_path / "s.json"))
    client = TestClient(create_app(FakeBroker()))
    assert client.get("/api/orders").json() == []
    assert client.get("/api/trades").json() == []
