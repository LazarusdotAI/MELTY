import { useState } from "react";
import { Check, X, ChevronDown } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg, ago } from "../../lib/api";
import { Button } from "../ui/button";
import { Progress } from "../ui/progress";
import StateBadge from "./StateBadge";

const summary = (j) => {
  const r = j.result || {};
  if (j.op === "asset_scan") return r.engine ? `Engine: ${r.engine_version ? "Unreal " + r.engine_version : r.engine}; ${r.containers?.length ?? 0} containers` : "";
  if (j.op === "asset_extract") return r.extracted ? `${r.extracted.length} extracted, ${r.problems?.length || 0} problems${r.source_untouched ? " · game files untouched" : ""}` : `${j.count} files selected`;
  if (j.op === "asset_convert") return r.reports ? `${r.reports.filter((x) => x.converted).length} of ${r.reports.length} converted` : `${j.count} files`;
  if (j.op === "asset_package") return r.verify ? `${r.verify.files} files, verified` : "";
  if (j.op === "asset_install") return r.installed_to ? `Installed to ${r.installed_to}` : "Copies the package into the game (backed up)";
  if (j.op === "uninstall_package") return r.restored != null ? `Restored ${r.restored}, removed ${r.deleted}` : "";
  if (j.op === "asset_cleanup") return r.freed_bytes != null ? `Freed ${(r.freed_bytes / 1e6).toFixed(1)} MB` : "";
  return "";
};

function OpRow({ j, i, onChange }) {
  const [open, setOpen] = useState(false);
  const act = (path, msg) => api.post(path).then(() => { toast(msg); onChange(); }).catch((e) => toast.error(errMsg(e)));
  return (
    <div className="border border-slate-800 rounded-md p-3 space-y-2" data-testid={`op-row-${i}`}>
      <div className="flex items-center gap-2">
        <StateBadge state={j.state} testid={`op-state-${i}`} />
        <span className="text-sm truncate mr-auto">{j.label}</span>
        <span className="text-[11px] text-slate-500">{ago(j.created_at)}</span>
        <button data-testid={`op-toggle-${i}`} onClick={() => setOpen(!open)} className="text-slate-500 hover:text-slate-200"><ChevronDown className={`w-4 h-4 transition-transform ${open ? "rotate-180" : ""}`} /></button>
      </div>
      {j.state === "Running" && <div className="space-y-1"><Progress value={j.progress || 3} className="h-1.5" /><div className="text-[11px] text-slate-500 font-mono truncate">{j.progress_msg}</div></div>}
      <div className="text-xs text-slate-400">{summary(j)}</div>
      {j.why && <div className="text-xs text-rose-200" data-testid={`op-why-${i}`}>Why: {j.why}</div>}
      {j.state === "Permission Required" && (
        <div className="flex items-center gap-2 bg-violet-500/5 border border-violet-500/30 rounded-md p-2">
          <span className="text-xs text-violet-200 mr-auto">{j.op === "asset_extract" ? "Allow MELTY to copy files out of this game? Approving also allows later extractions from this game." : "Allow MELTY to change this game's folder? A backup is kept so you can roll back."}</span>
          <Button data-testid={`op-approve-${i}`} size="sm" className="bg-violet-500 hover:bg-violet-400 text-white h-7" onClick={() => act(`/jobs/${j.id}/approve`, "Approved")}><Check className="w-3.5 h-3.5 mr-1" />Allow</Button>
          <Button data-testid={`op-deny-${i}`} size="sm" variant="outline" className="border-slate-700 h-7" onClick={() => act(`/jobs/${j.id}/cancel`, "Cancelled")}><X className="w-3.5 h-3.5" /></Button>
        </div>
      )}
      {j.state === "Pending" && <button data-testid={`op-cancel-${i}`} onClick={() => act(`/jobs/${j.id}/cancel`, "Cancelled")} className="text-xs text-slate-500 hover:text-rose-300">Cancel</button>}
      {open && (
        <pre className="text-[11px] bg-[#0a0b0e] border border-slate-800 rounded p-2 max-h-60 overflow-auto scroll-thin whitespace-pre-wrap" data-testid={`op-log-${i}`}>
          {j.log || "(no log yet)"}{"\n"}{(j.result?.problems || []).map((p) => `${p.path}: ${p.reason}`).join("\n")}
        </pre>
      )}
    </div>
  );
}

export default function OpsPanel({ ops, onChange }) {
  return (
    <div className="panel p-5 space-y-3" data-testid="ops-panel">
      <h3 className="font-display font-semibold">Operations & logs</h3>
      {!ops.length && <p className="text-sm text-slate-500">Nothing has run yet.</p>}
      <div className="space-y-2 max-h-[560px] overflow-auto scroll-thin">
        {ops.map((j, i) => <OpRow key={j.id} j={j} i={i} onChange={onChange} />)}
      </div>
    </div>
  );
}
