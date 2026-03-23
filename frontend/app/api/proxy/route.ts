import { NextResponse } from "next/server";

const PYTHON_API = process.env.PYTHON_API_URL || "http://localhost:8000";

async function proxyGet(endpoint: string) {
  const res = await fetch(`${PYTHON_API}${endpoint}`, {
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
  });
  const data = await res.json();
  return NextResponse.json(data);
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const endpoint = searchParams.get("endpoint") || "/api/health";
  const allowed = [
    "/api/health",
    "/api/account",
    "/api/positions",
    "/api/pnl",
    "/api/orders",
    "/api/market",
    "/api/bot",
  ];

  // Endpoints with query params
  if (endpoint.startsWith("/api/history") || endpoint.startsWith("/api/activities")) {
    return proxyGet(endpoint);
  }

  if (!allowed.includes(endpoint)) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  return proxyGet(endpoint);
}

export async function POST(request: Request) {
  const { searchParams } = new URL(request.url);
  const endpoint = searchParams.get("endpoint") || "";
  const allowedPost = ["/api/bot/config"];

  if (!allowedPost.includes(endpoint)) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  const body = await request.json();
  const res = await fetch(`${PYTHON_API}${endpoint}`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return NextResponse.json(data);
}
