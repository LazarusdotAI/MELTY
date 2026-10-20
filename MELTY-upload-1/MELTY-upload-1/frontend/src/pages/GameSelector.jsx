import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Search, Monitor, Sparkles, Gauge, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg, ago } from "../lib/api";
import usePC from "../hooks/usePC";
import { Input } from "../components/ui/input";
import { canHost } from "../components/GamePicker";
import { ModStatusBadge } from "../components/ModToolsPanel";
import GameDetailsSheet from "../components/GameDetailsSheet";
import { Pairing } from "./Companion";

const TRAINER_ENGINES = ["redengine4", "unreal"];

function Cover({ g }) {
  const [err, setErr] = useState(false);
  return g.steam_appid && !err
    ? <img src={`https://cdn.cloudflare.steamstatic.com/steam/apps/${g.steam_appid}/header.jpg`} alt={g.name} onError={() => setErr(true)} className="w-full h-full object-cover group-hover:scale-[1.03] transition-transform duration-500" />
    : <div className="w-full h-full grid place-items-center bg-gradient-to-br from-slate-800 to-[#0a0b0e]"><span className="font-display text-3xl font-extrabold text-slate-500">{g.name.slice(0, 2).toUpperCase()}</span></div>;
}

function GameCard({ g, onOpen, i }) {
  const q = new URLSearchParams({ host: g.name, device_id: g.device_id });
  return (
    <div data-testid={`game-card-${g.name}`} className="group panel overflow-hidden flex flex-col fade-up" style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}>
      <button data-testid={`game-open-${g.name}`} onClick={() => onOpen(g)} className="aspect-[460/215] overflow-hidden bg-slate-900"><Cover g={g} /></button>
      <div className="p-3 flex flex-col gap-2 flex-1">
        <div className="flex items-start gap-2">
          <span className="font-display font-semibold text-sm leading-tight mr-auto">{g.name}</span>
          <ModStatusBadge status={g.mod_status} testid={`game-status-${g.name}`} />
        </div>
        <div className="mt-auto flex flex-wrap gap-1.5">
          {canHost(g) && <Link to={`/?${q}`} data-testid={`game-mod-${g.name}`} className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-full bg-cyan-500 text-[#08090d] font-semibold hover:bg-cyan-400 transition-colors"><Sparkles className="w-3 h-3" /> Make a mod</Link>}
          {TRAINER_ENGINES.includes(g.engine) && <Link to={`/trainer?game=${encodeURIComponent(g.install_dir)}`} data-testid={`game-trainer-${g.name}`} className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border border-slate-700 hover:border-cyan-500/60 transition-colors"><Gauge className="w-3 h-3" /> Trainer</Link>}
          {(!canHost(g) || g.mod_status === "SETUP REQUIRED") && <button data-testid={`game-setup-${g.name}`} onClick={() => onOpen(g)} className="text-xs px-2.5 py-1 rounded-full border border-amber-500/40 text-amber-200 hover:bg-amber-500/10 transition-colors">{g.mod_status === "SETUP REQUIRED" ? "Set it up" : "Why not?"}</button>}
        </div>
      </div>
    </div>
  );
}

export default function GameSelector() {
  const { device, games, reload } = usePC(6000);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(null);
  const [all, setAll] = useState(false);
  const [latest, setLatest] = useState(null);
  useEffect(() => { api.get("/companion-app/version").then((r) => setLatest(r.data.version)).catch(() => {}); }, []);
  const mine = device?.status?.version || device?.companion_version;
  const old = latest && mine && latest.localeCompare(mine, undefined, { numeric: true }) > 0;
  const list = useMemo(() => games.filter((g) => g.name.toLowerCase().includes(q.toLowerCase()) && (all || g.mod_status !== "UNSUPPORTED")), [games, q, all]);
  const rescan = async () => { try { await api.post(`/devices/${device.id}/jobs`, { op: "detect_games", params: {} }); toast("Looking for games on your PC…"); } catch (e) { toast.error(errMsg(e)); } };
  return (
    <main className="px-5 sm:px-8 py-10 max-w-[1400px] mx-auto space-y-6" data-testid="game-selector-page">
      <div className="flex flex-wrap items-end gap-4">
        <div className="mr-auto">
          <p className="font-mono text-xs text-cyan-400 tracking-widest uppercase mb-3">Game Selector</p>
          <h1 className="font-display text-4xl sm:text-5xl font-extrabold tracking-tight">Your games</h1>
        </div>
        {device && (
          <div data-testid="pc-status" className="flex items-center gap-2 text-sm text-slate-400">
            <Monitor className="w-4 h-4" /> {device.hostname}
            <span className={`flex items-center gap-1 text-xs ${device.online ? "text-emerald-300" : "text-amber-300"}`}><span className={`w-1.5 h-1.5 rounded-full ${device.online ? "bg-emerald-400" : "bg-amber-400"}`} />{device.online ? "online" : `offline · seen ${ago(device.last_seen)}`}</span>
            <button data-testid="rescan-games" disabled={!device.online} onClick={rescan} title="Look for games again" className="ml-1 p-1.5 rounded-full hover:bg-slate-800 disabled:opacity-40"><RefreshCw className="w-3.5 h-3.5" /></button>
          </div>
        )}
      </div>
      {old && <div data-testid="companion-update-banner" className="rounded-xl border border-amber-500/40 bg-amber-500/5 px-4 py-3 text-sm text-amber-100">Your PC's MELTY Companion is out of date ({mine} → {latest}). Close its window and start it again from the desktop shortcut — it updates itself. <Link to="/companion" className="text-cyan-300 ml-1">Other ways</Link></div>}
      {device === null || (device && !device.online) ? <div className="max-w-2xl"><Pairing onDone={reload} /></div> : null}
      {games.length > 0 && (
        <div className="flex items-center gap-3">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <Input data-testid="game-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${games.length} games`} className="pl-9 h-10 rounded-full bg-[#0a0b0e] border-slate-800" />
          </div>
          <button data-testid="show-all-games" onClick={() => setAll(!all)} className={`text-xs px-3 py-1.5 rounded-full border ${all ? "border-cyan-500 text-cyan-200" : "border-slate-700 text-slate-400"}`}>{all ? "Unsupported games: shown" : "Unsupported games: hidden"}</button>
        </div>
      )}
      <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="games-grid">
        {list.map((g, i) => <GameCard key={g.install_dir} g={g} i={i} onOpen={setOpen} />)}
      </div>
      {device?.online && games.length === 0 && <p className="text-sm text-slate-500" data-testid="games-scanning">Looking for games on your PC — they'll appear here by themselves.</p>}
      <GameDetailsSheet game={open} onClose={() => setOpen(null)} />
    </main>
  );
}
