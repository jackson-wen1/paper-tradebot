"""
API Server — FastAPI backend for the Tradebot dashboard.

Exposes REST endpoints for account data, positions, portfolio history,
and bot control. Deployable for free on Render (free tier) or any Docker host.
Also provides a /api/cron/tick endpoint for Vercel Cron to trigger trading.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from infrastructure.account_monitor import (
    get_account,
    get_positions,
    get_portfolio_history,
    get_activities,
    get_daily_pnl,
    is_market_open,
)
from infrastructure.data_pipeline import get_historical_bars
from infrastructure.order_execution import get_open_orders
from infrastructure.risk_management import RiskManager

logger = logging.getLogger(__name__)

# Bot state (shared with the trading loop if run in same process)
bot_state = {
    "strategy": os.getenv("BOT_STRATEGY", "momentum"),
    "symbols": os.getenv("BOT_SYMBOLS", "SPY,AAPL,MSFT,GOOGL,AMZN,NVDA").split(","),
    "running": False,
    "started_at": None,
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("API server starting")
    yield
    logger.info("API server shutting down")


app = FastAPI(
    title="Tradebot Dashboard API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow the Vercel frontend
allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/account")
async def api_account() -> dict:
    """Get account summary (equity, cash, buying power)."""
    return get_account()


@app.get("/api/positions")
async def api_positions() -> list[dict]:
    """Get all open positions with P&L."""
    return get_positions()


@app.get("/api/pnl")
async def api_pnl() -> dict:
    """Get today's P&L."""
    return get_daily_pnl()


@app.get("/api/history")
async def api_history(period: str = "1M", timeframe: str = "1D") -> dict:
    """Get portfolio equity history for charts."""
    return get_portfolio_history(period=period, timeframe=timeframe)


@app.get("/api/orders")
async def api_orders() -> list[dict]:
    """Get open orders."""
    return get_open_orders()


@app.get("/api/activities")
async def api_activities(limit: int = 50) -> list[dict]:
    """Get recent trade fills."""
    return get_activities(limit=limit)


@app.get("/api/market")
async def api_market() -> dict:
    """Check if market is open."""
    return is_market_open()


@app.get("/api/bot")
async def api_bot_status() -> dict:
    """Get bot status (strategy, symbols, running state)."""
    return bot_state


class BotConfigUpdate(BaseModel):
    strategy: str | None = None
    symbols: list[str] | None = None


@app.post("/api/bot/config")
async def api_bot_config(update: BotConfigUpdate) -> dict:
    """Update bot strategy and/or symbols at runtime."""
    if update.strategy is not None:
        if update.strategy not in STRATEGY_MAP:
            return {"status": "error", "reason": f"unknown strategy: {update.strategy}"}
        bot_state["strategy"] = update.strategy

    if update.symbols is not None:
        cleaned = [s.strip().upper() for s in update.symbols if s.strip()]
        if not cleaned:
            return {"status": "error", "reason": "symbols list cannot be empty"}
        bot_state["symbols"] = cleaned

    return {"status": "ok", **bot_state}


# ---------------------------------------------------------------------------
# Cron Tick — Vercel Cron (or any scheduler) calls this to execute one
# trading cycle. This is how the bot runs 24/7 without a persistent server.
# ---------------------------------------------------------------------------
_risk_manager = RiskManager()

STRATEGY_MAP = {
    "momentum": "strategies.momentum",
    "mean_reversion": "strategies.mean_reversion",
    "trend_following": "strategies.trend_following",
    "options_volatility": "strategies.options_volatility",
}


@app.post("/api/cron/tick")
async def cron_tick(authorization: str | None = Header(default=None)) -> dict:
    """
    Execute one cycle of the trading bot.

    Called by an external cron service every minute during market hours.
    Stateless: reads account, generates signals, executes orders.
    """
    cron_secret = os.getenv("CRON_SECRET")
    if cron_secret:
        if authorization != f"Bearer {cron_secret}":
            raise HTTPException(status_code=401, detail="Unauthorized")
    import importlib
    from infrastructure.order_execution import submit_market_order

    # Check market hours
    clock = is_market_open()
    if not clock["is_open"]:
        return {"status": "skipped", "reason": "market_closed"}

    # Load strategy
    strategy_name = bot_state["strategy"]
    if strategy_name not in STRATEGY_MAP:
        return {"status": "error", "reason": f"unknown strategy: {strategy_name}"}

    strategy_module = importlib.import_module(STRATEGY_MAP[strategy_name])
    symbols = bot_state["symbols"]

    # Get account state
    account = get_account()
    equity = account["equity"]
    buying_power = account["buying_power"]

    # Initialize daily equity if not set
    if _risk_manager.state.daily_start_equity == 0:
        _risk_manager.update_daily_equity(equity)

    # Check daily loss
    if not _risk_manager.check_daily_loss_limit(equity):
        return {"status": "halted", "reason": "daily_loss_limit"}

    # Check risk triggers on existing positions
    actions_taken = []
    positions = get_positions()
    for pos in positions:
        action = _risk_manager.update_price(pos["symbol"], pos["current_price"])
        if action in ("stop_loss", "take_profit", "trailing_stop"):
            qty = abs(pos["qty"])
            side = "sell" if pos["qty"] > 0 else "buy"
            try:
                submit_market_order(pos["symbol"], side, qty)
                _risk_manager.close_position(pos["symbol"])
                actions_taken.append({"symbol": pos["symbol"], "action": action})
            except Exception as e:
                actions_taken.append({"symbol": pos["symbol"], "action": action, "error": str(e)})

    # Run strategy on each symbol
    timeframe = "1Min"
    orders_placed = []
    for symbol in symbols:
        try:
            data = get_historical_bars(symbol, timeframe, limit=300)
            if data.empty or len(data) < 35:
                continue

            result = strategy_module.execute(
                symbol=symbol,
                risk_manager=_risk_manager,
                account_equity=equity,
                buying_power=buying_power,
                data=data,
            )
            if result:
                orders_placed.append(result)
        except Exception as e:
            logger.error("Cron tick error for %s: %s", symbol, e)

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strategy": strategy_name,
        "timeframe": timeframe,
        "symbols_checked": len(symbols),
        "orders_placed": len(orders_placed),
        "risk_actions": actions_taken,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
