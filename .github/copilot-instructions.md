# Tradebot — Copilot Instructions

## Project Overview
This is an algorithmic trading bot built in Python using the Alpaca API. The primary environment is **paper trading** for strategy development and testing before any live deployment.

## Tech Stack
- **Language:** Python 3.x
- **Broker API:** Alpaca (`alpaca-py` SDK preferred, `alpaca-trade-api` also acceptable)
- **Data:** Alpaca Market Data API (historical + real-time WebSocket streams)
- **Testing:** pytest
- **Environment:** Windows, VS Code, virtual environment (`.venv`)

## Code Conventions
- Use environment variables (or a `.env` file with `python-dotenv`) for API keys — **never hardcode credentials**
- Use type hints on all function signatures
- Prefer `async`/`await` patterns for WebSocket streams and concurrent data fetches
- Keep strategy logic decoupled from order execution logic
- Each strategy module should expose: `generate_signals()`, `backtest()`, and `execute()` functions

## Trading Rules
- Always validate orders before submission: check symbol existence, quantity > 0, sufficient buying power
- Enforce position sizing via the risk management module — no single position should exceed a configurable % of portfolio
- All strategies must have a corresponding backtest before paper trading
- Log every order submission, fill, and rejection with timestamps
- Handle market hours, halted symbols, and API rate limits gracefully

## Paper Trading
- Base URL: `https://paper-api.alpaca.markets`
- Test all strategies in paper mode first; never bypass paper testing
- Track and compare paper results against backtest expectations

## File Structure (target)
```
tradebot/
├── .github/
│   ├── copilot-instructions.md
│   └── prompts/           # Copilot agent prompt files
├── strategies/            # Strategy modules (momentum, mean_reversion, etc.)
├── infrastructure/        # Data pipeline, risk management, order execution
├── tests/                 # pytest test files
├── config.py              # Configuration and env var loading
├── main.py                # Entry point
├── README.md              # Project documentation and usage guide
└── requirements.txt
```

## Documentation
- Keep `README.md` up to date whenever new modules, strategies, or infrastructure are added
- The README should document: setup instructions, project structure, available strategies, data pipeline usage, and how to run backtests and paper trading
