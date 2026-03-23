"""
Tradebot — Main entry point.

Runs the trading bot: fetches data, generates signals, executes trades,
and monitors the portfolio. Supports multiple strategies and paper trading.
"""

import asyncio
import argparse
import logging
import signal
import sys
from datetime import datetime, timezone

from config import ALPACA_BASE_URL
from infrastructure.account_monitor import get_account, get_positions, is_market_open
from infrastructure.data_pipeline import get_historical_bars
from infrastructure.risk_management import RiskManager, RiskConfig
from infrastructure.order_execution import cancel_all_orders

from strategies import momentum, mean_reversion, trend_following, options_volatility

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("tradebot.log"),
    ],
)
logger = logging.getLogger(__name__)

STRATEGY_MAP = {
    "momentum": momentum,
    "mean_reversion": mean_reversion,
    "trend_following": trend_following,
    "options_volatility": options_volatility,
}

DEFAULT_SYMBOLS = ["SPY", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(
        self,
        strategy_name: str = "momentum",
        symbols: list[str] | None = None,
        risk_config: RiskConfig | None = None,
        interval_seconds: int = 60,
    ) -> None:
        if strategy_name not in STRATEGY_MAP:
            raise ValueError(f"Unknown strategy: {strategy_name}. Choose from: {list(STRATEGY_MAP.keys())}")

        self.strategy_name = strategy_name
        self.strategy = STRATEGY_MAP[strategy_name]
        self.symbols = symbols or DEFAULT_SYMBOLS
        self.risk_manager = RiskManager(risk_config)
        self.interval = interval_seconds
        self._running = False

    async def run(self) -> None:
        """Main trading loop."""
        self._running = True
        logger.info("=" * 60)
        logger.info("Tradebot starting — Strategy: %s", self.strategy_name)
        logger.info("Symbols: %s", self.symbols)
        logger.info("Base URL: %s", ALPACA_BASE_URL)
        logger.info("=" * 60)

        # Check account
        account = get_account()
        logger.info("Account equity: $%.2f | Buying power: $%.2f",
                     account["equity"], account["buying_power"])

        # Set daily equity for risk management
        self.risk_manager.update_daily_equity(account["equity"])

        while self._running:
            try:
                await self._tick()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error("Error in trading loop: %s", e, exc_info=True)

            if self._running:
                await asyncio.sleep(self.interval)

        logger.info("Trading bot stopped")

    async def _tick(self) -> None:
        """Single iteration of the trading loop."""
        # Check market hours
        clock = is_market_open()
        if not clock["is_open"]:
            logger.debug("Market is closed. Next open: %s", clock["next_open"])
            return

        # Refresh account
        account = get_account()
        equity = account["equity"]
        buying_power = account["buying_power"]

        # Check daily loss limit
        if not self.risk_manager.check_daily_loss_limit(equity):
            logger.warning("Daily loss limit breached — halting trading")
            return

        # Check risk triggers for existing positions
        positions = get_positions()
        for pos in positions:
            action = self.risk_manager.update_price(pos["symbol"], pos["current_price"])
            if action in ("stop_loss", "take_profit", "trailing_stop"):
                from infrastructure.order_execution import submit_market_order
                qty = abs(pos["qty"])
                side = "sell" if pos["qty"] > 0 else "buy"
                submit_market_order(pos["symbol"], side, qty)
                self.risk_manager.close_position(pos["symbol"])
                logger.info("Risk exit [%s] for %s: %.0f shares", action, pos["symbol"], qty)

        # Generate signals and execute for each symbol
        for symbol in self.symbols:
            try:
                data = get_historical_bars(symbol, "1Day", limit=200)
                if data.empty or len(data) < 50:
                    continue

                self.strategy.execute(
                    symbol=symbol,
                    risk_manager=self.risk_manager,
                    account_equity=equity,
                    buying_power=buying_power,
                    data=data,
                )
            except Exception as e:
                logger.error("Error processing %s: %s", symbol, e)

    def stop(self) -> None:
        """Gracefully stop the bot."""
        self._running = False
        logger.info("Stop signal received — shutting down...")


def run_backtest(strategy_name: str, symbol: str, start: str, end: str) -> None:
    """Run a backtest for the specified strategy."""
    if strategy_name not in STRATEGY_MAP:
        print(f"Unknown strategy: {strategy_name}")
        sys.exit(1)

    strategy = STRATEGY_MAP[strategy_name]
    result = strategy.backtest(symbol=symbol, start=start, end=end)

    from infrastructure.backtesting import format_backtest_report
    print(format_backtest_report(result))


def main() -> None:
    parser = argparse.ArgumentParser(description="Tradebot — Algorithmic Trading Bot")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Trade command
    trade_parser = subparsers.add_parser("trade", help="Start paper trading")
    trade_parser.add_argument("--strategy", default="momentum",
                              choices=list(STRATEGY_MAP.keys()),
                              help="Trading strategy to use")
    trade_parser.add_argument("--symbols", nargs="+", default=None,
                              help="Symbols to trade (default: SPY, AAPL, etc.)")
    trade_parser.add_argument("--interval", type=int, default=60,
                              help="Seconds between trading loop iterations")

    # Backtest command
    bt_parser = subparsers.add_parser("backtest", help="Run a backtest")
    bt_parser.add_argument("--strategy", default="momentum",
                           choices=list(STRATEGY_MAP.keys()),
                           help="Strategy to backtest")
    bt_parser.add_argument("--symbol", default="SPY", help="Symbol to backtest")
    bt_parser.add_argument("--start", default="2023-01-01", help="Start date (YYYY-MM-DD)")
    bt_parser.add_argument("--end", default="2025-01-01", help="End date (YYYY-MM-DD)")

    # Status command
    subparsers.add_parser("status", help="Show account status and positions")

    args = parser.parse_args()

    if args.command == "trade":
        bot = TradingBot(
            strategy_name=args.strategy,
            symbols=args.symbols,
            interval_seconds=args.interval,
        )

        # Handle graceful shutdown
        def shutdown_handler(sig: int, frame: object) -> None:
            bot.stop()

        signal.signal(signal.SIGINT, shutdown_handler)
        signal.signal(signal.SIGTERM, shutdown_handler)

        asyncio.run(bot.run())

    elif args.command == "backtest":
        run_backtest(args.strategy, args.symbol, args.start, args.end)

    elif args.command == "status":
        account = get_account()
        positions = get_positions()
        clock = is_market_open()

        print("\n" + "=" * 50)
        print("ACCOUNT STATUS")
        print("=" * 50)
        print(f"Equity:        ${account['equity']:>12,.2f}")
        print(f"Cash:          ${account['cash']:>12,.2f}")
        print(f"Buying Power:  ${account['buying_power']:>12,.2f}")
        print(f"Market Open:   {clock['is_open']}")
        print(f"\nPositions ({len(positions)}):")
        for p in positions:
            pnl_sign = "+" if p["unrealized_pl"] >= 0 else ""
            print(f"  {p['symbol']:>6} | {p['qty']:>8.2f} shares | "
                  f"${p['market_value']:>10,.2f} | "
                  f"P&L: {pnl_sign}${p['unrealized_pl']:>8,.2f} ({p['unrealized_plpc']:.2%})")
        print("=" * 50)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
