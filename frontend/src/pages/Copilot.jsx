import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Plus } from "lucide-react";
import { api } from "../lib/api";
import Composer from "../components/copilot/Composer";
import ModChat from "../components/copilot/ModChat";

const DOT = { verified: "bg-emerald-400", built: "bg-amber-300", unbuilt: "bg-slate-600" };

function useMods() {
  const [mods, setMods] = useState([]);
  useEffect(() => {
    const load = () => api.get("/mods").then((r) => setMods(r.data)).catch(() => {});
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);
  return mods;
}

function MobileRail({ current, mods }) {
  return (
    <div className="md:hidden flex gap-1.5 overflow-x-auto scroll-thin px-3 py-2 border-b border-slate-800/80" data-testid="copilot-rail-mobile">
      <Link to="/" className={`shrink-0 text-xs px-3 py-1 rounded-full ${!current ? "bg-cyan-500 text-[#08090d] font-semibold" : "border border-slate-700"}`}>+ New</Link>
      {mods.map((m) => <Link key={m.id} to={`/mods/${m.id}`} data-testid={`rail-mobile-mod-${m.id}`} className={`shrink-0 max-w-[180px] truncate text-xs px-3 py-1 rounded-full border ${current === m.id ? "border-cyan-500 text-cyan-200" : "border-slate-800 text-slate-400"}`}>{m.title}</Link>)}
    </div>
  );
}

function Rail({ current, mods }) {
  return (
    <aside className="hidden md:flex w-64 shrink-0 flex-col border-r border-slate-800/80 min-h-0" data-testid="copilot-rail">
      <div className="p-3">
        <Link to="/" data-testid="copilot-new-mod" className={`flex items-center gap-2 px-3 py-2 rounded-full text-sm font-semibold transition-colors ${!current ? "bg-cyan-500 text-[#08090d]" : "border border-slate-700 text-slate-200 hover:border-cyan-500/60"}`}>
          <Plus className="w-4 h-4" /> New mod
        </Link>
      </div>
      <p className="px-4 pb-2 text-[10px] uppercase tracking-widest text-slate-500">Your mods</p>
      <div className="flex-1 overflow-auto scroll-thin px-2 pb-4 space-y-0.5">
        {mods.map((m) => (
          <Link key={m.id} to={`/mods/${m.id}`} data-testid={`rail-mod-${m.id}`}
            className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${current === m.id ? "bg-slate-800/80 text-white" : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"}`}>
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${DOT[m.build_status] || "bg-slate-600"}`} />
            <span className="truncate">{m.title}</span>
          </Link>
        ))}
        {mods.length === 0 && <p className="px-3 text-xs text-slate-600">Nothing yet — describe your first mod.</p>}
      </div>
    </aside>
  );
}

export default function Copilot() {
  const { id } = useParams();
  const mods = useMods();
  return (
    <div className="flex h-[calc(100vh-3.5rem)]" data-testid="copilot-page">
      <Rail current={id} mods={mods} />
      <div className="flex-1 min-w-0 min-h-0 flex flex-col">
        <MobileRail current={id} mods={mods} />
        <div className="flex-1 min-h-0">{id ? <ModChat key={id} id={id} /> : <Composer />}</div>
      </div>
    </div>
  );
}
