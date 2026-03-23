const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchAPI<T>(endpoint: string): Promise<T> {
  const res = await fetch(`${API_URL}${endpoint}`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export interface Account {
  equity: number;
  cash: number;
  buying_power: number;
  portfolio_value: number;
  last_equity: number;
  long_market_value: number;
  short_market_value: number;
  daytrade_count: number;
  currency: string;
}

export interface Position {
  symbol: string;
  qty: number;
  side: string;
  market_value: number;
  cost_basis: number;
  avg_entry_price: number;
  current_price: number;
  unrealized_pl: number;
  unrealized_plpc: number;
  change_today: number;
}

export interface PnL {
  equity: number;
  last_equity: number;
  daily_pnl: number;
  daily_pnl_pct: number;
}

export interface PortfolioHistory {
  timestamps: string[];
  equity: number[];
  profit_loss: number[];
  profit_loss_pct: number[];
  base_value: number;
}

export interface MarketStatus {
  is_open: boolean;
  next_open: string;
  next_close: string;
}

export interface BotStatus {
  strategy: string;
  symbols: string[];
  timeframe: string;
  running: boolean;
  started_at: string | null;
}

export interface Activity {
  id: string;
  activity_type: string;
  symbol?: string;
  side?: string;
  qty?: number;
  price?: number;
  transaction_time?: string;
}
