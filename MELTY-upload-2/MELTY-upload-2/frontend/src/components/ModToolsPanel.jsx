import { useState } from "react";
import { Wrench, CheckCircle2, Circle, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg } from "../lib/api";
import { Button } from "./ui/button";

export const STATUS_STYLE = {
  "READY TO MOD": "text-emerald-300 border-emerald-500/40 bg-emerald-500/10",
  "SETUP REQUIRED": "text-amber-200 border-amber-500/40 bg-amber-500/10",
  "LIMITED SUPPORT": "text-cyan-200 border-cyan-500/40 bg-cyan-500/10",
  UNSUPPORTED: "text-rose-300 border-rose-500/40 bg-rose-500/10",
};
const LABEL = { "READY TO MOD": "Ready to mod", "SETUP REQUIRED": "Setup required", "LIMITED SUPPORT": "Limited support", UNSUPPORTED: "Unsupported" };
const ENGINES = [["redengine4", "REDengine 4 (Cyberpunk-style)"], ["unreal", "Unreal Engine 4/5"], ["unity-mono", "Unity (Mono)"], ["unity-il2cpp", "Unity (IL2CPP)"], ["unreal3", "Unreal Engine 3"], ["re-engine", "RE Engine"]];

export function ModStatusBadge({ status, testid }) {
  if (!status) return null;
  return <span data-testid={testid} className={`inline-block text-[10px] px-1.5 py-0.5 rounded border ${STATUS_STYLE[status] || ""}`}>{LABEL[status] || status}</span>;
}

export default function ModToolsPanel({ game, onChanged }) {
  const [engine, setEngine] = useState("");
  const tools = game.tools || [];
  const missing = tools.filter((t) => !t.installed && t.installable && t.required);
  const run = async (body, msg) => {
    try { await api.post("/games/tools", { device_id: game.device_id, install_dir: game.install_dir, ...body }); toast(msg); onChanged?.(); } catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <div className="space-y-3 border border-slate-800 rounded-lg p-3" data-testid="mod-tools-panel">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-slate-400">Game installed · {game.hostable ? "Can host mods" : "Can't host yet"}</span>
        <ModStatusBadge status={game.mod_status} testid="mod-status-badge" />
      </div>
      {tools.length > 0 && (
        <div className="space-y-1" data-testid="mod-tools-list">
          {tools.map((t) => (
            <div key={t.key} className="flex items-start gap-2 text-xs" data-testid={`tool-${t.key}`}>
              {t.installed ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 mt-0.5" /> : <Circle className="w-3.5 h-3.5 text-slate-600 mt-0.5" />}
              <div className="min-w-0">
                <span className="text-slate-200">{t.name}</span>{t.required && <span className="text-amber-200"> · needed</span>}
                <div className="text-slate-500">{t.installed ? "Installed" : t.install_hint || t.role}</div>
              </div>
              {!t.installed && t.installable && (
                <button data-testid={`tool-install-${t.key}`} onClick={() => run({ tools: [t.key] }, `${t.name} setup queued — approve it on My PC`)} className="ml-auto text-cyan-300 hover:underline shrink-0">Install</button>
              )}
            </div>
          ))}
        </div>
      )}
      {(game.capabilities || []).length > 0 && (
        <div className="text-xs space-y-0.5" data-testid="mod-capabilities">
          <div className="text-slate-500">What MELTY can build here</div>
          {game.capabilities.map((c) => <div key={c.feature} className={c.ready ? "text-emerald-300" : "text-slate-400"}>{c.ready ? "✓" : "○"} {c.feature}{!c.ready && ` (needs ${c.needs.join(" + ")})`}</div>)}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {missing.length > 0 && <Button data-testid="setup-tools-button" size="sm" onClick={() => run({ tools: missing.map((t) => t.key) }, "Setup queued — approve it on My PC")} className="bg-cyan-500 hover:bg-cyan-400 text-[#08090d]"><Wrench className="w-4 h-4 mr-1" />Set up modding tools</Button>}
        {tools.length > 0 && <Button data-testid="recheck-tools-button" size="sm" variant="outline" className="border-slate-700" onClick={() => run({ tools: [] }, "Checking installed tools…")}>Recheck tools</Button>}
      </div>
      {game.mod_status === "SETUP REQUIRED" && !tools.length && (
        <div className="flex items-center gap-2 text-xs" data-testid="manual-engine">
          <Settings2 className="w-3.5 h-3.5 text-slate-400" />
          <select data-testid="manual-engine-select" value={engine} onChange={(e) => setEngine(e.target.value)} className="bg-[#0a0b0e] border border-slate-800 rounded px-2 py-1">
            <option value="">Set the engine by hand…</option>
            {ENGINES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <Button data-testid="manual-engine-save" size="sm" variant="outline" className="border-slate-700 h-7" disabled={!engine}
            onClick={() => api.post("/games/manual", { device_id: game.device_id, install_dir: game.install_dir, engine }).then(() => { toast("Saved"); onChanged?.(); }).catch((e) => toast.error(errMsg(e)))}>Save</Button>
        </div>
      )}
    </div>
  );
}
