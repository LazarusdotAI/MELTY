import { useState } from "react";
import { RotateCcw, Bookmark } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg, ago } from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import StatusBadge from "./StatusBadge";

export default function VersionsPanel({ mod, versions, onChange, busy }) {
  const [name, setName] = useState("");
  const save = async () => {
    await api.post(`/mods/${mod.id}/versions`, { name: name || "Checkpoint" });
    setName("");
    toast.success("Checkpoint saved");
    onChange();
  };
  const restore = async (v) => {
    if (!window.confirm(`Restore v${v.number} “${v.name}”? Your current code is kept as its own version, so you can switch back.`)) return;
    try {
      await api.post(`/mods/${mod.id}/versions/${v.id}/restore`);
      toast.success(`Restored v${v.number}`);
      onChange();
    } catch (e) {
      toast.error(errMsg(e));
    }
  };
  return (
    <div className="p-4" data-testid="versions-panel">
      <div className="flex gap-2 mb-4">
        <Input data-testid="checkpoint-name-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Checkpoint name" className="h-8 bg-[#0a0b0e] border-slate-800 text-xs" />
        <Button data-testid="save-checkpoint-button" size="sm" onClick={save} className="h-8 bg-violet-500 hover:bg-violet-400"><Bookmark className="w-3 h-3 mr-1" /> Save</Button>
      </div>
      <div className="space-y-2">
        {versions.map((v) => {
          const cur = v.id === mod.current_version_id;
          const st = (v.name.match(/\[(\w+)\]$/) || [])[1];
          return (
            <div key={v.id} data-testid={`version-${v.number}`} className={`rounded-lg border px-3 py-2 ${cur ? "border-cyan-500/50 bg-cyan-500/5" : "border-slate-800"}`}>
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs text-cyan-400">v{v.number}</span>
                <span className="text-sm truncate flex-1">{v.name.replace(/\s\[\w+\]$/, "")}</span>
                {st && <StatusBadge status={st} />}
              </div>
              <div className="flex items-center justify-between mt-1">
                <span className="text-[11px] text-slate-500">{v.kind} · {ago(v.created_at)}</span>
                {cur ? <span className="text-[11px] text-cyan-300">current</span> : (
                  <button data-testid={`restore-version-${v.number}`} disabled={busy} onClick={() => restore(v)} className="text-[11px] text-slate-300 hover:text-cyan-300 flex items-center gap-1 disabled:opacity-40"><RotateCcw className="w-3 h-3" /> Restore</button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
