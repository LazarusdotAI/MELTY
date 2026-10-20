import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, usd, ago, errMsg } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import StatusBadge from "../components/StatusBadge";
import ModelPicker from "../components/ModelPicker";

function Stat({ label, value, testid, tone = "text-slate-100" }) {
  return <div className="panel p-5"><p className="text-[11px] uppercase tracking-wider text-slate-500">{label}</p><p data-testid={testid} className={`font-display text-3xl font-bold mt-1 ${tone}`}>{value}</p></div>;
}

export default function Budget() {
  const [b, setB] = useState(null);
  const [cap, setCap] = useState("");
  const [gcap, setGcap] = useState("");
  const load = () => api.get("/budget").then((r) => { setB(r.data); setCap(String(r.data.settings.daily_ceiling)); setGcap(String(r.data.settings.generation_ceiling)); });
  useEffect(() => { load(); const t = setInterval(load, 10000); return () => clearInterval(t); }, []);
  if (!b) return <div className="p-10 text-slate-500">Loading…</div>;
  const save = async () => {
    try { await api.put("/budget/settings", { daily_ceiling: Number(cap), generation_ceiling: Number(gcap) }); toast.success("Limits saved"); load(); window.dispatchEvent(new Event("melty-budget")); } catch (e) { toast.error(errMsg(e)); }
  };
  const pct = Math.min(100, ((b.spent + b.reserved) / b.ceiling) * 100);
  return (
    <main className="px-8 py-10 max-w-[1400px] mx-auto">
      <p className="font-mono text-xs text-amber-400 tracking-widest uppercase mb-3">Cost controls · day {b.day} (UTC)</p>
      <h1 className="font-display text-4xl sm:text-5xl font-extrabold tracking-tight mb-6">Settings & AI budget</h1>
      <div className="mb-8 flex items-center gap-3 text-sm text-slate-400" data-testid="settings-model">AI model <ModelPicker /></div>
      <div className="grid sm:grid-cols-4 gap-4 mb-4">
        <Stat label="Spent today" value={usd(b.spent, 3)} testid="budget-spent" />
        <Stat label="Reserved (in-flight)" value={usd(b.reserved, 3)} testid="budget-reserved" tone="text-violet-300" />
        <Stat label="Remaining" value={usd(b.remaining, 3)} testid="budget-remaining" tone="text-cyan-300" />
        <Stat label="Daily ceiling" value={usd(b.ceiling, 2)} testid="budget-ceiling" tone="text-amber-300" />
      </div>
      <div className="h-2 rounded-full bg-slate-800 overflow-hidden mb-8"><div className="h-full bg-gradient-to-r from-cyan-400 to-amber-400" style={{ width: `${pct}%` }} /></div>
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 lg:col-span-4 space-y-6">
          <div className="panel p-5">
            <h3 className="font-display font-semibold mb-3">Limits</h3>
            <label className="text-xs text-slate-400">Daily ceiling (USD, your target {usd(b.settings.target, 0)})</label>
            <Input data-testid="daily-ceiling-input" value={cap} onChange={(e) => setCap(e.target.value)} className="bg-[#0a0b0e] border-slate-800 mb-3 mt-1" />
            <label className="text-xs text-slate-400">Per-run ceiling (USD)</label>
            <Input data-testid="generation-ceiling-input" value={gcap} onChange={(e) => setGcap(e.target.value)} className="bg-[#0a0b0e] border-slate-800 mt-1" />
            {Number(cap) >= b.settings.target && <p className="text-xs text-rose-300 mt-2">At or above your ${b.settings.target}/day target.</p>}
            <Button data-testid="save-limits-button" onClick={save} className="w-full mt-4 bg-cyan-500 hover:bg-cyan-400 text-[#08090d]">Save limits</Button>
            <p className="text-[11px] text-slate-500 mt-3">Every paid call reserves (input estimate + max output tokens) × price before it starts. Concurrent runs share the same atomic counter. When too little is left, runs pause and save a checkpoint.</p>
          </div>
          <div className="panel p-5" data-testid="outside-limit">
            <h3 className="font-display font-semibold mb-3">Outside the enforced limit</h3>
            {b.outside_limit.map((o) => <div key={o.item} className="py-2 border-t border-slate-800/60"><p className="text-sm">{o.item}</p><p className="text-[11px] text-slate-500">{o.note}</p></div>)}
            <p className="text-[11px] text-slate-500 mt-2">Companion jobs run on your PC: {Object.entries(b.companion_jobs).map(([k, v]) => `${k} ×${v}`).join(", ") || "none yet"}</p>
          </div>
        </div>
        <div className="col-span-12 lg:col-span-8 space-y-6">
          <div className="panel overflow-hidden" data-testid="per-project-table">
            <div className="px-5 py-3 border-b border-slate-800 font-display font-semibold">Per project</div>
            <table className="w-full text-sm"><tbody>
              {b.per_project.map((p) => <tr key={p.project_id || "x"} className="border-t border-slate-800/60"><td className="px-5 py-2">{p.title}</td><td className="px-5 py-2 font-mono text-xs text-slate-400">{p.calls} calls · {(p.tin || 0).toLocaleString()}→{(p.tout || 0).toLocaleString()} tok</td><td className="px-5 py-2 font-mono text-right">{usd(p.cost)}</td></tr>)}
            </tbody></table>
          </div>
          <div className="panel overflow-hidden" data-testid="per-generation-table">
            <div className="px-5 py-3 border-b border-slate-800 font-display font-semibold">Per AI run</div>
            <table className="w-full text-sm"><tbody>
              {b.generations.map((g) => <tr key={g.id} className="border-t border-slate-800/60"><td className="px-5 py-2"><div className="truncate max-w-[300px]">{g.title}</div><div className="text-[11px] text-slate-500 truncate max-w-[300px]">{g.kind}: {g.prompt}</div></td><td className="px-5 py-2"><StatusBadge status={g.status} /></td><td className="px-5 py-2 font-mono text-xs text-slate-400">{g.model || "—"}</td><td className="px-5 py-2 text-xs text-slate-500">{ago(g.created_at)}</td><td className="px-5 py-2 font-mono text-right">{usd(g.cost)}</td></tr>)}
            </tbody></table>
          </div>
          <div className="panel overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-800 font-display font-semibold">Recent paid calls (including failed attempts and fallbacks)</div>
            <div className="max-h-[360px] overflow-auto scroll-thin"><table className="w-full text-xs"><tbody>
              {b.calls.map((c) => <tr key={c.id} className="border-t border-slate-800/60"><td className="px-5 py-1.5 font-mono">{c.model}</td><td className="px-5 py-1.5 text-slate-400">{c.purpose}</td><td className="px-5 py-1.5"><StatusBadge status={c.status === "ok" ? "done" : "failed"} label={c.status} /></td><td className="px-5 py-1.5 font-mono text-slate-500">res {usd(c.reserved)}</td><td className="px-5 py-1.5 font-mono text-right">{usd(c.cost)}</td></tr>)}
            </tbody></table></div>
          </div>
        </div>
      </div>
    </main>
  );
}
