"use client";

import { Position } from "@/lib/api";

interface Props {
  positions: Position[];
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(value);
}

export function PositionsTable({ positions }: Props) {
  if (positions.length === 0) {
    return (
      <p className="text-zinc-500 text-sm py-4 text-center">
        No open positions
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-zinc-500 text-xs uppercase tracking-wider border-b border-[#1e1e2e]">
            <th className="text-left py-3 pr-4">Symbol</th>
            <th className="text-right py-3 pr-4">Qty</th>
            <th className="text-right py-3 pr-4">Avg Entry</th>
            <th className="text-right py-3 pr-4">Current</th>
            <th className="text-right py-3 pr-4">Market Value</th>
            <th className="text-right py-3 pr-4">P&L</th>
            <th className="text-right py-3">Return</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => {
            const isProfit = p.unrealized_pl >= 0;
            const plColor = isProfit ? "text-green-400" : "text-red-400";

            return (
              <tr
                key={p.symbol}
                className="border-b border-[#1e1e2e]/50 hover:bg-[#1a1a25] transition-colors"
              >
                <td className="py-3 pr-4">
                  <span className="font-mono font-medium">{p.symbol}</span>
                </td>
                <td className="text-right py-3 pr-4 text-zinc-300">
                  {p.qty.toFixed(p.qty % 1 === 0 ? 0 : 2)}
                </td>
                <td className="text-right py-3 pr-4 text-zinc-300">
                  {formatCurrency(p.avg_entry_price)}
                </td>
                <td className="text-right py-3 pr-4 text-zinc-300">
                  {formatCurrency(p.current_price)}
                </td>
                <td className="text-right py-3 pr-4 text-zinc-300">
                  {formatCurrency(p.market_value)}
                </td>
                <td className={`text-right py-3 pr-4 font-medium ${plColor}`}>
                  {isProfit ? "+" : ""}
                  {formatCurrency(p.unrealized_pl)}
                </td>
                <td className={`text-right py-3 font-medium ${plColor}`}>
                  {isProfit ? "+" : ""}
                  {(p.unrealized_plpc * 100).toFixed(2)}%
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
