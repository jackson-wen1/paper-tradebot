"""
Account Monitor — Track account health, P&L, positions, and equity.

Provides real-time portfolio visibility and exposes data for the dashboard API.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from alpaca.trading.client import TradingClient

from config import ALPACA_API_KEY, ALPACA_API_SECRET, ALPACA_BASE_URL

logger = logging.getLogger(__name__)


def _get_client() -> TradingClient:
    return TradingClient(
        ALPACA_API_KEY, ALPACA_API_SECRET,
        paper=("paper" in ALPACA_BASE_URL),
    )


def get_account() -> dict:
    """Fetch full account details."""
    client = _get_client()
    account = client.get_account()
    return {
        "id": str(account.id),
        "status": str(account.status),
        "equity": float(account.equity),
        "cash": float(account.cash),
        "buying_power": float(account.buying_power),
        "portfolio_value": float(account.portfolio_value) if account.portfolio_value else float(account.equity),
        "last_equity": float(account.last_equity),
        "long_market_value": float(account.long_market_value),
        "short_market_value": float(account.short_market_value),
        "initial_margin": float(account.initial_margin) if account.initial_margin else 0,
        "maintenance_margin": float(account.maintenance_margin) if account.maintenance_margin else 0,
        "daytrade_count": int(account.daytrade_count),
        "pattern_day_trader": bool(account.pattern_day_trader),
        "trading_blocked": bool(account.trading_blocked),
        "account_blocked": bool(account.account_blocked),
        "currency": str(account.currency),
    }


def get_positions() -> list[dict]:
    """Fetch all open positions."""
    client = _get_client()
    positions = client.get_all_positions()
    return [
        {
            "symbol": p.symbol,
            "qty": float(p.qty),
            "side": str(p.side),
            "market_value": float(p.market_value),
            "cost_basis": float(p.cost_basis),
            "avg_entry_price": float(p.avg_entry_price),
            "current_price": float(p.current_price),
            "unrealized_pl": float(p.unrealized_pl),
            "unrealized_plpc": float(p.unrealized_plpc),
            "change_today": float(p.change_today),
        }
        for p in positions
    ]


def get_position(symbol: str) -> Optional[dict]:
    """Fetch a specific position by symbol."""
    client = _get_client()
    try:
        p = client.get_open_position(symbol)
        return {
            "symbol": p.symbol,
            "qty": float(p.qty),
            "side": str(p.side),
            "market_value": float(p.market_value),
            "cost_basis": float(p.cost_basis),
            "avg_entry_price": float(p.avg_entry_price),
            "current_price": float(p.current_price),
            "unrealized_pl": float(p.unrealized_pl),
            "unrealized_plpc": float(p.unrealized_plpc),
            "change_today": float(p.change_today),
        }
    except Exception:
        return None


def close_position(symbol: str) -> dict:
    """Close a specific position."""
    client = _get_client()
    order = client.close_position(symbol)
    logger.info("Closed position for %s", symbol)
    return {
        "id": str(order.id),
        "symbol": order.symbol,
        "status": str(order.status),
    }


def close_all_positions() -> list[dict]:
    """Close all open positions."""
    client = _get_client()
    results = client.close_all_positions(cancel_orders=True)
    logger.info("Closed all positions")
    return [{"symbol": str(r), "status": "closing"} for r in results]


def get_portfolio_history(
    period: str = "1M",
    timeframe: str = "1D",
) -> dict:
    """
    Fetch portfolio history for equity curve.

    Args:
        period: "1D", "1W", "1M", "3M", "1A", "all"
        timeframe: "1Min", "5Min", "15Min", "1H", "1D"
    """
    client = _get_client()
    history = client.get_portfolio_history(
        period=period,
        timeframe=timeframe,
    )
    return {
        "timestamps": [
            datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            for ts in history.timestamp
        ] if history.timestamp else [],
        "equity": [float(e) for e in history.equity] if history.equity else [],
        "profit_loss": [float(p) for p in history.profit_loss] if history.profit_loss else [],
        "profit_loss_pct": [
            float(p) for p in history.profit_loss_pct
        ] if history.profit_loss_pct else [],
        "base_value": float(history.base_value) if history.base_value else 0,
    }


def get_activities(activity_type: str = "FILL", limit: int = 50) -> list[dict]:
    """Fetch recent account activities (fills, dividends, etc.)."""
    client = _get_client()
    activities = client.get_activities(activity_types=activity_type)
    result = []
    for a in activities[:limit]:
        entry = {
            "id": str(a.id),
            "activity_type": str(a.activity_type),
        }
        # Trade activities have symbol, side, qty, price
        if hasattr(a, "symbol"):
            entry.update({
                "symbol": a.symbol,
                "side": str(a.side) if a.side else None,
                "qty": float(a.qty) if a.qty else 0,
                "price": float(a.price) if a.price else 0,
                "transaction_time": str(a.transaction_time) if a.transaction_time else None,
            })
        result.append(entry)
    return result


def get_daily_pnl() -> dict:
    """Calculate today's P&L from account data."""
    account = get_account()
    daily_pnl = account["equity"] - account["last_equity"]
    daily_pnl_pct = (daily_pnl / account["last_equity"] * 100) if account["last_equity"] else 0
    return {
        "equity": account["equity"],
        "last_equity": account["last_equity"],
        "daily_pnl": daily_pnl,
        "daily_pnl_pct": daily_pnl_pct,
    }


def is_market_open() -> dict:
    """Check if the market is currently open."""
    client = _get_client()
    clock = client.get_clock()
    return {
        "is_open": clock.is_open,
        "next_open": str(clock.next_open),
        "next_close": str(clock.next_close),
        "timestamp": str(clock.timestamp),
    }
