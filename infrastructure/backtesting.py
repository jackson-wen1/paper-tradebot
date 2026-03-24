"""
Backtesting Engine — Run strategies against historical data with realistic simulation.

Supports configurable initial capital, commission model, slippage, and generates
comprehensive performance metrics. No lookahead bias.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Backtesting parameters."""
    initial_capital: float = 100_000.0
    commission_per_trade: float = 0.0      # Alpaca is commission-free
    slippage_pct: float = 0.001            # 0.1% slippage assumption
    max_position_pct: float = 0.05         # 5% per position
    risk_free_rate: float = 0.05           # For Sharpe/Sortino calculation


@dataclass
class Trade:
    """Record of a single completed trade."""
    symbol: str
    side: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    return_pct: float


@dataclass
class BacktestResult:
    """Full backtest output with metrics and trade log."""
    config: BacktestConfig
    trades: list[Trade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    benchmark_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    metrics: dict = field(default_factory=dict)


class BacktestEngine:
    """
    Chronological backtesting engine. Iterates bar-by-bar, simulates fills,
    and tracks portfolio state. No future data leakage.
    """

    def __init__(self, config: Optional[BacktestConfig] = None) -> None:
        self.config = config or BacktestConfig()
        self._cash = self.config.initial_capital
        self._positions: dict[str, dict] = {}  # symbol -> {qty, entry_price, entry_time}
        self._trades: list[Trade] = []
        self._equity_history: list[tuple[pd.Timestamp, float]] = []

    def run(
        self,
        data: pd.DataFrame,
        signals: pd.DataFrame,
        symbol: str = "UNKNOWN",
    ) -> BacktestResult:
        """
        Run backtest on a single symbol.

        Args:
            data: OHLCV DataFrame indexed by timestamp
            signals: DataFrame with 'signal' column (1=buy, -1=sell, 0=hold)
                     indexed by same timestamps as data
            symbol: Ticker symbol name

        Returns:
            BacktestResult with metrics and trade log
        """
        self._cash = self.config.initial_capital
        self._positions = {}
        self._trades = []
        self._equity_history = []

        if "signal" not in signals.columns:
            raise ValueError("signals DataFrame must have a 'signal' column")

        # Align data and signals
        common_idx = data.index.intersection(signals.index)
        data = data.loc[common_idx]
        signals = signals.loc[common_idx]

        for timestamp in data.index:
            bar = data.loc[timestamp]
            signal = signals.loc[timestamp, "signal"]
            current_price = float(bar["close"])

            # Apply slippage
            buy_price = current_price * (1 + self.config.slippage_pct)
            sell_price = current_price * (1 - self.config.slippage_pct)

            # Process signals
            if signal == 1 and symbol not in self._positions:
                # BUY
                max_value = self._cash * self.config.max_position_pct
                qty = int(max_value / buy_price) if buy_price > 0 else 0
                if qty > 0:
                    cost = qty * buy_price + self.config.commission_per_trade
                    if cost <= self._cash:
                        self._cash -= cost
                        self._positions[symbol] = {
                            "qty": qty,
                            "entry_price": buy_price,
                            "entry_time": timestamp,
                        }

            elif signal == -1 and symbol in self._positions:
                # SELL
                pos = self._positions.pop(symbol)
                proceeds = pos["qty"] * sell_price - self.config.commission_per_trade
                self._cash += proceeds
                pnl = proceeds - (pos["qty"] * pos["entry_price"])
                ret = (sell_price - pos["entry_price"]) / pos["entry_price"]

                self._trades.append(Trade(
                    symbol=symbol,
                    side="long",
                    entry_time=pos["entry_time"],
                    exit_time=timestamp,
                    entry_price=pos["entry_price"],
                    exit_price=sell_price,
                    quantity=pos["qty"],
                    pnl=pnl,
                    return_pct=ret,
                ))

            # Record equity
            portfolio_value = self._cash
            for sym, pos in self._positions.items():
                portfolio_value += pos["qty"] * current_price
            self._equity_history.append((timestamp, portfolio_value))

        # Close any remaining positions at last price
        if self._positions and len(data) > 0:
            last_bar = data.iloc[-1]
            last_price = float(last_bar["close"]) * (1 - self.config.slippage_pct)
            last_time = data.index[-1]
            for sym in list(self._positions.keys()):
                pos = self._positions.pop(sym)
                proceeds = pos["qty"] * last_price - self.config.commission_per_trade
                self._cash += proceeds
                pnl = proceeds - (pos["qty"] * pos["entry_price"])
                ret = (last_price - pos["entry_price"]) / pos["entry_price"]
                self._trades.append(Trade(
                    symbol=sym,
                    side="long",
                    entry_time=pos["entry_time"],
                    exit_time=last_time,
                    entry_price=pos["entry_price"],
                    exit_price=last_price,
                    quantity=pos["qty"],
                    pnl=pnl,
                    return_pct=ret,
                ))

        # Build equity curve
        equity_curve = pd.Series(
            [e[1] for e in self._equity_history],
            index=[e[0] for e in self._equity_history],
            name="equity",
        )

        # Build benchmark (buy-and-hold SPY proxy using the same data)
        benchmark_curve = pd.Series(
            self.config.initial_capital * data["close"] / data["close"].iloc[0],
            name="benchmark",
        ) if len(data) > 0 else pd.Series(dtype=float)

        # Calculate metrics
        metrics = self._calculate_metrics(equity_curve)

        result = BacktestResult(
            config=self.config,
            trades=self._trades,
            equity_curve=equity_curve,
            benchmark_curve=benchmark_curve,
            metrics=metrics,
        )

        logger.info(
            "Backtest complete: %d trades, total return %.2f%%, Sharpe %.2f",
            len(self._trades),
            metrics.get("total_return_pct", 0),
            metrics.get("sharpe_ratio", 0),
        )

        return result

    def _calculate_metrics(self, equity_curve: pd.Series) -> dict:
        """Calculate comprehensive performance metrics."""
        if len(equity_curve) < 2:
            return {"error": "Insufficient data for metrics"}

        initial = self.config.initial_capital
        final = equity_curve.iloc[-1]
        total_return = (final - initial) / initial

        # Daily returns
        daily_returns = equity_curve.pct_change().dropna()

        # Trading days
        n_days = len(equity_curve)
        n_years = n_days / 252 if n_days > 0 else 1

        # Annualized return
        annualized_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0

        # Sharpe ratio (annualized)
        rf_daily = self.config.risk_free_rate / 252
        excess_returns = daily_returns - rf_daily
        excess_std = float(excess_returns.std())
        sharpe = (
            np.sqrt(252) * float(excess_returns.mean()) / excess_std
            if excess_std > 1e-12 else 0.0
        )

        # Sortino ratio (only downside deviation)
        downside = daily_returns[daily_returns < 0]
        downside_std = float(downside.std()) if len(downside) > 0 else 0.0
        sortino = (
            np.sqrt(252) * (float(daily_returns.mean()) - rf_daily) / downside_std
            if downside_std > 1e-12 else 0.0
        )

        # Max drawdown
        cummax = equity_curve.cummax()
        drawdown = (equity_curve - cummax) / cummax
        max_drawdown = drawdown.min()

        # Drawdown duration
        in_drawdown = equity_curve < cummax
        if in_drawdown.any():
            dd_groups = (~in_drawdown).cumsum()
            dd_durations = in_drawdown.groupby(dd_groups).sum()
            max_dd_duration = dd_durations.max()
        else:
            max_dd_duration = 0

        # Trade statistics
        pnls = [t.pnl for t in self._trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate = len(wins) / len(pnls) if pnls else 0
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        if not pnls:
            profit_factor = 0.0               # no trades → 0, not inf
        elif not losses or sum(losses) == 0:
            profit_factor = float(sum(wins))  # all winners → raw profit
        else:
            profit_factor = abs(sum(wins) / sum(losses))

        # Average holding period
        holding_periods = [
            (t.exit_time - t.entry_time).total_seconds() / 86400 for t in self._trades
        ]
        avg_holding = np.mean(holding_periods) if holding_periods else 0

        return {
            "total_return_pct": total_return * 100,
            "annualized_return_pct": annualized_return * 100,
            "sharpe_ratio": float(sharpe),
            "sortino_ratio": float(sortino),
            "max_drawdown_pct": float(max_drawdown * 100),
            "max_drawdown_duration_days": int(max_dd_duration),
            "total_trades": len(self._trades),
            "win_rate": win_rate,
            "avg_win": float(avg_win),
            "avg_loss": float(avg_loss),
            "profit_factor": float(profit_factor),
            "avg_holding_period_days": float(avg_holding),
            "initial_capital": initial,
            "final_equity": float(final),
        }


def format_backtest_report(result: BacktestResult) -> str:
    """Format backtest results as a readable string report."""
    m = result.metrics
    lines = [
        "=" * 60,
        "BACKTEST RESULTS",
        "=" * 60,
        f"Initial Capital:       ${m.get('initial_capital', 0):>12,.2f}",
        f"Final Equity:          ${m.get('final_equity', 0):>12,.2f}",
        f"Total Return:          {m.get('total_return_pct', 0):>12.2f}%",
        f"Annualized Return:     {m.get('annualized_return_pct', 0):>12.2f}%",
        "-" * 60,
        f"Sharpe Ratio:          {m.get('sharpe_ratio', 0):>12.2f}",
        f"Sortino Ratio:         {m.get('sortino_ratio', 0):>12.2f}",
        f"Max Drawdown:          {m.get('max_drawdown_pct', 0):>12.2f}%",
        f"Max DD Duration:       {m.get('max_drawdown_duration_days', 0):>12d} days",
        "-" * 60,
        f"Total Trades:          {m.get('total_trades', 0):>12d}",
        f"Win Rate:              {m.get('win_rate', 0):>12.1%}",
        f"Avg Win:               ${m.get('avg_win', 0):>12,.2f}",
        f"Avg Loss:              ${m.get('avg_loss', 0):>12,.2f}",
        f"Profit Factor:         {m.get('profit_factor', 0):>12.2f}",
        f"Avg Holding Period:    {m.get('avg_holding_period_days', 0):>12.1f} days",
        "=" * 60,
    ]
    return "\n".join(lines)
