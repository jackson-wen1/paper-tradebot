"""
Mean Reversion Strategy — Bollinger Bands, Z-score, RSI extremes, pairs trading.

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
class MeanReversionConfig:
    """Configurable parameters for the mean reversion strategy."""
    # Bollinger Bands
    bb_period: int = 20
    bb_std_dev: float = 2.0
    # Z-score
    zscore_period: int = 20
    zscore_entry: float = 2.0      # Enter at ±2 std devs
    zscore_exit: float = 0.5       # Exit when within 0.5 std devs of mean
    # RSI
    rsi_period: int = 14
    rsi_oversold: float = 25.0     # More extreme than momentum
    rsi_overbought: float = 75.0
    # Time-based exit
    max_holding_bars: int = 20     # Force exit after N bars
    # Signal combination
    min_confirmations: int = 2


def _compute_bollinger_bands(close: pd.Series, period: int, num_std: float) -> pd.DataFrame:
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return pd.DataFrame({
        "bb_upper": sma + num_std * std,
        "bb_middle": sma,
        "bb_lower": sma - num_std * std,
        "bb_width": (num_std * std * 2) / sma,  # Bandwidth
    }, index=close.index)


def _compute_zscore(close: pd.Series, period: int) -> pd.Series:
    mean = close.rolling(period).mean()
    std = close.rolling(period).std()
    return (close - mean) / std


def _compute_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _adf_test_stationary(series: pd.Series, max_lags: int = 20) -> tuple[bool, float]:
    """
    Simple stationarity check using autocorrelation decay.
    Returns (is_stationary, half_life_estimate).
    For a proper ADF test, use statsmodels.
    """
    # Approximate half-life from lag-1 autocorrelation
    lag1_corr = series.autocorr(lag=1)
    if lag1_corr is not None and 0 < lag1_corr < 1:
        half_life = -np.log(2) / np.log(lag1_corr)
    else:
        half_life = float("inf")

    # Rough stationarity check: if autocorrelation decays, likely mean-reverting
    is_stationary = 0 < lag1_corr < 0.95 if lag1_corr is not None else False
    return is_stationary, half_life


def generate_signals(
    data: pd.DataFrame,
    config: Optional[MeanReversionConfig] = None,
) -> pd.DataFrame:
    """
    Generate mean reversion trading signals from OHLCV data.

    Args:
        data: DataFrame with columns: open, high, low, close, volume
        config: Strategy parameters

    Returns:
        DataFrame with columns: signal (1=buy, -1=sell, 0=hold),
        plus indicator values for analysis
    """
    config = config or MeanReversionConfig()
    close = data["close"]

    # Calculate indicators
    bb = _compute_bollinger_bands(close, config.bb_period, config.bb_std_dev)
    zscore = _compute_zscore(close, config.zscore_period)
    rsi = _compute_rsi(close, config.rsi_period)

    # Individual signals
    # Bollinger Band: buy below lower, sell above upper
    bb_buy = close < bb["bb_lower"]
    bb_sell = close > bb["bb_upper"]

    # Z-score: buy when very negative, sell when very positive
    zscore_buy = zscore < -config.zscore_entry
    zscore_sell = zscore > config.zscore_entry

    # RSI extremes
    rsi_buy = rsi < config.rsi_oversold
    rsi_sell = rsi > config.rsi_overbought

    # Exit signals (revert to mean)
    exit_signal = abs(zscore) < config.zscore_exit

    # Combine: count confirmations
    buy_count = bb_buy.astype(int) + zscore_buy.astype(int) + rsi_buy.astype(int)
    sell_count = bb_sell.astype(int) + zscore_sell.astype(int) + rsi_sell.astype(int)

    signal = pd.Series(0, index=data.index, name="signal")
    signal[buy_count >= config.min_confirmations] = 1
    signal[sell_count >= config.min_confirmations] = -1

    # Exit positions when price reverts to mean
    # This is handled by the backtester/executor tracking holding period
    signal_strength = pd.Series(0.5, index=data.index)
    signal_strength[abs(zscore) > config.zscore_entry * 1.5] = 1.0

    result = pd.DataFrame({
        "signal": signal,
        "signal_strength": signal_strength,
        "zscore": zscore,
        "rsi": rsi,
        "bb_upper": bb["bb_upper"],
        "bb_middle": bb["bb_middle"],
        "bb_lower": bb["bb_lower"],
        "bb_width": bb["bb_width"],
        "exit_signal": exit_signal.astype(int),
    }, index=data.index)

    buy_total = (signal == 1).sum()
    sell_total = (signal == -1).sum()
    logger.info("Mean reversion signals: %d buys, %d sells out of %d bars",
                buy_total, sell_total, len(data))

    # Log stationarity check
    is_stat, half_life = _adf_test_stationary(close)
    logger.info("Stationarity check: stationary=%s, half_life=%.1f bars", is_stat, half_life)

    return result


def backtest(
    symbol: str = "SPY",
    start: str = "2023-01-01",
    end: str = "2025-01-01",
    timeframe: str = "1Day",
    config: Optional[MeanReversionConfig] = None,
    bt_config: Optional[BacktestConfig] = None,
) -> BacktestResult:
    """Run a backtest of the mean reversion strategy on historical data."""
    logger.info("Running mean reversion backtest: %s %s to %s", symbol, start, end)

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
    config: Optional[MeanReversionConfig] = None,
) -> Optional[dict]:
    """
    Execute the mean reversion strategy for a single bar update.

    Called during live/paper trading when new data arrives.
    """
    signals = generate_signals(data, config)
    latest = signals.iloc[-1]
    signal = int(latest["signal"])
    strength = float(latest["signal_strength"])
    is_exit = bool(latest["exit_signal"])

    # If we have a position and the exit signal fires, sell
    if is_exit and symbol in risk_manager.state.positions:
        pos = risk_manager.state.positions[symbol]
        order = submit_market_order(symbol, "sell", pos.quantity)
        risk_manager.close_position(symbol)
        logger.info("Mean reversion exit: %s (reverted to mean)", symbol)
        return order

    if signal == 0:
        return None

    current_price = float(data["close"].iloc[-1])
    side = "buy" if signal == 1 else "sell"

    qty = risk_manager.calculate_position_size(account_equity, current_price, strength)
    if qty <= 0:
        return None

    valid, reason = risk_manager.validate_order(
        symbol, side, qty, current_price, account_equity, buying_power
    )
    if not valid:
        logger.warning("Order rejected by risk manager: %s", reason)
        return None

    order = submit_market_order(symbol, side, qty)

    if signal == 1:
        risk_manager.register_position(symbol, current_price, qty, "long")
    else:
        risk_manager.close_position(symbol)

    logger.info("Mean reversion %s executed: %s x%d @ ~$%.2f", side, symbol, qty, current_price)
    return order
