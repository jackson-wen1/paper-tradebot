"""
Risk Management — Position sizing, stop-losses, portfolio limits, order validation.

Acts as a gatekeeper: every order must pass risk checks before submission.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetStatus

from config import ALPACA_API_KEY, ALPACA_API_SECRET, ALPACA_BASE_URL

logger = logging.getLogger(__name__)


@dataclass
class RiskConfig:
    """Configurable risk parameters."""
    max_position_pct: float = 0.20         # Max 20% of portfolio per position
    max_portfolio_loss_daily_pct: float = 0.03  # Halt at 3% daily loss
    max_open_positions: int = 20
    default_stop_loss_pct: float = 0.02    # 2% stop-loss
    default_take_profit_pct: float = 0.04  # 4% take-profit (2:1 reward:risk)
    trailing_stop_pct: float = 0.015       # 1.5% trailing stop
    max_portfolio_exposure: float = 1.0    # 100% max (no leverage)


@dataclass
class PositionRisk:
    """Risk state for a single position."""
    symbol: str
    entry_price: float
    quantity: float
    side: str  # "long" or "short"
    stop_loss: float
    take_profit: float
    highest_price: float = 0.0  # For trailing stop
    lowest_price: float = float("inf")

    def trailing_stop_price(self, trailing_pct: float) -> float:
        if self.side == "long":
            return self.highest_price * (1 - trailing_pct)
        return self.lowest_price * (1 + trailing_pct)


@dataclass
class RiskState:
    """Portfolio-level risk tracking."""
    daily_start_equity: float = 0.0
    positions: dict[str, PositionRisk] = field(default_factory=dict)
    trading_halted: bool = False
    halt_reason: str = ""
    order_log: list[dict] = field(default_factory=list)


class RiskManager:
    """Validates orders and enforces risk limits."""

    def __init__(self, config: Optional[RiskConfig] = None) -> None:
        self.config = config or RiskConfig()
        self.state = RiskState()
        self._client = TradingClient(
            ALPACA_API_KEY, ALPACA_API_SECRET,
            paper=("paper" in ALPACA_BASE_URL),
        )

    def update_daily_equity(self, equity: float) -> None:
        """Call at start of each trading day."""
        self.state.daily_start_equity = equity
        self.state.trading_halted = False
        self.state.halt_reason = ""
        logger.info("Daily equity set to $%.2f", equity)

    def check_daily_loss_limit(self, current_equity: float) -> bool:
        """Returns True if still within daily loss limit."""
        if self.state.daily_start_equity <= 0:
            return True
        loss_pct = (self.state.daily_start_equity - current_equity) / self.state.daily_start_equity
        if loss_pct >= self.config.max_portfolio_loss_daily_pct:
            self.state.trading_halted = True
            self.state.halt_reason = f"Daily loss limit breached: {loss_pct:.2%}"
            logger.warning(self.state.halt_reason)
            return False
        return True

    def validate_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        account_equity: float,
        buying_power: float,
    ) -> tuple[bool, str]:
        """
        Validate an order against all risk rules.

        Returns:
            (is_valid, reason)
        """
        # Check if trading is halted
        if self.state.trading_halted:
            reason = f"Trading halted: {self.state.halt_reason}"
            self._log_validation(symbol, side, quantity, False, reason)
            return False, reason

        # Check quantity
        if quantity <= 0:
            reason = "Quantity must be > 0"
            self._log_validation(symbol, side, quantity, False, reason)
            return False, reason

        # Check position size limit
        position_value = quantity * price
        max_position_value = account_equity * self.config.max_position_pct
        if position_value > max_position_value:
            reason = (
                f"Position ${position_value:.2f} exceeds {self.config.max_position_pct:.0%} "
                f"limit (${max_position_value:.2f})"
            )
            self._log_validation(symbol, side, quantity, False, reason)
            return False, reason

        # Check buying power
        if position_value > buying_power:
            reason = f"Insufficient buying power: need ${position_value:.2f}, have ${buying_power:.2f}"
            self._log_validation(symbol, side, quantity, False, reason)
            return False, reason

        # Check max open positions
        if symbol not in self.state.positions and len(self.state.positions) >= self.config.max_open_positions:
            reason = f"Max open positions ({self.config.max_open_positions}) reached"
            self._log_validation(symbol, side, quantity, False, reason)
            return False, reason

        # Check duplicate order
        if symbol in self.state.positions:
            existing = self.state.positions[symbol]
            if existing.side == ("long" if side == "buy" else "short"):
                reason = f"Duplicate order: already {existing.side} {symbol}"
                self._log_validation(symbol, side, quantity, False, reason)
                return False, reason

        # Check portfolio exposure
        total_exposure = sum(
            p.quantity * p.entry_price for p in self.state.positions.values()
        )
        new_exposure = (total_exposure + position_value) / account_equity if account_equity > 0 else 0
        if new_exposure > self.config.max_portfolio_exposure:
            reason = f"Portfolio exposure {new_exposure:.0%} would exceed {self.config.max_portfolio_exposure:.0%}"
            self._log_validation(symbol, side, quantity, False, reason)
            return False, reason

        self._log_validation(symbol, side, quantity, True, "Passed all checks")
        return True, "Passed all checks"

    def validate_symbol(self, symbol: str) -> tuple[bool, str]:
        """Check if a symbol exists and is tradeable."""
        try:
            asset = self._client.get_asset(symbol)
            if asset.status != AssetStatus.ACTIVE:
                return False, f"{symbol} is not active (status: {asset.status})"
            if not asset.tradable:
                return False, f"{symbol} is not tradable"
            return True, "Symbol is valid and tradable"
        except Exception as e:
            return False, f"Symbol validation failed: {e}"

    def calculate_position_size(
        self,
        account_equity: float,
        price: float,
        signal_strength: float = 1.0,
    ) -> int:
        """
        Calculate position size based on risk config and signal strength.

        Args:
            account_equity: Total portfolio value
            price: Current price of the asset
            signal_strength: 0.0 to 1.0 scaling factor

        Returns:
            Number of shares to buy (integer)
        """
        signal_strength = max(0.0, min(1.0, signal_strength))
        max_value = account_equity * self.config.max_position_pct * signal_strength
        if price <= 0:
            return 0
        shares = int(max_value / price)
        return max(shares, 0)

    def calculate_stop_loss(self, entry_price: float, side: str) -> float:
        """Calculate stop-loss price for a position."""
        if side == "long":
            return entry_price * (1 - self.config.default_stop_loss_pct)
        return entry_price * (1 + self.config.default_stop_loss_pct)

    def calculate_take_profit(self, entry_price: float, side: str) -> float:
        """Calculate take-profit price for a position."""
        if side == "long":
            return entry_price * (1 + self.config.default_take_profit_pct)
        return entry_price * (1 - self.config.default_take_profit_pct)

    def register_position(
        self, symbol: str, entry_price: float, quantity: float, side: str
    ) -> None:
        """Register a new position for tracking."""
        self.state.positions[symbol] = PositionRisk(
            symbol=symbol,
            entry_price=entry_price,
            quantity=quantity,
            side=side,
            stop_loss=self.calculate_stop_loss(entry_price, side),
            take_profit=self.calculate_take_profit(entry_price, side),
            highest_price=entry_price,
            lowest_price=entry_price,
        )
        logger.info(
            "Registered %s position: %s x%.0f @ $%.2f | SL=$%.2f TP=$%.2f",
            side, symbol, quantity, entry_price,
            self.state.positions[symbol].stop_loss,
            self.state.positions[symbol].take_profit,
        )

    def update_price(self, symbol: str, current_price: float) -> Optional[str]:
        """
        Update price tracking for a position. Returns action if stop/target hit.

        Returns:
            "stop_loss", "take_profit", "trailing_stop", or None
        """
        if symbol not in self.state.positions:
            return None

        pos = self.state.positions[symbol]
        pos.highest_price = max(pos.highest_price, current_price)
        pos.lowest_price = min(pos.lowest_price, current_price)

        if pos.side == "long":
            if current_price <= pos.stop_loss:
                logger.warning("STOP LOSS triggered for %s at $%.2f", symbol, current_price)
                return "stop_loss"
            if current_price >= pos.take_profit:
                logger.info("TAKE PROFIT triggered for %s at $%.2f", symbol, current_price)
                return "take_profit"
            trailing = pos.trailing_stop_price(self.config.trailing_stop_pct)
            if current_price <= trailing and pos.highest_price > pos.entry_price:
                logger.info("TRAILING STOP triggered for %s at $%.2f", symbol, current_price)
                return "trailing_stop"
        else:
            if current_price >= pos.stop_loss:
                logger.warning("STOP LOSS triggered for %s at $%.2f", symbol, current_price)
                return "stop_loss"
            if current_price <= pos.take_profit:
                logger.info("TAKE PROFIT triggered for %s at $%.2f", symbol, current_price)
                return "take_profit"
            trailing = pos.trailing_stop_price(self.config.trailing_stop_pct)
            if current_price >= trailing and pos.lowest_price < pos.entry_price:
                logger.info("TRAILING STOP triggered for %s at $%.2f", symbol, current_price)
                return "trailing_stop"

        return None

    def close_position(self, symbol: str) -> None:
        """Remove a position from tracking."""
        if symbol in self.state.positions:
            del self.state.positions[symbol]
            logger.info("Closed position tracking for %s", symbol)

    def _log_validation(
        self, symbol: str, side: str, quantity: float, passed: bool, reason: str
    ) -> None:
        entry = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "passed": passed,
            "reason": reason,
        }
        self.state.order_log.append(entry)
        level = logging.INFO if passed else logging.WARNING
        logger.log(level, "Order validation [%s]: %s %s x%.0f — %s",
                    "PASS" if passed else "FAIL", side, symbol, quantity, reason)
