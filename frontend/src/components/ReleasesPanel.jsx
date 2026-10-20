import { useState } from "react";
import { Link } from "react-router-dom";
import { Package, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg, ago } from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Switch } from "./ui/switch";
import StatusBadge from "./StatusBadge";

export default function ReleasesPanel({ mod, releases, onChange }) {
  const [version, setVersion] = useState("0.1.0");
  const [notes, setNotes] = useState("");
  const [mp, setMp] = useState(false);
  const [busy, setBusy] = useState(false);
  const canRelease = mod.last_build_job_id && !mod.dirty && !mod.hosting_blocked_reason;
  const create = async () => {
    setBusy(true);
    try {
      await api.post(`/mods/${mod.id}/releases`, { version, notes, multiplayer_supported: mp, multiplayer_notes: mp ? "Multiplayer attempted — see compatibility table." : "Single-player only." });
      toast.success("Release package created (not published)");
      onChange();
    } catch (e) {
      toast.error(errMsg(e));
    }
    setBusy(false);
  };
  return (
    <div className="p-4 space-y-4" data-testid="releases-panel">
      <div className="rounded-lg border border-slate-800 p-3 space-y-2">
        <p className="text-xs text-slate-400">Package the last successful build as a <code className="text-cyan-300">meltpack.json</code> release with checksums and tested versions.</p>
        <div className="flex gap-2">
          <Input data-testid="release-version-input" value={version} onChange={(e) => setVersion(e.target.value)} className="h-8 w-24 bg-[#0a0b0e] border-slate-800 text-xs font-mono" />
          <Input data-testid="release-notes-input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="First-launch notes" className="h-8 bg-[#0a0b0e] border-slate-800 text-xs" />
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-400"><Switch data-testid="release-mp-switch" checked={mp} onCheckedChange={setMp} /> Multiplayer attempted</label>
        <Button data-testid="create-release-button" size="sm" disabled={!canRelease || busy} onClick={create} className="w-full bg-cyan-500 hover:bg-cyan-400 text-[#08090d]">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <><Package className="w-4 h-4 mr-1" /> Create release</>}
        </Button>
        {!canRelease && <p data-testid="release-unavailable-reason" className="text-[11px] text-amber-300">{mod.hosting_blocked_reason || "Needs a successful build of the current code first."}</p>}
      </div>
      {releases.map((r) => (
        <Link key={r.id} to={`/releases/${r.id}`} data-testid={`release-${r.id}`} className="block rounded-lg border border-slate-800 px-3 py-2 hover:border-cyan-500/40">
          <div className="flex items-center gap-2"><span className="font-mono text-sm">v{r.version}</span><StatusBadge status={r.published ? "done" : "untested"} label={r.published ? "published" : "private"} /><span className="ml-auto text-[11px] text-slate-500">{ago(r.created_at)}</span></div>
        </Link>
      ))}
    </div>
  );
}
