import type { Context } from "hono";

const DB_URL = process.env.DATABASE_URL || "";

async function queryDB(sql: string, params: any[] = []) {
  const { neon } = await import("@neondatabase/serverless");
  const sqlFn = neon(DB_URL);
  return await sqlFn(sql, params);
}

function loadJSON(filepath: string): any {
  try {
    const { readFileSync, existsSync } = require("fs") as typeof import("fs");
    const { join } = require("path") as typeof import("path");
    const f = join(process.cwd(), filepath);
    if (!existsSync(f)) return filepath.includes("signal") ? [] : {};
    return JSON.parse(readFileSync(f, "utf-8"));
  } catch { return filepath.includes("signal") ? [] : {}; }
}

export default async (c: Context) => {
  if (c.req.path === "/api/signals") {
    let signals: any[] = [];
    if (DB_URL) {
      try {
        const rows: any[] = await queryDB(
          "SELECT symbol, signal_type, confidence, entry_price, status, pnl_pct, created_at, expiry_time FROM signal_history ORDER BY created_at DESC LIMIT 100"
        );
        signals = rows;
      } catch (e) { console.log("DB fallback:", e); }
    }
    if (!signals.length) signals = loadJSON("signal_history.json");

    const closed = signals.filter((s: any) => s.status === "won" || s.status === "lost");
    const won = signals.filter((s: any) => s.status === "won");
    const lost = signals.filter((s: any) => s.status === "lost");
    const winRate = closed.length ? (won.length / closed.length) * 100 : 0;
    const avgWin = won.length ? won.reduce((a: number, s: any) => a + (s.pnl_pct || 0), 0) / won.length : 0;
    const avgLoss = lost.length ? lost.reduce((a: number, s: any) => a + (s.pnl_pct || 0), 0) / lost.length : 0;
    const totalReturn = closed.reduce((a: number, s: any) => a + (s.pnl_pct || 0), 0);
    const sorted = [...closed].sort((a: any, b: any) => (b.pnl_pct || 0) - (a.pnl_pct || 0));

    return c.json({
      stats: {
        total: signals.length,
        active: signals.filter((s: any) => s.status === "active").length,
        closed: closed.length,
        won: won.length,
        lost: lost.length,
        win_rate: winRate,
        avg_win: avgWin,
        avg_loss: avgLoss,
        total_return: totalReturn,
        best_signal: sorted[0] || null,
        worst_signal: sorted[sorted.length - 1] || null
      },
      signals: signals.slice(0, 50)
    });
  }

  return c.json({ error: "Not found" }, 404);
};
