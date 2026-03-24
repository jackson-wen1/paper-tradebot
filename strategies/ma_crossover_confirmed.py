"""
MA Crossover Confirmed Strategy — ML-optimizable moving average crossover
with three confirmation modes.

Core idea:
  Compute a short-term MA and long-term MA.
  When they cross, wait for *confirmation* before acting. The confirmation
  logic depends on the chosen signal mode:

Signal Modes:
  1. iqr_avg     — After a cross, check MA diff across a confirmation window.
                   The diff must exceed a threshold derived from the MEAN of
                   recent rolling-IQR values measured before the cross.
  2. iqr_highlow — Same as (1), but uses asymmetric thresholds: the MAX of
                   recent IQR for buy signals (conservative in high-vol) and
                   the MIN for sell signals (quicker exit in low-vol).
  3. bollinger   — After a cross, if the short MA breaks through Bollinger
                   Bands computed on the long MA within a configurable window,
                   signal. Captures strong momentum after the cross.

Structural features:
  - Window confirmation: fires as soon as threshold is met within 1..N bars
  - Trend filter: optional long-term MA to avoid counter-trend trades
  - Volume filter: optional above-average volume requirement
  - Exit on reverse cross: immediate sell when MAs cross back (no confirmation)

All tuneable parameters were optimised via walk-forward random search
(optimization/ folder, gitignored).

Exposes generate_signals(), backtest(), and execute() as required by the project.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from infrastructure.data_pipeline import get_historical_bars
from infrastructure.backtesting import (
    BacktestEngine,
    BacktestConfig,
    BacktestResult,
    format_backtest_report,
)
from infrastructure.risk_management import RiskManager
from infrastructure.order_execution import submit_market_order

logger = logging.getLogger(__name__)

VALID_SIGNAL_MODES = ("iqr_avg", "iqr_highlow", "bollinger")


@dataclass
class MACrossoverConfig:
    """All tuneable parameters for the confirmed MA crossover strategy."""

    # Moving averages
    short_ma_period: int = 11
    long_ma_period: int = 21

    # Signal mode
    signal_mode: str = "iqr_avg"  # "iqr_avg" | "iqr_highlow" | "bollinger"

    # Confirmation window — check across bars 1..N after the cross (modes 1 & 2)
    confirmation_bars: int = 6

    # Fallback threshold as a fraction of price (used when IQR data is sparse)
    confirmation_pct: float = 0.002

    # IQR parameters (modes iqr_avg & iqr_highlow)
    iqr_window: int = 7        # rolling window for IQR of close prices
    iqr_lookback: int = 20     # how many IQR values to aggregate before the cross
    iqr_multiplier: float = 1.8110  # scale the IQR-based threshold

    # Bollinger Band parameters (mode bollinger)
    bb_period: int = 21        # lookback for BB computed on the long MA series
    bb_std_dev: float = 2.0    # number of standard deviations
    bb_wait_bars: int = 5      # max bars after cross to wait for BB break

    # Trend filter — long-term MA; set to 0 to disable
    trend_ma_period: int = 11

    # Volume filter — require volume > X× its moving average; set to 0 to disable
    volume_ma_period: int = 2
    volume_multiplier: float = 1.6263

    # Exit on reverse cross without needing confirmation
    exit_on_reverse: bool = False


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------

def _rolling_iqr(close: pd.Series, window: int) -> np.ndarray:
    """Compute rolling IQR (Q3 − Q1) of a price series — vectorized."""
    q75 = close.rolling(window).quantile(0.75)
    q25 = close.rolling(window).quantile(0.25)
    return (q75 - q25).values


def _bollinger_on_series(
    series: pd.Series, period: int, num_std: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute Bollinger Bands on an arbitrary series (e.g. the long MA)."""
    mid = series.rolling(period).mean()
    std = series.rolling(period).std()
    upper = (mid + num_std * std).values
    lower = (mid - num_std * std).values
    return upper, lower


# ---------------------------------------------------------------------------
# Signal generation (stateful bar-by-bar loop)
# ---------------------------------------------------------------------------

