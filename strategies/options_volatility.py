"""
Options & Volatility Strategy — IV analysis, vol surface, premium selling/buying.

Focuses on implied vs. historical volatility spreads, IV percentile/rank,
and options strategies (covered calls, iron condors, strangles, etc.).

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
class OptionsVolatilityConfig:
    """Configurable parameters for the options/volatility strategy."""
    # Historical volatility
    hv_period: int = 20           # HV lookback window
    hv_annual_factor: float = 252.0
    # IV rank / percentile thresholds
    iv_rank_high: float = 80.0    # Sell premium when IV rank > 80
    iv_rank_low: float = 20.0     # Buy premium when IV rank < 20
    iv_lookback: int = 252        # 1 year for IV rank calculation
    # Profit targets
    profit_target_pct: float = 0.50  # Close at 50% of max profit
    max_loss_pct: float = 2.0        # Max loss as multiple of credit received
    # DTE (days to expiry)
    min_dte: int = 30
    max_dte: int = 60
    exit_dte: int = 10               # Close position at this many DTE
    # Regime detection
    vix_high: float = 30.0          # High volatility regime
    vix_low: float = 15.0           # Low volatility regime


def _compute_historical_volatility(
    close: pd.Series, period: int, annualize: float = 252.0
) -> pd.Series:
    """Compute annualized historical (realized) volatility."""
    log_returns = np.log(close / close.shift(1))
    return log_returns.rolling(period).std() * np.sqrt(annualize)


def _compute_iv_rank(iv_series: pd.Series, lookback: int) -> pd.Series:
    """
    Compute IV rank: where current IV sits relative to its range over lookback period.
    IV Rank = (Current IV - Min IV) / (Max IV - Min IV) * 100
    """
    rolling_min = iv_series.rolling(lookback, min_periods=1).min()
    rolling_max = iv_series.rolling(lookback, min_periods=1).max()
    iv_range = rolling_max - rolling_min
    rank = ((iv_series - rolling_min) / iv_range) * 100
    return rank.fillna(50)


def _compute_iv_percentile(iv_series: pd.Series, lookback: int) -> pd.Series:
    """
    Compute IV percentile: % of days in lookback where IV was lower than current.
    """
    def pctile(window: pd.Series) -> float:
        current = window.iloc[-1]
        return (window.iloc[:-1] < current).mean() * 100

    return iv_series.rolling(lookback + 1, min_periods=2).apply(pctile, raw=False).fillna(50)


def _compute_vol_regime(hv: pd.Series, high_thresh: float, low_thresh: float) -> pd.Series:
    """
    Classify volatility regime.
    Returns: 'high', 'low', or 'normal' for each bar.
    """
    regime = pd.Series("normal", index=hv.index)
    # Annualized HV thresholds (approximate: VIX-like levels as % / 100)
    regime[hv > high_thresh / 100] = "high"
    regime[hv < low_thresh / 100] = "low"
    return regime


def generate_signals(
    data: pd.DataFrame,
    config: Optional[OptionsVolatilityConfig] = None,
) -> pd.DataFrame:
    """
    Generate volatility-based trading signals.

    Since we may not have real options IV data, we use historical volatility
    as a proxy. For real options trading, this would be enhanced with actual
    options chain data from Alpaca.

    Signal interpretation:
      1 = Buy premium (long volatility) — when IV rank is low
     -1 = Sell premium (short volatility) — when IV rank is high
      0 = No action

    Args:
        data: DataFrame with OHLCV columns
        config: Strategy parameters

    Returns:
        DataFrame with signal column and volatility indicators
    """
    config = config or OptionsVolatilityConfig()
    close = data["close"]

    # Historical volatility (proxy for IV when options data unavailable)
    hv = _compute_historical_volatility(close, config.hv_period)

    # IV rank and percentile (using HV as proxy)
    iv_rank = _compute_iv_rank(hv, config.iv_lookback)
    iv_pctile = _compute_iv_percentile(hv, config.iv_lookback)

    # HV vs longer-term HV (vol of vol, term structure proxy)
    hv_long = _compute_historical_volatility(close, config.hv_period * 3)
    vol_spread = hv - hv_long  # Positive = backwardation, negative = contango

    # Regime
    regime = _compute_vol_regime(hv, config.vix_high, config.vix_low)

    # Signals
    signal = pd.Series(0, index=data.index, name="signal")

    # Sell premium when IV rank is high (mean reversion play on volatility)
    sell_premium = (iv_rank > config.iv_rank_high) & (regime != "high")
    # Buy premium when IV rank is low and vol is expanding
    buy_premium = (iv_rank < config.iv_rank_low) & (vol_spread > 0)

    signal[sell_premium] = -1  # Sell premium / short vol
    signal[buy_premium] = 1   # Buy premium / long vol

    # Signal strength based on IV rank extremity
    signal_strength = pd.Series(0.5, index=data.index)
    signal_strength[iv_rank > 90] = 1.0
    signal_strength[iv_rank < 10] = 1.0
    signal_strength[(iv_rank > 70) & (iv_rank <= 90)] = 0.75
    signal_strength[(iv_rank >= 10) & (iv_rank < 30)] = 0.75

    result = pd.DataFrame({
        "signal": signal,
        "signal_strength": signal_strength,
        "hv": hv,
        "hv_long": hv_long,
        "iv_rank": iv_rank,
        "iv_percentile": iv_pctile,
        "vol_spread": vol_spread,
        "regime": regime,
    }, index=data.index)

    sell_total = (signal == -1).sum()
    buy_total = (signal == 1).sum()
    logger.info("Volatility signals: %d sell-premium, %d buy-premium out of %d bars",
                sell_total, buy_total, len(data))

    return result


def backtest(
    symbol: str = "SPY",
    start: str = "2023-01-01",
    end: str = "2025-01-01",
    timeframe: str = "1Day",
    config: Optional[OptionsVolatilityConfig] = None,
    bt_config: Optional[BacktestConfig] = None,
) -> BacktestResult:
    """
    Run a backtest of the volatility strategy.

    Note: This backtests the underlying equity signals derived from vol analysis.
    A full options backtest would require options chain historical data.
    """
    logger.info("Running volatility backtest: %s %s to %s", symbol, start, end)

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
    config: Optional[OptionsVolatilityConfig] = None,
) -> Optional[dict]:
    """
    Execute the volatility strategy for a single bar update.

    For actual options orders, this would need to be extended with
    Alpaca's options API endpoints.
    """
    signals = generate_signals(data, config)
    latest = signals.iloc[-1]
    signal = int(latest["signal"])
    strength = float(latest["signal_strength"])
    regime = str(latest["regime"])

    if signal == 0:
        return None

    # In high-vol regime, reduce position sizes
    if regime == "high":
        strength *= 0.5

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

    logger.info("Volatility %s executed: %s x%d @ ~$%.2f (regime=%s)",
                side, symbol, qty, current_price, regime)
    return order
