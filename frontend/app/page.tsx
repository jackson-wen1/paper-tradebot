"use client";

import useSWR from "swr";
import {
  Account,
  Position,
  PnL,
  PortfolioHistory,
  MarketStatus,
  BotStatus,
  Activity,
} from "@/lib/api";
import { EquityChart } from "@/components/EquityChart";
import { PositionsTable } from "@/components/PositionsTable";
import { ActivityFeed } from "@/components/ActivityFeed";
import { BotControl } from "@/components/BotControl";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const fetcher = (url: string) => fetch(url).then((r) => r.json());

function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(value);
}

function formatPercent(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

function StatCard({
  label,
  value,
  subvalue,
  color,
}: {
  label: string;
  value: string;
  subvalue?: string;
  color?: "green" | "red" | "blue" | "default";
}) {
  const colorClass =
    color === "green"
      ? "text-green-400"
      : color === "red"
      ? "text-red-400"
      : color === "blue"
      ? "text-blue-400"
      : "text-zinc-100";

  return (
    <div className="rounded-xl bg-[#12121a] border border-[#1e1e2e] p-5">
      <p className="text-xs text-zinc-500 uppercase tracking-wider mb-1">
        {label}
      </p>
      <p className={`text-2xl font-semibold ${colorClass}`}>{value}</p>
      {subvalue && <p className="text-sm text-zinc-500 mt-1">{subvalue}</p>}
    </div>
  );
}

function MarketBadge({ status }: { status?: MarketStatus }) {
  if (!status) return null;
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${
        status.is_open
          ? "bg-green-500/10 text-green-400"
          : "bg-red-500/10 text-red-400"
      }`}
    >
      <span
        className={`w-2 h-2 rounded-full ${
          status.is_open ? "bg-green-400 animate-pulse" : "bg-red-400"
        }`}
      />
      {status.is_open ? "Market Open" : "Market Closed"}
    </span>
  );
}

export default function Dashboard() {
  const { data: account } = useSWR<Account>(
    `${API_URL}/api/account`,
    fetcher,
    { refreshInterval: 30000 }
  );
  const { data: positions } = useSWR<Position[]>(
    `${API_URL}/api/positions`,
    fetcher,
    { refreshInterval: 15000 }
  );
  const { data: pnl } = useSWR<PnL>(`${API_URL}/api/pnl`, fetcher, {
    refreshInterval: 30000,
  });
  const { data: history } = useSWR<PortfolioHistory>(
    `${API_URL}/api/history?period=1M&timeframe=1D`,
    fetcher,
    { refreshInterval: 60000 }
  );
  const { data: market } = useSWR<MarketStatus>(
    `${API_URL}/api/market`,
    fetcher,
    { refreshInterval: 60000 }
  );
  const { data: bot, mutate: mutateBot } = useSWR<BotStatus>(`${API_URL}/api/bot`, fetcher, {
    refreshInterval: 30000,
  });
  const { data: activities } = useSWR<Activity[]>(
    `${API_URL}/api/activities?limit=20`,
    fetcher,
    { refreshInterval: 30000 }
  );

  const totalUnrealizedPL =
    positions?.reduce((sum, p) => sum + p.unrealized_pl, 0) ?? 0;

  return (
    <main className="min-h-screen p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            Tradebot Dashboard
          </h1>
          <p className="text-zinc-500 mt-1">
            Strategy:{" "}
            <span className="text-purple-400 font-medium">
              {bot?.strategy ?? "—"}
            </span>
            {bot?.running && (
              <span className="ml-3 text-green-400">● Running</span>
            )}
          </p>
        </div>
        <MarketBadge status={market} />
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          label="Portfolio Value"
          value={account ? formatCurrency(account.equity) : "—"}
          subvalue={account ? `Cash: ${formatCurrency(account.cash)}` : undefined}
        />
        <StatCard
          label="Today's P&L"
          value={pnl ? formatCurrency(pnl.daily_pnl) : "—"}
          subvalue={pnl ? formatPercent(pnl.daily_pnl_pct) : undefined}
          color={pnl ? (pnl.daily_pnl >= 0 ? "green" : "red") : "default"}
        />
        <StatCard
          label="Unrealized P&L"
          value={formatCurrency(totalUnrealizedPL)}
          subvalue={`${positions?.length ?? 0} positions open`}
          color={totalUnrealizedPL >= 0 ? "green" : "red"}
        />
        <StatCard
          label="Buying Power"
          value={account ? formatCurrency(account.buying_power) : "—"}
          subvalue={
            account
              ? `Long: ${formatCurrency(account.long_market_value)}`
              : undefined
          }
          color="blue"
        />
      </div>

      {/* Equity Chart */}
      <div className="rounded-xl bg-[#12121a] border border-[#1e1e2e] p-5 mb-8">
        <h2 className="text-lg font-semibold mb-4">Equity Curve</h2>
        {history ? (
          <EquityChart history={history} />
        ) : (
          <div className="h-64 flex items-center justify-center text-zinc-500">
            Loading chart...
          </div>
        )}
      </div>

      {/* Positions & Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <div className="rounded-xl bg-[#12121a] border border-[#1e1e2e] p-5">
            <h2 className="text-lg font-semibold mb-4">Open Positions</h2>
            <PositionsTable positions={positions ?? []} />
          </div>
        </div>
        <div>
          <div className="rounded-xl bg-[#12121a] border border-[#1e1e2e] p-5">
            <h2 className="text-lg font-semibold mb-4">Recent Activity</h2>
            <ActivityFeed activities={activities ?? []} />
          </div>
        </div>
      </div>

      {/* Bot Control */}
      {bot && (
        <div className="mt-8 rounded-xl bg-[#12121a] border border-[#1e1e2e] p-5">
          <h2 className="text-lg font-semibold mb-4">Bot Configuration</h2>
          <BotControl bot={bot} onUpdate={() => mutateBot()} />
        </div>
      )}
    </main>
  );
}
