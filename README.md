# Tradebot — Algorithmic Trading Bot

An algorithmic trading bot built in Python using the Alpaca API. Features multiple trading strategies, a backtesting engine, risk management, and a real-time dashboard deployable on Vercel.

## Features

- **4 Trading Strategies** — Momentum, Mean Reversion, Trend Following, Options/Volatility
- **Backtesting Engine** — Test strategies against historical data with realistic slippage and commissions
- **Risk Management** — Position sizing, stop-losses, trailing stops, daily loss limits, portfolio exposure controls
- **Paper Trading** — Safe testing via Alpaca's paper trading environment
- **Real-time Dashboard** — Next.js frontend showing portfolio value, P&L, positions, and equity curves
- **FastAPI Backend** — REST API for the dashboard and external integrations
- **Deployable** — Dockerfile for the bot/API, Vercel-ready frontend

## Project Structure

```
tradebot/
├── main.py                       # CLI entry point (trade, backtest, status)
├── api.py                        # FastAPI server for the dashboard
├── config.py                     # Environment variable loading
├── requirements.txt
├── Dockerfile                    # Container for bot + API deployment
│
├── infrastructure/
│   ├── data_pipeline.py          # Historical/real-time data fetching from Alpaca
│   ├── risk_management.py        # Position sizing, stop-loss, order validation
│   ├── order_execution.py        # Order submission (market, limit, stop, bracket)
│   ├── account_monitor.py        # Account health, positions, P&L, portfolio history
│   ├── backtesting.py            # Backtesting engine with performance metrics
│   ├── stream.py                 # Real-time market data WebSocket stream
│   └── trade_stream.py           # Trade/order update WebSocket stream
│
├── strategies/
│   ├── momentum.py               # MACD, RSI, Rate of Change
│   ├── mean_reversion.py         # Bollinger Bands, Z-score, RSI extremes
│   ├── trend_following.py        # MA crossovers, ADX, Donchian, Supertrend
│   └── options_volatility.py     # IV rank, HV analysis, vol regime detection
│
├── tests/
│   └── test_strategies.py        # pytest tests for strategies and risk management
│
├── frontend/                     # Next.js dashboard (deploy to Vercel)
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx              # Main dashboard page
│   │   └── globals.css
│   ├── components/
│   │   ├── EquityChart.tsx       # Portfolio equity curve chart
│   │   ├── PositionsTable.tsx    # Open positions table
│   │   └── ActivityFeed.tsx      # Recent trade activity feed
│   ├── lib/
│   │   └── api.ts                # API client and TypeScript types
│   ├── package.json
│   ├── tailwind.config.js
│   └── .env.example
│
└── .github/
    ├── copilot-instructions.md
    └── prompts/                  # Copilot agent prompt files
```

## Quick Start

### 1. Prerequisites

