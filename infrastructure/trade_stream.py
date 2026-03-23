"""
Trade Stream — Real-time trade/order update stream via Alpaca.

Subscribes to trade updates (fills, cancellations, rejections) and triggers callbacks.
"""

import asyncio
import logging
from typing import Callable, Optional

from alpaca.trading.stream import TradingStream

from config import ALPACA_API_KEY, ALPACA_API_SECRET, ALPACA_BASE_URL

logger = logging.getLogger(__name__)


class TradeUpdateStream:
    """Manages real-time trade update WebSocket stream."""

    def __init__(self) -> None:
        self._stream: Optional[TradingStream] = None
        self._handlers: list[Callable] = []
        self._running = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

    def _create_stream(self) -> TradingStream:
        return TradingStream(
            ALPACA_API_KEY, ALPACA_API_SECRET,
            paper=("paper" in ALPACA_BASE_URL),
        )

    def on_trade_update(self, handler: Callable) -> None:
        """Register a handler for trade update events."""
        self._handlers.append(handler)

    async def _dispatch(self, data: object) -> None:
        """Dispatch trade update to all registered handlers."""
        event = str(data.event) if hasattr(data, "event") else "unknown"
        order = data.order if hasattr(data, "order") else data

        logger.info(
            "Trade update: event=%s symbol=%s status=%s",
            event,
            getattr(order, "symbol", "N/A"),
            getattr(order, "status", "N/A"),
        )

        for handler in self._handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(data)
                else:
                    handler(data)
            except Exception as e:
                logger.error("Trade update handler error: %s", e)

    async def run(self) -> None:
        """Start the trade update stream with auto-reconnect."""
        self._running = True
        while self._running:
            try:
                self._stream = self._create_stream()
                self._stream.subscribe_trade_updates(self._dispatch)
                logger.info("Starting trade update stream...")
                self._stream.run()
            except Exception as e:
                if not self._running:
                    break
                logger.error(
                    "Trade stream disconnected: %s. Reconnecting in %.0fs...",
                    e, self._reconnect_delay,
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._max_reconnect_delay
                )
            else:
                self._reconnect_delay = 1.0

    async def stop(self) -> None:
        """Stop the trade update stream."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
            except Exception:
                pass
            self._stream = None
        logger.info("Trade update stream stopped")
