"""
WebSocket Streams — Real-time market data and trade update streams via Alpaca.

Manages connection lifecycle, reconnection logic, and async message handling.
"""

import asyncio
import logging
from typing import Callable, Optional

from alpaca.data.live import StockDataStream

from config import ALPACA_API_KEY, ALPACA_API_SECRET

logger = logging.getLogger(__name__)


class MarketDataStream:
    """Manages real-time market data WebSocket streams."""

    def __init__(self) -> None:
        self._stream: Optional[StockDataStream] = None
        self._subscribed_bars: set[str] = set()
        self._subscribed_trades: set[str] = set()
        self._subscribed_quotes: set[str] = set()
        self._running = False
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0

    def _create_stream(self) -> StockDataStream:
        return StockDataStream(ALPACA_API_KEY, ALPACA_API_SECRET)

    async def subscribe_bars(
        self,
        symbols: list[str],
        handler: Callable,
    ) -> None:
        """Subscribe to real-time bar updates for symbols."""
        if self._stream is None:
            self._stream = self._create_stream()

        self._stream.subscribe_bars(handler, *symbols)
        self._subscribed_bars.update(symbols)
        logger.info("Subscribed to bars: %s", symbols)

    async def subscribe_trades(
        self,
        symbols: list[str],
        handler: Callable,
    ) -> None:
        """Subscribe to real-time trade updates for symbols."""
        if self._stream is None:
            self._stream = self._create_stream()

        self._stream.subscribe_trades(handler, *symbols)
        self._subscribed_trades.update(symbols)
        logger.info("Subscribed to trades: %s", symbols)

    async def subscribe_quotes(
        self,
        symbols: list[str],
        handler: Callable,
    ) -> None:
        """Subscribe to real-time quote updates."""
        if self._stream is None:
            self._stream = self._create_stream()

        self._stream.subscribe_quotes(handler, *symbols)
        self._subscribed_quotes.update(symbols)
        logger.info("Subscribed to quotes: %s", symbols)

    async def run(self) -> None:
        """Start the stream with auto-reconnect logic."""
        self._running = True
        while self._running:
            try:
                if self._stream is None:
                    self._stream = self._create_stream()
                logger.info("Starting market data stream...")
                self._stream.run()
            except Exception as e:
                if not self._running:
                    break
                logger.error("Stream disconnected: %s. Reconnecting in %.0fs...",
                             e, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._max_reconnect_delay
                )
                self._stream = None  # Force recreation
            else:
                self._reconnect_delay = 1.0  # Reset on successful connection

    async def stop(self) -> None:
        """Stop the stream."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
            except Exception:
                pass
            self._stream = None
        logger.info("Market data stream stopped")
