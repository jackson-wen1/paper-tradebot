import { NextResponse } from "next/server";

/**
 * Vercel Cron Job endpoint — triggers one tick of the trading bot.
 * 
 * Configure in vercel.json to run every minute during market hours.
 * The Python API does the actual trading logic via /api/cron/tick.
 */
export async function GET(request: Request) {
  // Verify the request is from Vercel Cron (not a random visitor)
  const authHeader = request.headers.get("authorization");
  const cronSecret = process.env.CRON_SECRET;

  if (cronSecret && authHeader !== `Bearer ${cronSecret}`) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const pythonApi = process.env.PYTHON_API_URL || "http://localhost:8000";

  try {
    const res = await fetch(`${pythonApi}/api/cron/tick`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
    });
    const data = await res.json();
    return NextResponse.json(data);
  } catch (error) {
    return NextResponse.json(
      { error: "Failed to reach trading API", detail: String(error) },
      { status: 502 }
    );
  }
}
