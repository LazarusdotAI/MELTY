import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Plus, Trash2, Wrench } from "lucide-react";
import { api, usd, ago } from "../lib/api";
import { Button } from "../components/ui/button";
import StatusBadge from "../components/StatusBadge";

export default function Mods() {
  const [items, setItems] = useState(null);
  const nav = useNavigate();
  const load = () => api.get("/mods").then((r) => setItems(r.data));
  useEffect(() => { load(); }, []);
  const del = async (e, m) => {
    e.stopPropagation();
    if (!window.confirm(`Delete “${m.title}” and its history?`)) return;
    await api.delete(`/mods/${m.id}`);
    load();
  };
  return (
    <main className="px-8 py-10 max-w-[1500px] mx-auto">
      <div className="flex items-end justify-between mb-8">
        <div>
          <p className="font-mono text-xs text-violet-400 tracking-widest uppercase mb-3">Creator</p>
          <h1 className="font-display text-4xl sm:text-5xl font-extrabold tracking-tight">My mods</h1>
        </div>
        <Link to="/"><Button data-testid="mods-new-button" className="rounded-full bg-cyan-500 hover:bg-cyan-400 text-[#08090d] font-semibold"><Plus className="w-4 h-4 mr-1" /> New mashup</Button></Link>
      </div>
      {items && items.length === 0 && <div data-testid="mods-empty" className="panel p-10 text-slate-400 max-w-lg">No mod projects yet.</div>}
      <div className="panel divide-y divide-slate-800" data-testid="mods-list">
        {(items || []).map((m) => (
          <div key={m.id} data-testid={`mod-row-${m.id}`} onClick={() => nav(`/mods/${m.id}`)}
            className="group flex items-center gap-5 px-5 py-4 cursor-pointer hover:bg-slate-900/60 transition-colors">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500/20 to-violet-500/20 grid place-items-center"><Wrench className="w-4 h-4 text-cyan-300" /></div>
            <div className="flex-1 min-w-0">
              <div className="font-display font-semibold truncate">{m.title}</div>
              <div className="text-xs text-slate-500 truncate">Host {m.host.name}{m.secondary?.length ? ` · ${m.secondary.map((s) => `${s.name} (${s.role})`).join(", ")}` : ""}</div>
            </div>
            <StatusBadge status={m.build_status} />
            <span className="font-mono text-xs text-slate-400 w-20 text-right">{usd(m.spent, 3)}</span>
            <span className="text-xs text-slate-500 w-20 text-right">{ago(m.updated_at)}</span>
            <button data-testid={`mod-delete-${m.id}`} onClick={(e) => del(e, m)} className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-rose-400"><Trash2 className="w-4 h-4" /></button>
          </div>
        ))}
      </div>
    </main>
  );
}
