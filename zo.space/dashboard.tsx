import { useState, useEffect } from "react";

interface Signal {
  symbol: string;
  signal_type: string;
  confidence: number;
  entry_price: number;
  status: string;
  pnl_pct: number | null;
  created_at: number;
  expiry_time: number;
}

interface Stats {
  total: number;
  active: number;
  closed: number;
  won: number;
  lost: number;
  win_rate: number;
  avg_win: number;
  avg_loss: number;
  total_return: number;
  best_signal: Signal | null;
  worst_signal: Signal | null;
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState("");
  const [livePrice, setLivePrice] = useState<number | null>(null);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 30000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    const ws = new WebSocket("wss://wss.ave-api.xyz");
    ws.onopen = () => {
      ws.send(JSON.stringify({ method: "SUBSCRIBE", params: ["token:USDT-BSC"], id: 1 }));
    };
    ws.onmessage = (ev) => {
      try {
        const d = JSON.parse(ev.data);
        if (d.params?.quote?.uprice) setLivePrice(parseFloat(d.params.quote.uprice));
      } catch {}
    };
    return () => ws.close();
  }, []);

  async function fetchData() {
    try {
      const r = await fetch("/api/signals");
      const data = await r.json();
      setStats(data.stats);
      setSignals(data.signals || []);
      setLastUpdate(new Date().toLocaleTimeString());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }

  const statusColor = (s: Signal) => {
    if (s.status === "active") return "text-yellow-400";
    if (s.status === "won") return "text-green-400";
    return "text-red-400";
  };

  const pnlDisplay = (s: Signal) => {
    if (s.status === "active") {
      const rem = Math.max(0, s.expiry_time * 1000 - Date.now());
      const h = Math.floor(rem / 3600000);
      const m = Math.floor((rem % 3600000) / 60000);
      return h > 0 ? `⏳ ${h}h ${m}m` : `⏳ ${m}m`;
    }
    if (s.pnl_pct == null) return "-";
    return `${s.pnl_pct >= 0 ? "+" : ""}${s.pnl_pct.toFixed(2)}%`;
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-white p-6">
      <div className="max-w-5xl mx-auto">
        <div className="flex justify-between items-start mb-8">
          <div>
            <h1 className="text-3xl font-bold text-blue-400">📡 Avegram Signals</h1>
            <p className="text-zinc-400 text-sm mt-1">Signal performance analytics dashboard</p>
          </div>
          <div className="text-right">
            {livePrice && (
              <>
                <div className="text-xs text-zinc-500">USDT Live</div>
                <div className="text-xl font-mono text-green-400">${livePrice.toFixed(6)}</div>
              </>
            )}
            <div className="text-xs text-zinc-600 mt-1">Updated {lastUpdate}</div>
          </div>
        </div>

        {loading ? (
          <div className="flex justify-center py-20 text-4xl">⏳</div>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
              <StatCard label="Total Signals" value={stats?.total ?? 0} emoji="📊" />
              <StatCard label="Active" value={stats?.active ?? 0} emoji="🟡" color="text-yellow-400" />
              <StatCard label="Win Rate" value={`${(stats?.win_rate ?? 0).toFixed(1)}%`} emoji="🎯" color="text-blue-400" />
              <StatCard
                label="Total Return"
                value={`${(stats?.total_return ?? 0) >= 0 ? "+" : ""}${(stats?.total_return ?? 0).toFixed(2)}%`}
                emoji="💰"
                color={(stats?.total_return ?? 0) >= 0 ? "text-green-400" : "text-red-400"}
              />
            </div>

            <div className="grid grid-cols-3 md:grid-cols-6 gap-3 mb-6">
              <MiniStat label="Won" value={`🟢 ${stats?.won ?? 0}`} color="text-green-400" />
              <MiniStat label="Lost" value={`🔴 ${stats?.lost ?? 0}`} color="text-red-400" />
              <MiniStat label="Avg Win" value={`+${(stats?.avg_win ?? 0).toFixed(2)}%`} color="text-green-300" />
              <MiniStat label="Avg Loss" value={`${(stats?.avg_loss ?? 0).toFixed(2)}%`} color="text-red-300" />
              <MiniStat label="Best" value={stats?.best_signal?.symbol ?? "-"} color="text-yellow-400" />
              <MiniStat label="Worst" value={stats?.worst_signal?.symbol ?? "-"} color="text-red-300" />
            </div>

            <div className="bg-zinc-900 rounded-xl overflow-hidden border border-zinc-800">
              <div className="px-6 py-4 border-b border-zinc-800 flex justify-between items-center">
                <h2 className="font-semibold">Recent Signals</h2>
                <button onClick={fetchData} className="text-xs bg-zinc-800 hover:bg-zinc-700 px-3 py-1 rounded transition">🔄 Refresh</button>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-zinc-800/50 text-zinc-400">
                    <tr>
                      <th className="px-4 py-3 text-left">Symbol</th>
                      <th className="px-4 py-3 text-left">Type</th>
                      <th className="px-4 py-3 text-left">Confidence</th>
                      <th className="px-4 py-3 text-left">Entry Price</th>
                      <th className="px-4 py-3 text-left">Status</th>
                      <th className="px-4 py-3 text-right">P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {signals.map((s, i) => (
                      <tr key={i} className="border-t border-zinc-800/50 hover:bg-zinc-800/30">
                        <td className="px-4 py-3 font-medium">{s.symbol}</td>
                        <td className="px-4 py-3">
                          <span className={s.signal_type === "buy" ? "text-green-400" : "text-red-400"}>
                            {s.signal_type.toUpperCase()}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-zinc-400">{s.confidence}%</td>
                        <td className="px-4 py-3 font-mono text-xs">${s.entry_price.toFixed(8)}</td>
                        <td className={`px-4 py-3 font-medium ${statusColor(s)}`}>{s.status.toUpperCase()}</td>
                        <td className={`px-4 py-3 text-right font-mono ${s.pnl_pct != null && s.pnl_pct >= 0 ? "text-green-400" : s.pnl_pct != null ? "text-red-400" : "text-zinc-400"}`}>
                          {pnlDisplay(s)}
                        </td>
                      </tr>
                    ))}
                    {signals.length === 0 && (
                      <tr><td colSpan={6} className="px-4 py-12 text-center text-zinc-600">No signals yet — check back soon</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="mt-6 text-center text-xs text-zinc-600">
              Avegram · Powered by Ave Cloud API · Signals refresh every 30s
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, emoji, color = "text-white" }: { label: string; value: string | number; emoji: string; color?: string }) {
  return (
    <div className="bg-zinc-900 rounded-xl p-5 border border-zinc-800">
      <div className="text-2xl mb-1">{emoji}</div>
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-zinc-400 text-sm mt-0.5">{label}</div>
    </div>
  );
}

function MiniStat({ label, value, color = "text-white" }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="bg-zinc-900 rounded-lg p-3 border border-zinc-800 text-center">
      <div className={`text-sm font-bold ${color}`}>{value}</div>
      <div className="text-zinc-500 text-xs mt-0.5">{label}</div>
    </div>
  );
}
