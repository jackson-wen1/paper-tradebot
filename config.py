import os
from dotenv import load_dotenv

load_dotenv()

ALPACA_API_KEY: str = os.environ["ALPACA_API_KEY"]
ALPACA_API_SECRET: str = os.environ["ALPACA_API_SECRET"]
ALPACA_BASE_URL: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# Bot defaults — set these in .env to persist settings across restarts
BOT_STRATEGY: str = os.getenv("BOT_STRATEGY", "momentum")
BOT_SYMBOLS: list[str] = os.getenv("BOT_SYMBOLS", "SPY,GOOGL,AMZN,NVDA").split(",")
BOT_TIMEFRAME: str = os.getenv("BOT_TIMEFRAME", "1Min")
BOT_INTERVAL: int = int(os.getenv("BOT_INTERVAL", "60"))
