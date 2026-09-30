import asyncio

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from .broker import DemoBroker, KiteBroker, NotLoggedIn
from .config import settings
from .portfolio import build_portfolio
from .risk import evaluate

app = FastAPI(title="Option Seller")
app.add_middleware(CORSMiddleware, allow_origins=[settings.frontend_url], allow_methods=["*"], allow_headers=["*"])

broker = DemoBroker() if settings.demo_mode else KiteBroker()


def snapshot() -> dict:
    portfolio = build_portfolio(broker)
    portfolio["alerts"] = evaluate(portfolio)
    return portfolio


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "demo_mode": settings.demo_mode, "logged_in": broker.logged_in}


@app.get("/auth/login")
def login() -> RedirectResponse:
    if settings.demo_mode:
        return RedirectResponse(settings.frontend_url)
    return RedirectResponse(broker.login_url())


@app.get("/auth/callback")
def callback(request_token: str) -> RedirectResponse:
    # Set this URL as the redirect URL of your Kite Connect app.
    broker.complete_login(request_token)
    return RedirectResponse(settings.frontend_url)


@app.get("/api/portfolio")
def portfolio() -> dict:
    try:
        return snapshot()
    except NotLoggedIn:
        raise HTTPException(401, "Log in to Kite first")


@app.websocket("/ws/portfolio")
async def portfolio_stream(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            try:
                await ws.send_json({"type": "portfolio", "data": await asyncio.to_thread(snapshot)})
            except NotLoggedIn:
                await ws.send_json({"type": "error", "error": "not_logged_in"})
            except Exception as exc:  # keep streaming through transient Kite errors
                await ws.send_json({"type": "error", "error": str(exc)})
            await asyncio.sleep(settings.refresh_seconds)
    except WebSocketDisconnect:
        pass
