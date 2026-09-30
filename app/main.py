import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from .broker import UNDERLYINGS, KiteBroker, NotLoggedIn
from .config import settings
from .engine import Engine, TradeParams

log = logging.getLogger("oneclick")
STATIC = Path(__file__).parent / "static"


class Watch(BaseModel):
    underlying: str
    expiry: str


class Risk(BaseModel):
    underlying: str
    expiry: str
    lots: int
    leg_sl_points: float
    max_loss: float
    tsl_start: float = 0
    tsl_lock: float = 0
    tsl_step: float = 0
    square_off: str = "15:15"
    product: str = "NRML"


class SellIn(Risk):
    type: str
    strike: float


class StartIn(Risk):
    ce_strike: float
    pe_strike: float


class BuyIn(BaseModel):
    type: str


def create_app(broker=None) -> FastAPI:
    broker = broker or KiteBroker()
    engine = Engine(
        broker,
        freeze_qty={"NIFTY": settings.freeze_qty_nifty, "SENSEX": settings.freeze_qty_sensex},
        state_file=settings.state_file,
    )
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(loop())
        yield
        task.cancel()

    app = FastAPI(title="One-click Option Seller", lifespan=lifespan)
    app.state.engine = engine
    watch = {"underlying": "NIFTY", "expiry": None}
    clients: set[WebSocket] = set()

    def build_chain(quotes: dict) -> dict | None:
        u, exp = watch["underlying"], watch["expiry"]
        if not exp:
            return None
        spot_q = quotes.get(UNDERLYINGS[u][1])
        if not spot_q:
            return None
        spot = spot_q["ltp"]
        contracts = engine.chain_contracts(u, exp)
        strikes = sorted({s for s, _ in contracts})
        atm = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
        rows = []
        for s in strikes[max(0, atm - settings.chain_width): atm + settings.chain_width + 1]:
            row = {"strike": s}
            for typ in ("CE", "PE"):
                c = contracts.get((s, typ))
                q = quotes.get(f"{c['exchange']}:{c['tradingsymbol']}") if c else None
                row[typ.lower()] = q and {
                    "ltp": q["ltp"], "oi": q["oi"],
                    "change_pct": round((q["ltp"] - q["close"]) / q["close"] * 100, 1) if q["close"] else 0,
                }
            rows.append(row)
        close = spot_q["close"]
        return {"underlying": u, "expiry": exp, "spot": spot,
                "spot_change_pct": (spot - close) / close * 100 if close else 0, "rows": rows}

    def chain_keys() -> list[str]:
        u, exp = watch["underlying"], watch["expiry"]
        keys = [UNDERLYINGS[u][1]]
        if exp:
            keys += [f"{c['exchange']}:{c['tradingsymbol']}" for c in engine.chain_contracts(u, exp).values()]
        return keys

    def tick() -> dict:
        if not broker.logged_in:
            return {"logged_in": False}
        keys = list(dict.fromkeys(engine.open_keys() + chain_keys()))
        # Kite allows up to 500 instruments per quote call.
        quotes = broker.quote(keys[:500])
        engine.on_prices({k: q["ltp"] for k, q in quotes.items()})
        return {"logged_in": True, "chain": build_chain(quotes), "trade": engine.snapshot()}

    async def loop() -> None:
        while True:
            try:
                msg = await asyncio.to_thread(tick)
            except NotLoggedIn:
                msg = {"logged_in": False}
            except Exception as exc:  # keep watching through transient Kite errors
                log.exception("tick failed")
                msg = {"logged_in": True, "error": str(exc), "trade": engine.snapshot()}
            for ws in list(clients):
                try:
                    await ws.send_json(msg)
                except Exception:
                    clients.discard(ws)
            await asyncio.sleep(settings.tick_seconds)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/auth/login")
    def login() -> RedirectResponse:
        return RedirectResponse(broker.login_url())

    @app.get("/auth/callback")
    def callback(request_token: str) -> RedirectResponse:
        # Set http://localhost:8000/auth/callback as the redirect URL of your Kite Connect app.
        broker.complete_login(request_token)
        return RedirectResponse("/")

    def guarded(fn, *args):
        try:
            return fn(*args)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except NotLoggedIn:
            raise HTTPException(401, "Log in with Kite first.")

    @app.get("/api/status")
    def status() -> dict:
        if not broker.logged_in:
            return {"logged_in": False}
        try:
            user = broker.profile().get("user_id")
        except Exception:
            user = None
        return {"logged_in": True, "user": user}

    @app.get("/api/expiries")
    def expiries(underlying: str) -> dict:
        if underlying not in UNDERLYINGS:
            raise HTTPException(400, "Only NIFTY and SENSEX are supported.")
        return guarded(lambda: {"expiries": engine.expiries(underlying), "lot_size": engine.lot_size(underlying)})

    @app.post("/api/watch")
    def set_watch(w: Watch) -> dict:
        watch.update(underlying=w.underlying, expiry=w.expiry)
        return {"ok": True}

    @app.post("/api/sell")
    def sell(body: SellIn) -> dict:
        risk = TradeParams(**body.model_dump(exclude={"type", "strike"}))
        guarded(engine.sell, risk, body.type, body.strike)
        return engine.snapshot()

    @app.post("/api/start")
    def start(body: StartIn) -> dict:
        risk = TradeParams(**body.model_dump(exclude={"ce_strike", "pe_strike"}))
        guarded(engine.start, risk, body.ce_strike, body.pe_strike)
        return engine.snapshot()

    @app.post("/api/buy")
    def buy(body: BuyIn) -> dict:
        guarded(engine.buy, body.type)
        return engine.snapshot()

    @app.post("/api/close-all")
    def close_all() -> dict:
        engine.exit_all("Close all")
        return engine.snapshot() or {}

    @app.post("/api/cancel-all")
    def cancel_all() -> dict:
        return {"cancelled": guarded(broker.cancel_open_orders)}

    @app.post("/api/exit-leg/{leg_id}")
    def exit_leg(leg_id: str) -> dict:
        guarded(engine.exit_leg, leg_id)
        return engine.snapshot()

    @app.get("/api/orders")
    def orders() -> list[dict]:
        return guarded(broker.orders)

    @app.get("/api/trades")
    def trades() -> list[dict]:
        return guarded(broker.trades)

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        clients.add(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            clients.discard(ws)

    return app


app = create_app()
