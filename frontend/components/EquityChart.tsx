"use client";

import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";
import { PortfolioHistory } from "@/lib/api";

interface Props {
  history: PortfolioHistory;
}

export function EquityChart({ history }: Props) {
  const data = history.timestamps.map((ts, i) => ({
    date: new Date(ts).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    }),
    equity: history.equity[i],
    pnl: history.profit_loss[i],
  }));

  if (data.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center text-zinc-500">
        No history data available
      </div>
    );
  }

  const minEquity = Math.min(...data.map((d) => d.equity)) * 0.998;
  const maxEquity = Math.max(...data.map((d) => d.equity)) * 1.002;

  const isUp = data.length >= 2 && data[data.length - 1].equity >= data[0].equity;
  const color = isUp ? "#22c55e" : "#ef4444";

  return (
    <ResponsiveContainer width="100%" height={280}>
      <AreaChart data={data} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
        <defs>
          <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor={color} stopOpacity={0.3} />
            <stop offset="95%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e1e2e" />
        <XAxis
          dataKey="date"
          tick={{ fill: "#71717a", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
        />
        <YAxis
          domain={[minEquity, maxEquity]}
          tick={{ fill: "#71717a", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={(v: number) =>
            `$${(v / 1000).toFixed(1)}k`
          }
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#12121a",
            border: "1px solid #1e1e2e",
            borderRadius: "8px",
            color: "#e4e4e7",
          }}
          formatter={(value: number) => [
            `$${value.toLocaleString("en-US", { minimumFractionDigits: 2 })}`,
            "Equity",
          ]}
        />
        <Area
          type="monotone"
          dataKey="equity"
          stroke={color}
          strokeWidth={2}
          fill="url(#equityGrad)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