- Python 3.11+
- Node.js 18+ (for the dashboard)
- An [Alpaca](https://alpaca.markets/) account (free paper trading)

### 2. Clone and Set Up Python Environment

```bash
git clone <your-repo-url>
cd tradebot
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the project root:

```env
ALPACA_API_KEY=your_api_key_here
ALPACA_API_SECRET=your_api_secret_here
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# For the API server
CORS_ORIGINS=http://localhost:3000
BOT_STRATEGY=momentum
BOT_SYMBOLS=SPY,GOOGL,AMZN,NVDA
```

Get your API keys from [Alpaca Dashboard](https://app.alpaca.markets/paper/dashboard/overview) → Paper Trading → API Keys.

### 4. Check Account Status

```bash
python main.py status
```

## Usage

### Run a Backtest

Test a strategy against historical data before paper trading:

```bash
# Backtest momentum strategy on SPY
python main.py backtest --strategy momentum --symbol SPY --start 2023-01-01 --end 2025-01-01

# Backtest mean reversion on AAPL
python main.py backtest --strategy mean_reversion --symbol AAPL --start 2023-06-01 --end 2024-12-01

# Backtest trend following
python main.py backtest --strategy trend_following --symbol MSFT --start 2023-01-01 --end 2025-01-01

# Backtest volatility strategy  
python main.py backtest --strategy options_volatility --symbol SPY --start 2023-01-01 --end 2025-01-01
```

Backtest output includes: total return, Sharpe ratio, Sortino ratio, max drawdown, win rate, profit factor, and more.

### Start Paper Trading

```bash
# Trade with momentum strategy on default symbols
python main.py trade --strategy momentum

# Trade specific symbols with a different strategy
python main.py trade --strategy trend_following --symbols SPY QQQ AAPL MSFT

# Adjust the trading loop interval (seconds)
python main.py trade --strategy mean_reversion --interval 120
```

Press `Ctrl+C` to gracefully shut down.

### Start the API Server

The API server provides data to the frontend dashboard:

```bash
uvicorn api:app --reload --port 8000
```

API endpoints:

| Endpoint | Description |
|---|---|
| `GET /api/health` | Health check |
| `GET /api/account` | Account summary (equity, cash, buying power) |
| `GET /api/positions` | Open positions with P&L |
| `GET /api/pnl` | Today's profit/loss |
| `GET /api/history?period=1M&timeframe=1D` | Portfolio equity history |
| `GET /api/orders` | Open orders |
| `GET /api/activities?limit=50` | Recent trade fills |
| `GET /api/market` | Market open/closed status |
| `GET /api/bot` | Bot status (strategy, symbols) |

### Run the Dashboard (Local)

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). The dashboard shows:
- Portfolio value and cash
- Today's P&L
- Unrealized P&L across positions
- Equity curve chart
- Open positions table
- Recent trade activity
- Active strategy and watched symbols

## Strategies

### Momentum (`momentum`)
Uses MACD crossovers, RSI overbought/oversold, and Rate of Change breakouts. Volume confirmation filters out weak signals. Best for trending markets.

### Mean Reversion (`mean_reversion`)
Uses Bollinger Bands, Z-score of price relative to rolling mean, and RSI extremes. Buys when price is significantly below the mean, sells when above. Includes stationarity validation.

### Trend Following (`trend_following`)
Uses 50/200 EMA crossovers (golden/death cross), ADX for trend strength filtering, Donchian channel breakouts, and Supertrend indicator. Only trades when ADX confirms a strong trend.

### Options Volatility (`options_volatility`)
Analyzes historical volatility, IV rank/percentile (using HV as proxy), and volatility regime detection. Sells premium when IV rank is high, buys when low. Reduces position size in high-vol regimes.

## Risk Management

All orders pass through the risk manager before execution:

- **Position sizing**: Max 5% of portfolio per position (configurable)
- **Stop-loss**: 2% default, trailing stop at 1.5%
- **Take-profit**: 4% default (2:1 reward:risk)
- **Daily loss limit**: Halts trading at 3% daily portfolio loss
- **Max positions**: 20 concurrent positions
- **Portfolio exposure**: 100% max (no leverage)
- **Order validation**: checks symbol tradability, buying power, duplicate orders

## Running Tests

```bash
pytest tests/ -v
```

Tests cover:
- Backtesting engine (basic run, no signals, metrics, slippage)
- Signal generation for all 4 strategies
- Risk management (validation, position sizing, stop-loss, daily loss halt)

## Deployment

### Option 1: All on Vercel (Free) — Recommended

Deploy **everything for free** on Vercel: the dashboard frontend + a Vercel Cron Job that triggers the bot on a schedule. You only need a separate free-tier host for the Python API (Render free tier works).

**Step 1 — Deploy the Python API on Render (free)**:
1. Push your repo to GitHub
2. Go to [Render](https://render.com) → New Web Service → Connect your repo
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**: `uvicorn api:app --host 0.0.0.0 --port $PORT`
5. Add environment variables: `ALPACA_API_KEY`, `ALPACA_API_SECRET`, `ALPACA_BASE_URL`, `CORS_ORIGINS` (your Vercel URL)
6. Choose the **Free** plan. The service sleeps after 15 min of inactivity but wakes on request.

**Step 2 — Deploy the Dashboard + Cron on Vercel (free)**:
1. Go to [Vercel](https://vercel.com) → New Project → Import your repo
2. Set **Root Directory** to `frontend`
3. Add environment variables:
   - `NEXT_PUBLIC_API_URL` = your Render URL (e.g., `https://tradebot-api.onrender.com`)
   - `PYTHON_API_URL` = same Render URL
   - `CRON_SECRET` = any random secret string (for cron auth)
4. Deploy

The `vercel.json` cron schedule (`* 9-16 * * 1-5`) runs the bot every minute, Mon–Fri, 9 AM – 4 PM ET (market hours). Vercel's free Hobby plan includes 1 cron job.

> **Note:** Render's free tier sleeps after inactivity. The Vercel cron wakes it up every minute during market hours, keeping it active when it matters. It sleeps on nights/weekends, which is fine since markets are closed.

### Option 2: Docker (Self-Hosted or Any Cloud)

The included `Dockerfile` runs the FastAPI server:

```bash
# Build and run locally
docker build -t tradebot .
docker run -p 8000:8000 --env-file .env tradebot
```

### Option 3: Oracle Cloud Free Tier (Always-On)

Oracle Cloud offers an **always-free** VM (1 CPU, 1 GB RAM) that can run both the bot and API 24/7:

1. Create a free Oracle Cloud account
2. Spin up an Always Free Compute instance (Ubuntu)
3. SSH in, clone your repo, install Python, set up a systemd service
4. This gives you a persistent server at zero cost

### Option 4: Run Locally

Just run both the API and bot on your own machine:

```bash
# Terminal 1: API server
uvicorn api:app --reload --port 8000

# Terminal 2: Trading bot
python main.py trade --strategy momentum

# Terminal 3: Frontend
cd frontend && npm run dev
```

### Deploy the Dashboard Only (Vercel)

If you only want the monitoring dashboard and run the bot locally:

1. Go to [Vercel](https://vercel.com) → New Project → Import your repo
2. Set **Root Directory** to `frontend`
3. Add env var: `NEXT_PUBLIC_API_URL` = your API URL
4. Deploy

The dashboard auto-refreshes data every 15–60 seconds.

## Available Strategies (CLI)

| Strategy | Flag | Indicators |
|---|---|---|
| Momentum | `--strategy momentum` | MACD, RSI, ROC, Volume |
| Mean Reversion | `--strategy mean_reversion` | Bollinger Bands, Z-score, RSI |
| Trend Following | `--strategy trend_following` | EMA crossover, ADX, Donchian, Supertrend |
| Options Volatility | `--strategy options_volatility` | HV, IV Rank, Vol Regime |

## Architecture

```
┌────────────────┐     ┌────────────────────────┐     ┌──────────────────────┐
│   Alpaca API   │◄────│  Python API (Render)    │────►│  Vercel (Frontend)   │
│  (Paper/Live)  │     │  FastAPI + /cron/tick   │     │  Next.js Dashboard   │
└────────────────┘     └────────────────────────┘     │  + Vercel Cron Job   │
                              │                        └──────────────────────┘
                    ┌─────────┼─────────┐                       │
                    │         │         │              Cron calls /api/cron/tick
              ┌─────▼───┐ ┌──▼──┐ ┌───▼────┐          every minute Mon-Fri
              │Strategies│ │Risk │ │Backtest│          during market hours
              │ Module   │ │Mgmt │ │Engine  │
              └─────────┘ └─────┘ └────────┘
```

**Cost: $0** — Render free tier + Vercel Hobby plan (both free).
