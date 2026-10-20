import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Circle } from "lucide-react";
import { api } from "../lib/api";

const LINKS = { mod: "/", host: "/ideas" };

export default function Checklist({ deviceId }) {
  const [c, setC] = useState(null);
  useEffect(() => {
    const load = () => api.get("/checklist", { params: deviceId ? { device_id: deviceId } : {} }).then((r) => setC(r.data)).catch(() => {});
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [deviceId]);
  if (!c) return null;
  const next = c.steps.find((s) => !s.done);
  const href = (k) => (k === "build" || k === "test") && c.mod_id ? `/mods/${c.mod_id}` : (k === "release" && c.mod_id ? `/mods/${c.mod_id}` : (k === "install" && c.release_id ? `/releases/${c.release_id}` : LINKS[k]));
  return (
    <div className="panel p-5" data-testid="crossover-checklist">
      <h3 className="font-display font-semibold mb-1">First real crossover</h3>
      <p className="text-xs text-slate-500 mb-4">{c.steps.filter((s) => s.done).length}/{c.steps.length} done · updates live</p>
      <ol className="space-y-2">
        {c.steps.map((s) => {
          const isNext = next?.key === s.key;
          const h = href(s.key);
          const label = <span className={s.done ? "text-slate-400 line-through decoration-slate-600" : isNext ? "text-cyan-200 font-semibold" : "text-slate-300"}>{s.label}</span>;
          return (
            <li key={s.key} data-testid={`checklist-${s.key}`} className="flex items-center gap-2 text-sm">
              {s.done ? <CheckCircle2 className="w-4 h-4 text-emerald-400" /> : <Circle className={`w-4 h-4 ${isNext ? "text-cyan-400" : "text-slate-600"}`} />}
              {isNext && h ? <Link to={h} className="hover:underline">{label}</Link> : label}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
