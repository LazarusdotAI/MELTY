import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Sparkles, Loader2, ArrowRight, Monitor } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg, usd } from "../lib/api";
import { Button } from "../components/ui/button";

function Cover({ name, appid }) {
  const [err, setErr] = useState(false);
  return appid && !err
    ? <img src={`https://cdn.cloudflare.steamstatic.com/steam/apps/${appid}/header.jpg`} alt={name} onError={() => setErr(true)} className="w-full h-full object-cover" />
    : <div className="w-full h-full grid place-items-center bg-gradient-to-br from-slate-800 to-[#0a0b0e] font-display text-xl font-extrabold text-slate-500">{name.slice(0, 2).toUpperCase()}</div>;
}

function PairCard({ p, i, onUse }) {
  const tone = p.score >= 75 ? "from-emerald-400 to-cyan-400" : p.score >= 55 ? "from-cyan-400 to-violet-400" : "from-amber-400 to-rose-400";
  return (
    <div data-testid={`suggestion-${i}`} className="panel p-4 fade-up flex flex-col md:flex-row gap-5 items-stretch" style={{ animationDelay: `${i * 40}ms` }}>
      <div className="font-mono text-2xl text-slate-600 w-8 pt-1">{String(i + 1).padStart(2, "0")}</div>
      <div className="flex gap-2 w-full md:w-[220px] lg:w-[300px] shrink-0">
        <div className="flex-1 rounded-md overflow-hidden border border-cyan-500/40 aspect-[460/215]"><Cover name={p.host.name} appid={p.host.steam_appid} /></div>
        <div className="flex-1 rounded-md overflow-hidden border border-violet-500/40 aspect-[460/215]"><Cover name={p.secondary.name} appid={p.secondary.steam_appid} /></div>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-display font-semibold text-cyan-200 truncate">{p.host.name}</span><span className="text-slate-600">×</span>
          <span className="font-display font-semibold text-violet-200 truncate">{p.secondary.name}</span>
          <span className="text-[10px] px-2 py-0.5 rounded-full border border-slate-700 text-slate-400">{p.secondary.role}</span>
        </div>
        {p.pitch ? (
          <div className="mt-1.5" data-testid={`suggestion-pitch-${i}`}>
            <p className="text-sm"><span className="font-semibold">{p.pitch.title}</span> — <span className="text-slate-300">{p.pitch.idea}</span></p>
            <p className="text-[11px] text-slate-500 mt-1">First step: {p.pitch.first_step}</p>
          </div>
        ) : (
          <ul className="mt-1.5 text-xs text-slate-400 space-y-0.5">{p.reasons.slice(0, 3).map((r) => <li key={r}>· {r}</li>)}</ul>
        )}
      </div>
      <div className="w-full md:w-40 shrink-0 flex flex-col justify-between items-end gap-3">
        <div className="w-full">
          <div className="flex justify-between text-[11px] text-slate-500 mb-1"><span>moddability</span><span data-testid={`suggestion-score-${i}`} className="font-mono text-slate-200">{p.score}</span></div>
          <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden"><div className={`h-full bg-gradient-to-r ${tone}`} style={{ width: `${p.score}%` }} /></div>
        </div>
        <Button data-testid={`use-suggestion-${i}`} size="sm" onClick={() => onUse(p)} className="bg-cyan-500 hover:bg-cyan-400 text-[#08090d]">Use this pair <ArrowRight className="w-3 h-3 ml-1" /></Button>
      </div>
    </div>
  );
}

export default function Ideas() {
  const nav = useNavigate();
  const [device, setDevice] = useState(undefined);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = (d) => api.get("/suggestions", { params: { device_id: d.id } }).then((r) => setData(r.data));
  useEffect(() => {
    api.get("/devices").then((r) => {
      const d = r.data.find((x) => x.online) || r.data[0] || null;
      setDevice(d);
      if (d) load(d);
    });
  }, []);
  const pitch = async () => {
    setBusy(true);
    try {
      const r = await api.post("/suggestions/pitch", { device_id: device.id, keys: data.pairs.slice(0, 6).map((p) => p.key) });
      toast.success(`${r.data.count} ideas from ${r.data.model} · ${usd(r.data.cost)}`);
      load(device);
    } catch (e) { toast.error(errMsg(e)); }
    setBusy(false);
  };
  const use = (p) => {
    const q = new URLSearchParams({ host: p.host.name, sec: p.secondary.name, role: p.secondary.role });
    if (p.pitch) q.set("desc", `${p.pitch.title}: ${p.pitch.idea} Start with: ${p.pitch.first_step}`);
    nav(`/?${q}`);
  };
  return (
    <main className="px-8 py-10 max-w-[1400px] mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-6 mb-8">
        <div>
          <p className="font-mono text-xs text-violet-400 tracking-widest uppercase mb-3">Mashup ideas</p>
          <h1 className="font-display text-4xl sm:text-5xl font-extrabold tracking-tight">Best pairs on your PC</h1>
          <p className="text-sm text-slate-400 mt-3 max-w-2xl">Ranked for free by how moddable the host is (engine, mod loader, adapter, saved notes) and how well the second game's content fits. AI pitches are optional.</p>
        </div>
        {data?.pairs?.length > 0 && (
          <Button data-testid="pitch-button" disabled={busy} onClick={pitch} className="rounded-full bg-gradient-to-r from-cyan-500 to-violet-500 text-[#08090d] font-semibold">
            {busy ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Sparkles className="w-4 h-4 mr-2" />} Pitch the top 6 with AI (~$0.03)
          </Button>
        )}
      </div>
      {device === null && <div data-testid="ideas-no-device" className="panel p-8 text-slate-400 flex items-center gap-3"><Monitor className="w-5 h-5" /> Pair your PC first. <Link to="/companion" className="text-cyan-300">Connect my PC</Link></div>}
      {data && data.pairs.length === 0 && (
        <div data-testid="ideas-empty" className="panel p-8 text-slate-400">
          {data.game_count === 0 ? "No games detected yet. They'll appear after the companion's first scan." : `None of your ${data.game_count} games can be a host right now. Here's why:`}
        </div>
      )}
      {data?.blocked?.length > 0 && (
        <details className="panel p-4 mb-4 text-sm" data-testid="not-hostable-list" open={data.pairs.length === 0}>
          <summary className="cursor-pointer text-slate-300">{data.blocked.length} game{data.blocked.length > 1 ? "s" : ""} can't host right now — see each game's support limits</summary>
          <ul className="mt-3 space-y-2">{data.blocked.map((b) => <li key={b.name}><span className="font-semibold text-slate-200">{b.name}</span> <span className="text-slate-400">— {b.reason}</span></li>)}</ul>
        </details>
      )}
      <div className="space-y-3" data-testid="suggestions-list">{data?.pairs.map((p, i) => <PairCard key={p.key} p={p} i={i} onUse={use} />)}</div>
    </main>
  );
}
