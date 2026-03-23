"""
Data Pipeline — Fetch, clean, and normalize market data from Alpaca.

Handles historical OHLCV bars, real-time WebSocket streams, rate limiting,
and local caching. Returns standardized pandas DataFrames.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestBarRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from config import ALPACA_API_KEY, ALPACA_API_SECRET

logger = logging.getLogger(__name__)

# Rate limiting: Alpaca free tier = 200 req/min
_REQUEST_TIMES: list[float] = []
_RATE_LIMIT = 200
_RATE_WINDOW = 60  # seconds

CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

TIMEFRAME_MAP = {
    "1Min": TimeFrame(1, TimeFrameUnit.Minute),
    "5Min": TimeFrame(5, TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
    "1Day": TimeFrame(1, TimeFrameUnit.Day),
}


def _get_client() -> StockHistoricalDataClient:
    return StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_API_SECRET)


def _enforce_rate_limit() -> None:
    """Block until we are under the rate limit."""
    now = time.monotonic()
    # Purge old timestamps
    while _REQUEST_TIMES and _REQUEST_TIMES[0] < now - _RATE_WINDOW:
        _REQUEST_TIMES.pop(0)
    if len(_REQUEST_TIMES) >= _RATE_LIMIT:
        sleep_for = _RATE_WINDOW - (now - _REQUEST_TIMES[0]) + 0.1
        logger.warning("Rate limit approaching, sleeping %.1fs", sleep_for)
        time.sleep(sleep_for)
    _REQUEST_TIMES.append(time.monotonic())


def _cache_key(symbol: str, timeframe: str, start: str, end: str) -> Path:
    safe = f"{symbol}_{timeframe}_{start}_{end}".replace(":", "-").replace(" ", "_")
    return CACHE_DIR / f"{safe}.parquet"


def _clean_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize column names and validate OHLC consistency."""
    rename_map = {
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "trade_count": "trade_count",
        "vwap": "vwap",
    }
    df = df.rename(columns=rename_map)

    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    df.index.name = "timestamp"

    # Validate OHLC consistency
    invalid = (df["high"] < df["low"]) | (df["open"] > df["high"]) | (df["open"] < df["low"])
    if invalid.any():
        count = invalid.sum()
        logger.warning("Found %d bars with inconsistent OHLC, flagging", count)
        df["ohlc_valid"] = ~invalid
    else:
        df["ohlc_valid"] = True

    # Remove duplicates
    df = df[~df.index.duplicated(keep="first")]

    # Sort by timestamp
    df = df.sort_index()

    # Forward-fill missing data (gaps from halts/holidays)
    df = df.ffill()

    return df


def get_historical_bars(
    symbol: str,
    timeframe: str = "1Day",
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """
    Fetch historical OHLCV bars for a symbol.

    Args:
        symbol: Ticker symbol (e.g. "AAPL")
        timeframe: One of "1Min", "5Min", "15Min", "1Hour", "1Day"
        start: Start date as ISO string (e.g. "2024-01-01")
        end: End date as ISO string
        limit: Maximum number of bars

    Returns:
        DataFrame with columns: open, high, low, close, volume
    """
    if timeframe not in TIMEFRAME_MAP:
        raise ValueError(f"Invalid timeframe '{timeframe}'. Use: {list(TIMEFRAME_MAP.keys())}")

    if start is None:
        if timeframe == "1Day":
            start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        else:
            # For intraday, look back only a few days to get recent bars
            start = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")

    # Only cache daily bars — intraday data changes every minute so cache is useless
    INTRADAY = timeframe != "1Day"

    # Check cache (daily only)
    cache_path = _cache_key(symbol, timeframe, start, end)
    if not INTRADAY and cache_path.exists():
        logger.info("Loading cached bars for %s", symbol)
        return pd.read_parquet(cache_path)

    _enforce_rate_limit()

    client = _get_client()
    request = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TIMEFRAME_MAP[timeframe],
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        limit=limit,
    )

    bars = client.get_stock_bars(request)
    df = bars.df

    if df.empty:
        logger.warning("No bars returned for %s (%s to %s)", symbol, start, end)
        return df

    # If multi-index (symbol, timestamp), drop symbol level
    if isinstance(df.index, pd.MultiIndex):
        df = df.droplevel("symbol")

    df = _clean_bars(df)

    # Only cache daily bars — intraday is fetched fresh every tick
    if not INTRADAY:
        df.to_parquet(cache_path)
    logger.info("Fetched %d bars for %s (%s)", len(df), symbol, timeframe)

    return df


def get_latest_bar(symbol: str) -> dict:
    """Fetch the latest bar for a symbol."""
    _enforce_rate_limit()
    client = _get_client()
    request = StockLatestBarRequest(symbol_or_symbols=symbol)
    bar = client.get_stock_latest_bar(request)
    if isinstance(bar, dict):
        bar = bar[symbol]
    return {
        "timestamp": bar.timestamp,
        "open": float(bar.open),
        "high": float(bar.high),
        "low": float(bar.low),
        "close": float(bar.close),
        "volume": int(bar.volume),
    }


async def get_multiple_bars(
    symbols: list[str],
    timeframe: str = "1Day",
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict[str, pd.DataFrame]:
    """
    Fetch bars for multiple symbols concurrently.

    Returns:
        Dict mapping symbol -> DataFrame
    """
    loop = asyncio.get_event_loop()
    results: dict[str, pd.DataFrame] = {}

    async def fetch_one(sym: str) -> None:
        df = await loop.run_in_executor(
            None, lambda: get_historical_bars(sym, timeframe, start, end)
        )
        results[sym] = df

    await asyncio.gather(*(fetch_one(s) for s in symbols))
    return results


def clear_cache() -> int:
    """Remove all cached data files. Returns count of files removed."""
    count = 0
    for f in CACHE_DIR.glob("*.parquet"):
        f.unlink()
        count += 1
    logger.info("Cleared %d cached files", count)
    return count
