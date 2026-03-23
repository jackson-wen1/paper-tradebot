"""
Momentum Strategy — MACD crossovers, RSI, Rate of Change, volume confirmation.

Exposes generate_signals(), backtest(), and execute() as required by the project.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from infrastructure.data_pipeline import get_historical_bars
from infrastructure.backtesting import BacktestEngine, BacktestConfig, BacktestResult, format_backtest_report
from infrastructure.risk_management import RiskManager
from infrastructure.order_execution import submit_market_order

logger = logging.getLogger(__name__)


@dataclass
class MomentumConfig:
    """Configurable parameters for the momentum strategy."""
    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    # RSI
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    # Rate of Change
    roc_period: int = 10
    roc_threshold: float = 0.02
    # Volume
    volume_ma_period: int = 20
    volume_multiplier: float = 1.5
    # Signal combination
    min_confirmations: int = 2  # How many indicators must agree


def _compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _compute_macd(close: pd.Series, fast: int, slow: int, signal: int) -> pd.DataFrame:
    ema_fast = _compute_ema(close, fast)
    ema_slow = _compute_ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return pd.DataFrame({
        "macd": macd_line,
        "macd_signal": signal_line,
        "macd_hist": histogram,
    }, index=close.index)


def _compute_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _compute_roc(close: pd.Series, period: int) -> pd.Series:
    return close.pct_change(periods=period)


def generate_signals(
    data: pd.DataFrame,
    config: Optional[MomentumConfig] = None,
) -> pd.DataFrame:
    """
    Generate momentum trading signals from OHLCV data.

    Args:
        data: DataFrame with columns: open, high, low, close, volume
        config: Strategy parameters

    Returns:
        DataFrame with columns: signal (1=buy, -1=sell, 0=hold),
        plus indicator values for analysis
    """
    config = config or MomentumConfig()
    close = data["close"]
    volume = data["volume"]

    # Calculate indicators
    macd_df = _compute_macd(close, config.macd_fast, config.macd_slow, config.macd_signal)
    rsi = _compute_rsi(close, config.rsi_period)
    roc = _compute_roc(close, config.roc_period)
    volume_ma = volume.rolling(config.volume_ma_period).mean()

    # Individual signals
    # MACD: bullish cross = 1, bearish cross = -1
    macd_prev = macd_df["macd_hist"].shift(1)
    macd_signal_buy = (macd_df["macd_hist"] > 0) & (macd_prev <= 0)
    macd_signal_sell = (macd_df["macd_hist"] < 0) & (macd_prev >= 0)

    # RSI: oversold cross up = 1, overbought cross down = -1
    rsi_prev = rsi.shift(1)
    rsi_signal_buy = (rsi > config.rsi_oversold) & (rsi_prev <= config.rsi_oversold)
    rsi_signal_sell = (rsi < config.rsi_overbought) & (rsi_prev >= config.rsi_overbought)

    # ROC: breakout above threshold = 1, breakdown below -threshold = -1
    roc_signal_buy = roc > config.roc_threshold
    roc_signal_sell = roc < -config.roc_threshold

    # Volume confirmation
    high_volume = volume > (volume_ma * config.volume_multiplier)

    # Combine: count confirmations
    buy_count = (
        macd_signal_buy.astype(int)
        + rsi_signal_buy.astype(int)
        + roc_signal_buy.astype(int)
    )
    sell_count = (
        macd_signal_sell.astype(int)
        + rsi_signal_sell.astype(int)
        + roc_signal_sell.astype(int)
    )

    signal = pd.Series(0, index=data.index, name="signal")
    signal[buy_count >= config.min_confirmations] = 1
    signal[sell_count >= config.min_confirmations] = -1

    # Volume filter: only act on high volume (optional boost, not hard filter)
    signal_strength = pd.Series(0.5, index=data.index)
    signal_strength[high_volume] = 1.0

    result = pd.DataFrame({
        "signal": signal,
        "signal_strength": signal_strength,
        "rsi": rsi,
        "macd": macd_df["macd"],
        "macd_signal": macd_df["macd_signal"],
        "macd_hist": macd_df["macd_hist"],
        "roc": roc,
    }, index=data.index)

    buy_count_total = (signal == 1).sum()
    sell_count_total = (signal == -1).sum()
    logger.info("Momentum signals: %d buys, %d sells out of %d bars",
                buy_count_total, sell_count_total, len(data))

    return result


def backtest(
    symbol: str = "SPY",
    start: str = "2023-01-01",
    end: str = "2025-01-01",
    timeframe: str = "1Day",
    config: Optional[MomentumConfig] = None,
    bt_config: Optional[BacktestConfig] = None,
) -> BacktestResult:
    """
    Run a backtest of the momentum strategy on historical data.

    Args:
        symbol: Ticker to backtest on
        start: Start date (ISO string)
        end: End date (ISO string)
        timeframe: Bar timeframe
        config: Strategy parameters
        bt_config: Backtesting engine parameters

    Returns:
        BacktestResult with metrics and trade log
    """
    logger.info("Running momentum backtest: %s %s to %s", symbol, start, end)

    data = get_historical_bars(symbol, timeframe, start, end)
    if data.empty:
        raise ValueError(f"No data returned for {symbol}")

    signals = generate_signals(data, config)
    engine = BacktestEngine(bt_config)
    result = engine.run(data, signals, symbol)

    logger.info("\n%s", format_backtest_report(result))
    return result


def execute(
    symbol: str,
    risk_manager: RiskManager,
    account_equity: float,
    buying_power: float,
    data: pd.DataFrame,
    config: Optional[MomentumConfig] = None,
) -> Optional[dict]:
    """
    Execute the momentum strategy for a single bar update.

    This is called during live/paper trading when new data arrives.
    Generates a signal from the latest data and submits orders if appropriate.

    Args:
        symbol: Ticker symbol
        risk_manager: RiskManager instance for validation
        account_equity: Current account equity
        buying_power: Current buying power
        data: Recent OHLCV data (enough history for indicator calculation)
        config: Strategy parameters

    Returns:
        Order dict if an order was placed, None otherwise
    """
    signals = generate_signals(data, config)
    latest = signals.iloc[-1]
    signal = int(latest["signal"])
    strength = float(latest["signal_strength"])

    if signal == 0:
        return None

    current_price = float(data["close"].iloc[-1])
    side = "buy" if signal == 1 else "sell"

    # Risk validation
    qty = risk_manager.calculate_position_size(account_equity, current_price, strength)
    if qty <= 0:
        return None

    valid, reason = risk_manager.validate_order(
        symbol, side, qty, current_price, account_equity, buying_power
    )
    if not valid:
        logger.warning("Order rejected by risk manager: %s", reason)
        return None

    # Submit order
    order = submit_market_order(symbol, side, qty)

    # Register with risk manager
    if signal == 1:
        risk_manager.register_position(symbol, current_price, qty, "long")
    else:
        risk_manager.close_position(symbol)

    logger.info("Momentum %s executed: %s x%d @ ~$%.2f", side, symbol, qty, current_price)
    return order