def generate_signals(
    data: pd.DataFrame,
    config: Optional[MACrossoverConfig] = None,
) -> pd.DataFrame:
    """
    Generate MA crossover signals with confirmation.

    Args:
        data: DataFrame with columns open, high, low, close, volume
        config: Strategy parameters (all ML-optimizable)

    Returns:
        DataFrame indexed like *data* with columns:
          signal          — 1 (buy), -1 (sell), 0 (hold)
          signal_strength — 0.0–1.0
          short_ma, long_ma, bb_upper, bb_lower
    """
    config = config or MACrossoverConfig()
    if config.signal_mode not in VALID_SIGNAL_MODES:
        raise ValueError(f"signal_mode must be one of {VALID_SIGNAL_MODES}")

    close = data["close"].astype(float)
    n = len(close)

    # --- Compute indicators ---
    short_ma = close.rolling(config.short_ma_period).mean().values
    long_ma = close.rolling(config.long_ma_period).mean().values
    rolling_iqr = _rolling_iqr(close, config.iqr_window)

    long_ma_series = pd.Series(long_ma, index=data.index)
    bb_upper, bb_lower = _bollinger_on_series(
        long_ma_series, config.bb_period, config.bb_std_dev,
    )

    # Trend filter MA (0 = disabled)
    trend_ma = np.full(n, np.nan)
    if config.trend_ma_period > 0:
        trend_ma = close.rolling(config.trend_ma_period).mean().values

    # Volume filter (0 = disabled)
    vol_ma = np.full(n, np.nan)
    if config.volume_ma_period > 0 and "volume" in data.columns:
        volume = data["volume"].astype(float)
        vol_ma = volume.rolling(config.volume_ma_period).mean().values

    # --- Output arrays ---
    signal = np.zeros(n, dtype=int)
    strength = np.full(n, 0.5)

    # --- State machine ---
    warmup = max(
        config.long_ma_period,
        config.iqr_window + config.iqr_lookback,
        config.bb_period + config.long_ma_period,
        config.trend_ma_period,
    ) + 1

    cross_type: Optional[str] = None   # "up" or "down"
    cross_bar: int = -999
    confirmed: bool = False             # has this cross already fired a signal?
    buy_thresh: float = 0.0
    sell_thresh: float = 0.0
    in_position: bool = False           # track if we've entered a long

    for i in range(warmup, n):
        # Skip if MAs not ready
        if np.isnan(short_ma[i]) or np.isnan(long_ma[i]) \
           or np.isnan(short_ma[i - 1]) or np.isnan(long_ma[i - 1]):
            continue

        prev_above = short_ma[i - 1] > long_ma[i - 1]
        curr_above = short_ma[i] > long_ma[i]

        # ---- Exit on reverse cross (no confirmation needed) ----
        if config.exit_on_reverse and in_position:
            if not curr_above and prev_above:
                # MAs crossed back down while we're long → exit
                signal[i] = -1
                strength[i] = 0.5
                in_position = False
                cross_type = None
                confirmed = False
                continue

        # ---- Detect new crossover ----
        new_cross = False
        if curr_above and not prev_above:
            cross_type, cross_bar, new_cross, confirmed = "up", i, True, False
        elif not curr_above and prev_above:
            cross_type, cross_bar, new_cross, confirmed = "down", i, True, False

        # Compute IQR thresholds at the moment of the cross
        if new_cross and config.signal_mode in ("iqr_avg", "iqr_highlow"):
            start_idx = max(0, i - config.iqr_lookback)
            iqr_slice = rolling_iqr[start_idx:i]
            valid = iqr_slice[~np.isnan(iqr_slice)]
            if len(valid) > 0:
                if config.signal_mode == "iqr_avg":
                    buy_thresh = float(np.mean(valid)) * config.iqr_multiplier
                    sell_thresh = buy_thresh
                else:  # iqr_highlow
                    buy_thresh = float(np.max(valid)) * config.iqr_multiplier
                    sell_thresh = float(np.min(valid)) * config.iqr_multiplier
            else:
                buy_thresh = float(close.iloc[i]) * config.confirmation_pct
                sell_thresh = buy_thresh

        # ---- Check confirmation (window: any bar from 1..N) ----
        bars_since = i - cross_bar

        if config.signal_mode in ("iqr_avg", "iqr_highlow"):
            if cross_type is not None and not confirmed \
               and 1 <= bars_since <= config.confirmation_bars:
                ma_diff = abs(short_ma[i] - long_ma[i])
                if cross_type == "up" and ma_diff > buy_thresh:
                    if _passes_filters(config, close, data, trend_ma, vol_ma, i, "buy"):
                        signal[i] = 1
                        excess = (ma_diff - buy_thresh) / buy_thresh if buy_thresh > 0 else 1.0
                        strength[i] = min(1.0, 0.3 + 0.35 * excess)
                        confirmed = True
                        in_position = True
                elif cross_type == "down" and ma_diff > sell_thresh:
                    if _passes_filters(config, close, data, trend_ma, vol_ma, i, "sell"):
                        signal[i] = -1
                        excess = (ma_diff - sell_thresh) / sell_thresh if sell_thresh > 0 else 1.0
                        strength[i] = min(1.0, 0.3 + 0.35 * excess)
                        confirmed = True
                        in_position = False
            # Expire after confirmation window
            if cross_type is not None and bars_since > config.confirmation_bars:
                cross_type = None

        elif config.signal_mode == "bollinger":
            if cross_type is not None and not confirmed \
               and 0 < bars_since <= config.bb_wait_bars:
                if not np.isnan(bb_upper[i]) and not np.isnan(bb_lower[i]):
                    if cross_type == "up" and short_ma[i] > bb_upper[i]:
                        if _passes_filters(config, close, data, trend_ma, vol_ma, i, "buy"):
                            signal[i] = 1
                            band_width = bb_upper[i] - bb_lower[i]
                            bb_excess = (short_ma[i] - bb_upper[i]) / band_width if band_width > 0 else 1.0
                            strength[i] = min(1.0, 0.3 + 0.35 * bb_excess)
                            confirmed = True
                            in_position = True
                    elif cross_type == "down" and short_ma[i] < bb_lower[i]:
                        if _passes_filters(config, close, data, trend_ma, vol_ma, i, "sell"):
                            signal[i] = -1
                            band_width = bb_upper[i] - bb_lower[i]
                            bb_excess = (bb_lower[i] - short_ma[i]) / band_width if band_width > 0 else 1.0
                            strength[i] = min(1.0, 0.3 + 0.35 * bb_excess)
                            confirmed = True
                            in_position = False
            if cross_type is not None and bars_since > config.bb_wait_bars:
                cross_type = None  # window expired

    # --- Build result ---
    result = pd.DataFrame(
        {
            "signal": signal,
            "signal_strength": strength,
            "short_ma": short_ma,
            "long_ma": long_ma,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
        },
        index=data.index,
    )

    buy_total = int((signal == 1).sum())
    sell_total = int((signal == -1).sum())
    logger.info(
        "MA Crossover [%s]: %d buys, %d sells out of %d bars",
        config.signal_mode, buy_total, sell_total, n,
    )
    return result


