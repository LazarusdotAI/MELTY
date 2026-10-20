import { useEffect, useState } from "react";
import { Cpu, AlertTriangle } from "lucide-react";
import { toast } from "sonner";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";
import { api, errMsg } from "../lib/api";

export default function ModelPicker() {
  const [s, setS] = useState(null);
  const load = () => api.get("/providers/status").then((r) => setS(r.data)).catch(() => {});
  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, []);
  if (!s) return null;
  const change = async (v) => {
    try {
      const r = await api.put("/providers/preferred", { preferred_model: v });
      setS(r.data);
      toast.success(`Primary model: ${r.data.models.find((m) => m.key === v).label}`);
    } catch (e) {
      toast.error(errMsg(e));
    }
  };
  const pref = s.models.find((m) => m.key === s.preferred);
  const fallingBack = (s.active && s.active !== s.preferred);
  const activeLabel = s.models.find((m) => m.key === (s.active !== s.preferred ? s.active : s.models.find((x) => x.key !== "kimi" && x.available)?.key))?.label;
  return (
    <div className="flex flex-wrap items-center gap-2 max-w-full">
      {fallingBack && (
        <span data-testid="model-fallback-indicator" title={pref?.last_error || ""}
          className="flex items-center gap-1 text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/30 rounded-full px-2 py-1">
          <AlertTriangle className="w-3 h-3" /> {pref?.label} unavailable → {activeLabel}
        </span>
      )}
      <Select value={s.preferred} onValueChange={change}>
        <SelectTrigger data-testid="model-picker" className="h-8 w-[190px] bg-[#0f1118] border-slate-800 text-xs">
          <Cpu className="w-3.5 h-3.5 text-cyan-400 mr-1" />
          <SelectValue />
        </SelectTrigger>
        <SelectContent className="bg-[#0f1118] border-slate-800">
          {s.models.map((m) => (
            <SelectItem key={m.key} value={m.key} data-testid={`model-option-${m.key}`} className="text-xs">
              {m.label} <span className="text-slate-500 font-mono ml-1">{m.model}</span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
