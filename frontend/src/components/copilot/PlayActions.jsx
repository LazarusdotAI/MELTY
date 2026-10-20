import { useState } from "react";
import { Play, CheckCheck, Undo2, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg } from "../../lib/api";

function Action({ testid, icon: Icon, label, onClick, disabled, busy, primary }) {
  return (
    <button data-testid={testid} disabled={disabled || busy} onClick={onClick}
      className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-sm transition-colors disabled:opacity-40 ${primary ? "bg-emerald-400 text-[#08090d] hover:bg-emerald-300 font-semibold" : "border border-slate-700 text-slate-200 hover:border-cyan-500/60"}`}>
      {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Icon className="w-3.5 h-3.5" />} {label}
    </button>
  );
}

export default function PlayActions({ mod, play, busy, onDone }) {
  const [doing, setDoing] = useState("");
  if (!play?.built || mod.hosting_blocked_reason) return null;
  const run = async (k, path) => {
    setDoing(k);
    try {
      const r = await api.post(`/mods/${mod.id}/${path}`);
      if (r.data?.needs_approval) toast("Allow it in the box above so I can read the game's log.");
    } catch (e) { toast.error(errMsg(e)); }
    setDoing("");
    onDone();
  };
  return (
    <div className="flex flex-wrap gap-2" data-testid="play-actions">
      <Action testid="play-install" icon={Play} label={play.installed ? "Reinstall & play" : "Install & play"} primary={!play.installed} disabled={busy} busy={doing === "play"} onClick={() => run("play", "play")} />
      <Action testid="play-confirm" icon={CheckCheck} label={play.checking ? "Checking…" : "Check it worked"} primary={play.installed && play.status !== "verified"} disabled={busy || play.checking} busy={doing === "confirm" || play.checking} onClick={() => run("confirm", "confirm")} />
      {play.installed && <Action testid="play-remove" icon={Undo2} label="Remove from game" disabled={busy} busy={doing === "remove"} onClick={() => window.confirm("Remove this mod and put the game's files back?") && run("remove", "remove")} />}
    </div>
  );
}