def _passes_filters(
    config: MACrossoverConfig,
    close: pd.Series,
    data: pd.DataFrame,
    trend_ma: np.ndarray,
    vol_ma: np.ndarray,
    i: int,
    side: str,
) -> bool:
    """Check trend and volume filters. Returns True if the signal is allowed."""
    # Trend filter
    if config.trend_ma_period > 0 and not np.isnan(trend_ma[i]):
        price = float(close.iloc[i])
        if side == "buy" and price < trend_ma[i]:
            return False   # don't buy below trend
        if side == "sell" and price > trend_ma[i]:
            return False   # don't sell above trend

    # Volume filter
    if config.volume_ma_period > 0 and "volume" in data.columns \
       and not np.isnan(vol_ma[i]):
        current_vol = float(data["volume"].iloc[i])
        if current_vol < vol_ma[i] * config.volume_multiplier:
            return False   # volume too low

    return True


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def backtest(
    symbol: str = "SPY",
    start: str = "2023-01-01",
    end: str = "2025-01-01",
    timeframe: str = "1Day",
    config: Optional[MACrossoverConfig] = None,
    bt_config: Optional[BacktestConfig] = None,
) -> BacktestResult:
    """Run a backtest of the confirmed MA crossover strategy."""
    logger.info("Running MA crossover backtest: %s %s→%s", symbol, start, end)

    data = get_historical_bars(symbol, timeframe, start, end)
    if data.empty:
        raise ValueError(f"No data returned for {symbol}")

    signals = generate_signals(data, config)
    engine = BacktestEngine(bt_config)
    result = engine.run(data, signals, symbol)

    logger.info("\n%s", format_backtest_report(result))
    return result


# ---------------------------------------------------------------------------
# Live / paper execution
# ---------------------------------------------------------------------------

def execute(
    symbol: str,
    risk_manager: RiskManager,
    account_equity: float,
    buying_power: float,
    data: pd.DataFrame,
    config: Optional[MACrossoverConfig] = None,
) -> Optional[dict]:
    """
    Execute the strategy for a single bar update (live/paper trading).

    Called by the cron‐tick loop when new data arrives. Generates signal
    from the latest bar window and submits an order if appropriate.
    """
    signals = generate_signals(data, config)
    latest = signals.iloc[-1]
    signal_val = int(latest["signal"])
    strength_val = float(latest["signal_strength"])

    if signal_val == 0:
        return None

    current_price = float(data["close"].iloc[-1])
    side = "buy" if signal_val == 1 else "sell"

    qty = risk_manager.calculate_position_size(
        account_equity, current_price, strength_val,
    )
    if qty <= 0:
        return None

    valid, reason = risk_manager.validate_order(
        symbol, side, qty, current_price, account_equity, buying_power,
    )
    if not valid:
        logger.warning("Order rejected by risk manager: %s", reason)
        return None

    order = submit_market_order(symbol, side, qty)

    if signal_val == 1:
        risk_manager.register_position(symbol, current_price, qty, "long")
    else:
        risk_manager.close_position(symbol)

    logger.info(
        "MA Crossover %s: %s x%d @ ~$%.2f", side, symbol, qty, current_price,
    )
    return order
