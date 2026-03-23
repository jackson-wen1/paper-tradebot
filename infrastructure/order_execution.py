"""
Order Execution — Submit, track, and manage orders via Alpaca Trading API.

Handles the full order lifecycle: submission, status tracking, cancellation,
and bracket orders (entry + stop-loss + take-profit).
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    StopOrderRequest,
    StopLimitOrderRequest,
    TrailingStopOrderRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus, OrderType

from config import ALPACA_API_KEY, ALPACA_API_SECRET, ALPACA_BASE_URL

logger = logging.getLogger(__name__)


def _get_client() -> TradingClient:
    return TradingClient(
        ALPACA_API_KEY, ALPACA_API_SECRET,
        paper=("paper" in ALPACA_BASE_URL),
    )


def _log_order(action: str, symbol: str, side: str, qty: float, **kwargs: object) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.info("[%s] %s: %s %s x%.4f %s", ts, action, side, symbol, qty, extra)


def submit_market_order(
    symbol: str,
    side: str,
    qty: float,
    time_in_force: str = "day",
) -> dict:
    """
    Submit a market order.

    Args:
        symbol: Ticker symbol
        side: "buy" or "sell"
        qty: Number of shares (supports fractional)
        time_in_force: "day", "gtc", "ioc", "fok"
    """
    client = _get_client()
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
    tif = getattr(TimeInForce, time_in_force.upper(), TimeInForce.DAY)

    request = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=order_side,
        time_in_force=tif,
    )

    _log_order("SUBMIT_MARKET", symbol, side, qty)
    order = client.submit_order(request)
    _log_order("SUBMITTED", symbol, side, qty, order_id=order.id, status=order.status)

    return _order_to_dict(order)


def submit_limit_order(
    symbol: str,
    side: str,
    qty: float,
    limit_price: float,
    time_in_force: str = "day",
) -> dict:
    """Submit a limit order."""
    client = _get_client()
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
    tif = getattr(TimeInForce, time_in_force.upper(), TimeInForce.DAY)

    request = LimitOrderRequest(
        symbol=symbol,
        qty=qty,
        side=order_side,
        time_in_force=tif,
        limit_price=limit_price,
    )

    _log_order("SUBMIT_LIMIT", symbol, side, qty, limit_price=limit_price)
    order = client.submit_order(request)
    _log_order("SUBMITTED", symbol, side, qty, order_id=order.id, status=order.status)

    return _order_to_dict(order)


def submit_stop_order(
    symbol: str,
    side: str,
    qty: float,
    stop_price: float,
    time_in_force: str = "day",
) -> dict:
    """Submit a stop order."""
    client = _get_client()
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
    tif = getattr(TimeInForce, time_in_force.upper(), TimeInForce.DAY)

    request = StopOrderRequest(
        symbol=symbol,
        qty=qty,
        side=order_side,
        time_in_force=tif,
        stop_price=stop_price,
    )

    _log_order("SUBMIT_STOP", symbol, side, qty, stop_price=stop_price)
    order = client.submit_order(request)
    _log_order("SUBMITTED", symbol, side, qty, order_id=order.id, status=order.status)

    return _order_to_dict(order)


def submit_stop_limit_order(
    symbol: str,
    side: str,
    qty: float,
    stop_price: float,
    limit_price: float,
    time_in_force: str = "day",
) -> dict:
    """Submit a stop-limit order."""
    client = _get_client()
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
    tif = getattr(TimeInForce, time_in_force.upper(), TimeInForce.DAY)

    request = StopLimitOrderRequest(
        symbol=symbol,
        qty=qty,
        side=order_side,
        time_in_force=tif,
        stop_price=stop_price,
        limit_price=limit_price,
    )

    _log_order("SUBMIT_STOP_LIMIT", symbol, side, qty, stop_price=stop_price, limit_price=limit_price)
    order = client.submit_order(request)
    _log_order("SUBMITTED", symbol, side, qty, order_id=order.id, status=order.status)

    return _order_to_dict(order)


def submit_trailing_stop_order(
    symbol: str,
    side: str,
    qty: float,
    trail_percent: float,
    time_in_force: str = "day",
) -> dict:
    """Submit a trailing stop order."""
    client = _get_client()
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
    tif = getattr(TimeInForce, time_in_force.upper(), TimeInForce.DAY)

    request = TrailingStopOrderRequest(
        symbol=symbol,
        qty=qty,
        side=order_side,
        time_in_force=tif,
        trail_percent=trail_percent,
    )

    _log_order("SUBMIT_TRAILING_STOP", symbol, side, qty, trail_percent=trail_percent)
    order = client.submit_order(request)
    _log_order("SUBMITTED", symbol, side, qty, order_id=order.id, status=order.status)

    return _order_to_dict(order)


def submit_bracket_order(
    symbol: str,
    side: str,
    qty: float,
    limit_price: Optional[float] = None,
    stop_loss_price: float = 0.0,
    take_profit_price: float = 0.0,
    time_in_force: str = "day",
) -> dict:
    """
    Submit a bracket order (entry + stop-loss + take-profit).

    Uses Alpaca's OCO (one-cancels-other) bracket order type.
    """
    client = _get_client()
    order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
    tif = getattr(TimeInForce, time_in_force.upper(), TimeInForce.DAY)

    if limit_price:
        request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=tif,
            limit_price=limit_price,
            order_class="bracket",
            stop_loss={"stop_price": stop_loss_price},
            take_profit={"limit_price": take_profit_price},
        )
    else:
        request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=tif,
            order_class="bracket",
            stop_loss={"stop_price": stop_loss_price},
            take_profit={"limit_price": take_profit_price},
        )

    _log_order("SUBMIT_BRACKET", symbol, side, qty,
               stop_loss=stop_loss_price, take_profit=take_profit_price)
    order = client.submit_order(request)
    _log_order("SUBMITTED", symbol, side, qty, order_id=order.id, status=order.status)

    return _order_to_dict(order)


def get_order(order_id: str) -> dict:
    """Get the current state of an order."""
    client = _get_client()
    order = client.get_order_by_id(order_id)
    return _order_to_dict(order)


def get_open_orders() -> list[dict]:
    """Get all open orders."""
    client = _get_client()
    orders = client.get_orders()
    return [_order_to_dict(o) for o in orders]


def cancel_order(order_id: str) -> None:
    """Cancel a specific order."""
    client = _get_client()
    client.cancel_order_by_id(order_id)
    _log_order("CANCELED", "N/A", "N/A", 0, order_id=order_id)


def cancel_all_orders() -> None:
    """Cancel all open orders."""
    client = _get_client()
    client.cancel_orders()
    logger.info("All open orders canceled")


def _order_to_dict(order: object) -> dict:
    """Convert an Alpaca order object to a plain dict."""
    return {
        "id": str(order.id),
        "symbol": order.symbol,
        "side": str(order.side),
        "qty": float(order.qty) if order.qty else 0,
        "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
        "type": str(order.type),
        "status": str(order.status),
        "limit_price": float(order.limit_price) if order.limit_price else None,
        "stop_price": float(order.stop_price) if order.stop_price else None,
        "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        "submitted_at": str(order.submitted_at) if order.submitted_at else None,
        "filled_at": str(order.filled_at) if order.filled_at else None,
        "created_at": str(order.created_at) if order.created_at else None,
    }
