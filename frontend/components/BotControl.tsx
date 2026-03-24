"use client";

import { useState } from "react";
import { BotStatus } from "@/lib/api";

const STRATEGIES = [
  "momentum",
  "mean_reversion",
  "trend_following",
  "options_volatility",
  "ma_crossover_confirmed",
];

const TIMEFRAMES = ["1Min", "5Min", "15Min", "1Hour", "1Day"];

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function BotControl({
  bot,
  onUpdate,
}: {
  bot: BotStatus;
  onUpdate: () => void;
}) {
  const [strategy, setStrategy] = useState(bot.strategy);
  const [symbolInput, setSymbolInput] = useState(bot.symbols.join(", "));
  const [timeframe, setTimeframe] = useState(bot.timeframe ?? "1Min");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const hasChanges =
    strategy !== bot.strategy ||
    symbolInput.trim() !== bot.symbols.join(", ") ||
    timeframe !== (bot.timeframe ?? "1Min");

  async function handleSave() {
    setSaving(true);
    setMessage(null);
    try {
      const symbols = symbolInput
        .split(",")
        .map((s: string) => s.trim().toUpperCase())
        .filter(Boolean);

      const res = await fetch(
        `${API_URL}/api/bot/config`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ strategy, symbols, timeframe }),
        }
      );
      const data = await res.json();
      if (data.status === "ok") {
        setMessage("Updated!");
        onUpdate();
      } else {
        setMessage(`Error: ${data.reason}`);
      }
    } catch {
      setMessage("Failed to reach API");
    } finally {
      setSaving(false);
      setTimeout(() => setMessage(null), 3000);
    }
  }

  return (
    <div className="space-y-4">
      {/* Strategy selector */}
      <div>
        <label className="block text-xs text-zinc-500 uppercase tracking-wider mb-1.5">
          Strategy
        </label>
        <select
          value={strategy}
          onChange={(e) => setStrategy(e.target.value)}
          className="w-full rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-100 px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
        >
          {STRATEGIES.map((s) => (
            <option key={s} value={s}>
              {s.replace(/_/g, " ")}
            </option>
          ))}
        </select>
      </div>

      {/* Timeframe selector */}
      <div>
        <label className="block text-xs text-zinc-500 uppercase tracking-wider mb-1.5">
          Timeframe
        </label>
        <select
          value={timeframe}
          onChange={(e) => setTimeframe(e.target.value)}
          className="w-full rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-100 px-3 py-2 text-sm focus:outline-none focus:border-purple-500"
        >
          {TIMEFRAMES.map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      {/* Symbols input */}
      <div>
        <label className="block text-xs text-zinc-500 uppercase tracking-wider mb-1.5">
          Symbols
        </label>
        <input
          type="text"
          value={symbolInput}
          onChange={(e) => setSymbolInput(e.target.value)}
          placeholder="SPY, AAPL, MSFT"
          className="w-full rounded-lg bg-zinc-800 border border-zinc-700 text-zinc-100 px-3 py-2 text-sm font-mono focus:outline-none focus:border-purple-500"
        />
        <p className="text-xs text-zinc-600 mt-1">Comma-separated tickers</p>
      </div>

      {/* Save button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving || !hasChanges}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            hasChanges
              ? "bg-purple-600 hover:bg-purple-500 text-white"
              : "bg-zinc-800 text-zinc-500 cursor-not-allowed"
          }`}
        >
          {saving ? "Saving..." : "Save Changes"}
        </button>
        {message && (
          <span
            className={`text-sm ${
              message.startsWith("Error") || message.startsWith("Failed")
                ? "text-red-400"
                : "text-green-400"
            }`}
          >
            {message}
          </span>
        )}
      </div>
    </div>
  );
}
