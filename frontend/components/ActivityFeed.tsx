"use client";

import { Activity } from "@/lib/api";

interface Props {
  activities: Activity[];
}

export function ActivityFeed({ activities }: Props) {
  if (activities.length === 0) {
    return (
      <p className="text-zinc-500 text-sm py-4 text-center">
        No recent activity
      </p>
    );
  }

  return (
    <div className="space-y-3 max-h-96 overflow-y-auto">
      {activities.map((a) => {
        const isBuy = a.side === "buy";
        const sideColor = isBuy ? "text-green-400" : "text-red-400";
        const sideBg = isBuy ? "bg-green-500/10" : "bg-red-500/10";
        const time = a.transaction_time
          ? new Date(a.transaction_time).toLocaleString("en-US", {
              month: "short",
              day: "numeric",
              hour: "numeric",
              minute: "2-digit",
            })
          : "—";

        return (
          <div
            key={a.id}
            className="flex items-center gap-3 p-3 rounded-lg bg-[#0a0a0f] border border-[#1e1e2e]/50"
          >
            <span
              className={`px-2 py-0.5 rounded text-xs font-medium uppercase ${sideColor} ${sideBg}`}
            >
              {a.side ?? a.activity_type}
            </span>
            <div className="flex-1 min-w-0">
              <p className="font-mono font-medium text-sm">
                {a.symbol ?? "—"}
              </p>
              <p className="text-xs text-zinc-500">
                {a.qty ? `${a.qty} shares` : ""}
                {a.price ? ` @ $${a.price.toFixed(2)}` : ""}
              </p>
            </div>
            <span className="text-xs text-zinc-500 whitespace-nowrap">
              {time}
            </span>
          </div>
        );
      })}
    </div>
  );
}
