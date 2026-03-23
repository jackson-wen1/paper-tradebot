"""
Trend Following Strategy — Moving average crossovers, ADX, Donchian channels, Supertrend.

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
class TrendFollowingConfig:
    """Configurable parameters for the trend following strategy."""
    # Moving averages
    fast_ma_period: int = 50
    slow_ma_period: int = 200
    use_ema: bool = True
    # ADX (trend strength filter)
    adx_period: int = 14
    adx_threshold: float = 25.0    # Only trade when ADX > threshold
    # Donchian Channel
    donchian_period: int = 20
    # ATR trailing stop
    atr_period: int = 14
    atr_multiplier: float = 2.0
    # Volume confirmation
    volume_ma_period: int = 20
    require_volume_confirm: bool = True
    # Signal combination
    min_confirmations: int = 2


def _compute_ma(close: pd.Series, period: int, use_ema: bool) -> pd.Series:
    if use_ema:
        return close.ewm(span=period, adjust=False).mean()
    return close.rolling(period).mean()


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.DataFrame:
    """Compute ADX, +DI, -DI."""
    plus_dm = high.diff()
    minus_dm = -low.diff()

    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0

    # Where +DM > -DM, keep +DM; else 0 (and vice versa)
    mask = plus_dm > minus_dm
    plus_dm[~mask] = 0
    minus_dm[mask] = 0

    atr = _compute_atr(high, low, close, period)

    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)

    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    adx = dx.rolling(period).mean()

    return pd.DataFrame({
        "adx": adx,
        "plus_di": plus_di,
        "minus_di": minus_di,
    }, index=close.index)


def _compute_donchian(high: pd.Series, low: pd.Series, period: int) -> pd.DataFrame:
    return pd.DataFrame({
        "dc_upper": high.rolling(period).max(),
        "dc_lower": low.rolling(period).min(),
        "dc_middle": (high.rolling(period).max() + low.rolling(period).min()) / 2,
    }, index=high.index)


def _compute_supertrend(
    high: pd.Series, low: pd.Series, close: pd.Series,
    atr_period: int, multiplier: float,
) -> pd.DataFrame:
    atr = _compute_atr(high, low, close, atr_period)
    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr

    supertrend = pd.Series(0.0, index=close.index)
    direction = pd.Series(1, index=close.index)  # 1=up, -1=down

    for i in range(1, len(close)):
        if close.iloc[i] > upper_band.iloc[i - 1]:
            direction.iloc[i] = 1
        elif close.iloc[i] < lower_band.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]

        if direction.iloc[i] == 1:
            supertrend.iloc[i] = lower_band.iloc[i]
        else:
            supertrend.iloc[i] = upper_band.iloc[i]

    return pd.DataFrame({
        "supertrend": supertrend,
        "st_direction": direction,
    }, index=close.index)


def generate_signals(
    data: pd.DataFrame,
    config: Optional[TrendFollowingConfig] = None,
) -> pd.DataFrame:
    """
    Generate trend following signals from OHLCV data.

    Args:
        data: DataFrame with columns: open, high, low, close, volume
        config: Strategy parameters

    Returns:
        DataFrame with signal column and indicators
    """
    config = config or TrendFollowingConfig()
    close = data["close"]
    high = data["high"]
    low = data["low"]
    volume = data["volume"]

    # Indicators
    fast_ma = _compute_ma(close, config.fast_ma_period, config.use_ema)
    slow_ma = _compute_ma(close, config.slow_ma_period, config.use_ema)
    adx_df = _compute_adx(high, low, close, config.adx_period)
    donchian = _compute_donchian(high, low, config.donchian_period)
    st = _compute_supertrend(high, low, close, config.atr_period, config.atr_multiplier)
    atr = _compute_atr(high, low, close, config.atr_period)
    volume_ma = volume.rolling(config.volume_ma_period).mean()

    # MA crossover signals
    ma_prev_fast = fast_ma.shift(1)
    ma_prev_slow = slow_ma.shift(1)
    ma_buy = (fast_ma > slow_ma) & (ma_prev_fast <= ma_prev_slow)  # Golden cross
    ma_sell = (fast_ma < slow_ma) & (ma_prev_fast >= ma_prev_slow)  # Death cross

    # Donchian breakout
    dc_buy = close >= donchian["dc_upper"]
    dc_sell = close <= donchian["dc_lower"]

    # Supertrend direction change
    st_prev = st["st_direction"].shift(1)
    st_buy = (st["st_direction"] == 1) & (st_prev == -1)
    st_sell = (st["st_direction"] == -1) & (st_prev == 1)

    # ADX filter: only trade when trend is strong
    strong_trend = adx_df["adx"] > config.adx_threshold

    # Volume confirmation
    high_volume = volume > volume_ma if config.require_volume_confirm else pd.Series(True, index=data.index)

    # Combine confirmations
    buy_count = ma_buy.astype(int) + dc_buy.astype(int) + st_buy.astype(int)
    sell_count = ma_sell.astype(int) + dc_sell.astype(int) + st_sell.astype(int)

    signal = pd.Series(0, index=data.index, name="signal")
    signal[(buy_count >= config.min_confirmations) & strong_trend & high_volume] = 1
    signal[(sell_count >= config.min_confirmations) & strong_trend & high_volume] = -1

    # Signal strength based on ADX
    signal_strength = (adx_df["adx"] / 100).clip(0, 1).fillna(0.5)

    result = pd.DataFrame({
        "signal": signal,
        "signal_strength": signal_strength,
        "fast_ma": fast_ma,
        "slow_ma": slow_ma,
        "adx": adx_df["adx"],
        "plus_di": adx_df["plus_di"],
        "minus_di": adx_df["minus_di"],
        "dc_upper": donchian["dc_upper"],
        "dc_lower": donchian["dc_lower"],
        "supertrend": st["supertrend"],
        "st_direction": st["st_direction"],
        "atr": atr,
    }, index=data.index)

    buy_total = (signal == 1).sum()
    sell_total = (signal == -1).sum()
    logger.info("Trend following signals: %d buys, %d sells out of %d bars",
                buy_total, sell_total, len(data))

    return result


def backtest(
    symbol: str = "SPY",
    start: str = "2023-01-01",
    end: str = "2025-01-01",
    timeframe: str = "1Day",
    config: Optional[TrendFollowingConfig] = None,
    bt_config: Optional[BacktestConfig] = None,
) -> BacktestResult:
    """Run a backtest of the trend following strategy on historical data."""
    logger.info("Running trend following backtest: %s %s to %s", symbol, start, end)

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
    config: Optional[TrendFollowingConfig] = None,
) -> Optional[dict]:
    """Execute the trend following strategy for a single bar update."""
    signals = generate_signals(data, config)
    latest = signals.iloc[-1]
    signal = int(latest["signal"])
    strength = float(latest["signal_strength"])

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

    logger.info("Trend following %s executed: %s x%d @ ~$%.2f", side, symbol, qty, current_price)
    return order
