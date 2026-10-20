import { Cpu, ScanSearch, ShieldCheck, FolderOpen } from "lucide-react";
import { Button } from "../ui/button";
import { bytes } from "./StateBadge";

const CSTATE = {
  ok: ["Readable", "text-emerald-300"],
  metadata_only: ["Info only", "text-amber-200"],
  blocked_by_protection: ["Encrypted — blocked", "text-rose-300"],
  unsupported: ["Unsupported", "text-amber-300"],
  failed: ["Could not read", "text-rose-300"],
};

function Containers({ scan, selected, onPick, role }) {
  if (!scan?.containers?.length) return <p className="text-xs text-slate-500">No .pak/.utoc containers found yet.</p>;
  return (
    <div className="max-h-56 overflow-auto scroll-thin space-y-1" data-testid={`${role}-containers`}>
      {scan.containers.map((c, i) => {
        const [label, cls] = CSTATE[c.state] || [c.state, "text-slate-400"];
        return (
          <button key={c.path} data-testid={`${role}-container-${i}`} disabled={c.state !== "ok"} onClick={() => onPick?.(c)}
            className={`w-full text-left px-2 py-1.5 rounded-md border text-xs transition-colors ${selected === c.path ? "border-cyan-500/60 bg-cyan-500/10" : "border-slate-800 hover:border-slate-600"} disabled:opacity-60`}>
            <div className="flex justify-between gap-2"><span className="font-mono truncate">{c.rel}</span><span className={cls}>{label}</span></div>
            <div className="text-slate-500 mt-0.5">{c.format} v{c.version} · {c.files ?? 0} files · {bytes(c.size)}{c.methods?.length ? ` · ${c.methods.join(", ")}` : ""}{c.ue_hint ? ` · ${c.ue_hint}` : ""}</div>
            {c.issues?.map((x) => <div key={x} className="text-amber-200/80 mt-0.5">{x}</div>)}
          </button>
        );
      })}
    </div>
  );
}

export default function GamePanel({ locked, role, title, game, games, onSelect, onScan, onPickContainer, selectedContainer, onRevoke }) {
  const scan = game?.scan;
  return (
    <div className="panel p-5 space-y-4" data-testid={`${role}-game-panel`}>
      <div className="flex items-center justify-between gap-3">
        <span className="text-[11px] uppercase tracking-widest text-slate-500">{title}</span>
        <select data-testid={`${role}-game-select`} value={game?.install_dir || ""} onChange={(e) => onSelect(e.target.value)}
          className="bg-[#0a0b0e] border border-slate-800 rounded-md text-sm px-2 py-1.5 max-w-[60%]">
          <option value="">Choose a game…</option>
          {games.map((g) => <option key={g.install_dir} value={g.install_dir}>{g.name}{g.engine === "unreal" ? " (Unreal)" : ""}</option>)}
        </select>
      </div>
      {game && (
        <>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h3 className="font-display font-semibold text-lg truncate" data-testid={`${role}-game-name`}>{game.name}</h3>
              <p className="text-xs text-slate-500 font-mono truncate flex items-center gap-1"><FolderOpen className="w-3 h-3 shrink-0" />{game.install_dir}</p>
            </div>
            <Button data-testid={`${role}-scan-button`} size="sm" disabled={locked} onClick={onScan} className="bg-cyan-500 hover:bg-cyan-400 text-[#08090d] shrink-0">
              <ScanSearch className="w-4 h-4 mr-1" /> {scan ? "Rescan" : "Scan game"}
            </Button>
          </div>
          {scan ? (
            <div className="grid grid-cols-2 gap-2 text-xs" data-testid={`${role}-engine-info`}>
              <Info k="Store" v={scan.store || game.source} />
              <Info k="Game version" v={scan.store_version || game.game_version || "not reported"} />
              <Info k="Engine" v={scan.engine_version ? `Unreal ${scan.engine_version}` : scan.engine === "unreal" ? "Unreal (build not proven)" : scan.engine} testid={`${role}-engine-version`} />
              <Info k="Game .exe version" v={scan.exe_version || "not readable"} />
              <div className="col-span-2 text-slate-400 space-y-0.5" data-testid={`${role}-evidence`}>
                {scan.evidence?.map((e) => <div key={e} className="flex gap-1"><Cpu className="w-3 h-3 mt-0.5 text-cyan-400 shrink-0" />{e}</div>)}
                {scan.engine_version_note && <div className="text-amber-200/80">{scan.engine_version_note}</div>}
                {scan.sdk_candidates?.length > 0 && <div className="text-emerald-300">Mod kit found: {scan.sdk_candidates.map((s) => s.name).join(", ")}</div>}
              </div>
            </div>
          ) : <p className="text-sm text-slate-400">Scan reads the version, engine and file containers. It never changes game files.</p>}
          {role === "source" && game.extract_granted && (
            <div className="flex items-center gap-2 text-xs text-emerald-300" data-testid="extract-granted">
              <ShieldCheck className="w-3.5 h-3.5" /> Extraction allowed for this game
              <button data-testid="revoke-extract-grant" onClick={onRevoke} className="text-slate-500 hover:text-rose-300 underline">revoke</button>
            </div>
          )}
          {scan && <Containers scan={scan} role={role} selected={selectedContainer} onPick={onPickContainer} />}
        </>
      )}
    </div>
  );
}

function Info({ k, v, testid }) {
  return (
    <div className="rounded-md border border-slate-800 px-2 py-1.5" data-testid={testid}>
      <div className="text-slate-500">{k}</div><div className="text-slate-200 truncate">{v}</div>
    </div>
  );
}
