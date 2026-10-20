import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowUp, Loader2, Monitor, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg } from "../../lib/api";
import usePC from "../../hooks/usePC";
import GamePicker, { canHost } from "../GamePicker";
import { Textarea } from "../ui/textarea";

const IDEAS = ["Add a soft aim assist that gently pulls my view to the nearest enemy, with a visible marker", "Make my character run 50% faster and jump higher", "Bring the other game's weather and radiation zones into this one"];

function PcNote({ device }) {
  if (device === undefined || device?.online) return null;
  return (
    <div data-testid="composer-pc-offline" className="flex items-center gap-3 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-100">
      <Monitor className="w-4 h-4 shrink-0" /> {device ? "Your PC is offline. Start MELTY Companion so I can build and test on it." : "Connect your Windows PC first so I can see your games."}
      <Link to="/games" className="ml-auto text-cyan-300 whitespace-nowrap">Open Game Selector</Link>
    </div>
  );
}

export default function Composer() {
  const nav = useNavigate();
  const [params] = useSearchParams();
  const { device, games } = usePC(8000, params.get("device_id"));
  const [host, setHost] = useState(params.get("host") || "");
  const [sec, setSec] = useState(params.get("sec") ? [params.get("sec")] : []);
  const [desc, setDesc] = useState(params.get("desc") || localStorage.getItem("composer-draft") || "");
  const [more, setMore] = useState(!!params.get("sec"));
  const [busy, setBusy] = useState(false);
  useEffect(() => { desc ? localStorage.setItem("composer-draft", desc) : localStorage.removeItem("composer-draft"); }, [desc]);
  const hostGame = games.find((g) => g.name === host);
  const ready = hostGame && canHost(hostGame) && desc.trim() && !busy;
  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.post("/mods", { title: "", host: { name: host, role: "host" }, secondary: sec.map((name) => ({ name, role: "asset-source" })),
        aspects: ["mechanics", "audio", "visual_style"], description: desc, device_id: device?.id });
      localStorage.removeItem("composer-draft");
      nav(`/mods/${r.data.project_id}`);
    } catch (e) { toast.error(errMsg(e)); setBusy(false); }
  };
  return (
    <main className="h-full overflow-auto scroll-thin" data-testid="copilot-composer">
      <div className="max-w-3xl mx-auto px-5 py-12 space-y-6">
        <div>
          <p className="font-mono text-xs text-cyan-400 tracking-widest uppercase mb-3">Copilot</p>
          <h1 className="font-display text-4xl sm:text-5xl font-extrabold tracking-tight">What should we make?</h1>
          <p className="text-slate-400 mt-3 text-sm sm:text-base">Pick a game, say what you want. I'll write it, build it on your PC and try it in the game.</p>
        </div>
        <PcNote device={device} />
        <section className="space-y-2">
          <div className="flex items-baseline justify-between"><span className="text-xs uppercase tracking-widest text-slate-500">Game to mod</span>{host && <span data-testid="selected-host" className="text-sm text-cyan-200 font-semibold">{host}</span>}</div>
          {games.length ? <GamePicker testid="host-picker" mode="host" games={games} selected={[host]} disabledNames={sec} onToggle={(g) => setHost(host === g.name ? "" : g.name)} />
            : <p className="text-sm text-slate-500" data-testid="games-waiting">Your games show up here once your PC is connected.</p>}
          {hostGame && !canHost(hostGame) && <p data-testid="host-setup-needed" className="text-xs text-amber-200">{hostGame.host_reason || "This game needs its mod tools set up first."} Open it in Game Selector to set it up.</p>}
        </section>
        <button data-testid="toggle-borrow" onClick={() => setMore(!more)} className="flex items-center gap-1 text-sm text-violet-300 hover:text-violet-200">
          <ChevronDown className={`w-4 h-4 transition-transform ${more ? "rotate-180" : ""}`} /> Mix in another game {sec.length > 0 && `(${sec.join(", ")})`}
        </button>
        {more && games.length > 0 && <GamePicker testid="secondary-picker" mode="secondary" games={games} selected={sec} disabledNames={[host]}
          onToggle={(g) => setSec(sec.includes(g.name) ? sec.filter((s) => s !== g.name) : sec.length < 3 ? [...sec, g.name] : sec)} />}
        <div className="rounded-2xl border border-slate-700 bg-[#0d0f15] focus-within:border-cyan-500/60 transition-colors p-3">
          <Textarea data-testid="mod-description-input" value={desc} onChange={(e) => setDesc(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && ready) { e.preventDefault(); submit(); } }}
            placeholder="Describe the mod in your own words…" className="border-0 bg-transparent min-h-[110px] text-base focus-visible:ring-0 resize-none" />
          <div className="flex items-center gap-2">
            <div className="flex flex-wrap gap-1.5">{!desc && IDEAS.map((s, i) => <button key={s} data-testid={`composer-idea-${i}`} onClick={() => setDesc(s)} className="text-[11px] px-2.5 py-1 rounded-full border border-slate-800 text-slate-400 hover:text-cyan-200 hover:border-cyan-500/40 transition-colors">{s}</button>)}</div>
            <button data-testid="create-mod-button" disabled={!ready} onClick={submit} aria-label="Start"
              className="ml-auto w-10 h-10 shrink-0 rounded-full grid place-items-center bg-cyan-500 text-[#08090d] disabled:bg-slate-800 disabled:text-slate-500 hover:bg-cyan-400 transition-colors">
              {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowUp className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
