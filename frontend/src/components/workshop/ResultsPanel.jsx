import { useMemo, useState } from "react";
import { Wand2, Microscope, Package, PlayCircle, Upload, Undo2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg, BACKEND } from "../../lib/api";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { LEVEL_STYLE, bytes } from "./StateBadge";

const cleanedAt = (ops, dir) => ops.find((j) => j.op === "asset_cleanup" && j.state === "Completed" && j.install_dir === dir)?.created_at || "";
const done = (ops, op, dir) => ops.filter((j) => j.op === op && j.state === "Completed" && (!dir || j.install_dir === dir) && (op === "asset_package" || op === "asset_install" || j.created_at > cleanedAt(ops, j.install_dir)));

function Reports({ ops, dir }) {
  const conv = ops.filter((j) => j.op === "asset_convert" && j.install_dir === dir && j.result?.reports).slice(0, 3);
  if (!conv.length) return null;
  return (
    <div className="space-y-2" data-testid="conversion-reports">
      <h4 className="text-sm font-semibold">Compatibility reports</h4>
      {conv.flatMap((j) => j.result.reports.map((r, i) => (
        <div key={j.id + i} className="flex gap-3 border border-slate-800 rounded-md p-2" data-testid={`report-${j.id.slice(0, 6)}-${i}`}>
          {r.preview && <img src={`${BACKEND}/api/jobs/${j.id}/artifact/${r.preview}`} alt="preview" className="w-16 h-16 object-contain bg-[#0a0b0e] rounded" style={{ imageRendering: "pixelated" }} />}
          <div className="min-w-0 text-xs space-y-0.5">
            <div className="font-mono truncate">{r.source?.split(/[\\/]/).pop()}</div>
            <div className={LEVEL_STYLE[r.level] || "text-slate-300"}>{r.converted ? "Converted · " : ""}{r.level_label}</div>
            <div className="text-slate-400">{r.reason}</div>
            {r.validation?.map((v) => <div key={v.path} className={v.ok ? "text-emerald-300/80" : "text-rose-300"}>Check: {v.check}</div>)}
            {r.outputs?.map((o) => <div key={o} className="text-slate-500 font-mono truncate">→ {o}</div>)}
          </div>
        </div>
      )))}
    </div>
  );
}

export default function ResultsPanel({ locked, src, dst, ops, deviceId, onQueued }) {
  const [sel, setSel] = useState({});
  const [name, setName] = useState("MeltyCrossover");
  const files = useMemo(() => {
    const ex = done(ops, "asset_extract", src?.install_dir).flatMap((j) => j.result.extracted.map((e) => ({ src: e.out, dest: e.path, size: e.size, kind: "extracted" })));
    const cv = done(ops, "asset_convert", src?.install_dir).flatMap((j) => j.result.reports.flatMap((r) => (r.converted ? r.outputs : []).map((o) => ({ src: o, dest: o.split(/[\\/]converted[\\/]/).pop()?.replace(/\\/g, "/"), kind: "converted" }))));
    const seen = new Set();
    return [...ex, ...cv].filter((f) => !seen.has(f.src) && seen.add(f.src));
  }, [ops, src]);
  const packages = done(ops, "asset_package").map((j) => ({ ...j.result, dir: j.install_dir }));
  const installs = done(ops, "asset_install").filter((j) => !done(ops, "uninstall_package").some((u) => u.params?.install_id === j.result.install_id));
  const call = async (path, body, msg) => {
    if (locked) return toast.error("Update the companion on your PC first");
    try {
      const r = await api.post(`/workshop/${path}`, { device_id: deviceId, ...body });
      toast(r.data.state === "Permission Required" ? "Approve it in Operations to continue" : msg);
      onQueued();
    } catch (e) { toast.error(errMsg(e)); }
  };
  const picked = files.filter((f) => sel[f.src]);
  const target = dst || src;
  if (!src) return null;
  return (
    <div className="panel p-5 space-y-4" data-testid="results-panel">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-display font-semibold mr-auto">Extracted & converted files</h3>
        <Button data-testid="convert-selected-button" size="sm" disabled={!picked.length} onClick={() => call("convert", { install_dir: src.install_dir, dst_install_dir: dst?.install_dir, files: picked.map((f) => f.src) }, "Conversion queued")} className="bg-cyan-500 hover:bg-cyan-400 text-[#08090d]"><Wand2 className="w-4 h-4 mr-1" />Convert</Button>
        <Button data-testid="analyze-selected-button" size="sm" variant="outline" className="border-slate-700" disabled={!picked.length} onClick={() => call("convert", { install_dir: src.install_dir, dst_install_dir: dst?.install_dir, files: picked.map((f) => f.src), analyze_only: true }, "Analysis queued")}><Microscope className="w-4 h-4 mr-1" />Check compatibility</Button>
      </div>
      {src.scan?.workspace && <p className="text-xs text-slate-500">Output folder on your PC: <span className="font-mono text-slate-300" data-testid="output-dir">{src.scan.workspace}</span></p>}
      {!files.length ? <p className="text-sm text-slate-500">Extract some files first.</p> : (
        <div className="max-h-64 overflow-auto scroll-thin space-y-1" data-testid="workspace-files">
          {files.map((f, i) => (
            <label key={f.src} className="flex items-center gap-2 text-xs border border-slate-800 rounded px-2 py-1">
              <input type="checkbox" data-testid={`workspace-file-${i}`} checked={!!sel[f.src]} onChange={() => setSel((s) => ({ ...s, [f.src]: s[f.src] ? undefined : f.dest }))} />
              <span className={`px-1.5 rounded text-[10px] ${f.kind === "converted" ? "bg-emerald-500/15 text-emerald-300" : "bg-slate-700/40 text-slate-300"}`}>{f.kind}</span>
              <span className="font-mono truncate mr-auto" title={f.src}>{f.src.split(/[\\/]/).pop()}</span>
              <span className="text-slate-500">{bytes(f.size)}</span>
            </label>
          ))}
        </div>
      )}
      <Reports ops={ops} dir={src.install_dir} />
      <div className="border-t border-slate-800 pt-4 space-y-2">
        <h4 className="text-sm font-semibold flex items-center gap-1"><Package className="w-4 h-4" /> Build a mod package for {target.name}</h4>
        {picked.map((f) => (
          <div key={f.src} className="flex items-center gap-2 text-xs">
            <span className="font-mono w-40 truncate">{f.src.split(/[\\/]/).pop()}</span>→
            <Input data-testid="package-dest-input" value={sel[f.src] || ""} onChange={(e) => setSel((s) => ({ ...s, [f.src]: e.target.value }))} className="h-7 text-xs bg-[#0a0b0e] border-slate-800 font-mono" />
          </div>
        ))}
        <div className="flex gap-2">
          <Input data-testid="package-name-input" value={name} onChange={(e) => setName(e.target.value)} className="h-9 w-56 bg-[#0a0b0e] border-slate-800 text-sm" />
          <Button data-testid="build-package-button" size="sm" disabled={!picked.length} onClick={() => call("package", { install_dir: target.install_dir, package_name: name, files: picked.map((f) => ({ src: f.src, dest: sel[f.src] })) }, "Package build queued")}>Build & verify</Button>
        </div>
        <p className="text-[11px] text-slate-500">Packages that contain files copied from a game are for your own PC only — MELTY never publishes them.</p>
        {packages.map((p, i) => (
          <div key={p.package + i} className="flex flex-wrap items-center gap-2 text-xs border border-slate-800 rounded p-2" data-testid={`package-row-${i}`}>
            <span className="font-mono truncate mr-auto">{p.package.split(/[\\/]/).pop()} · {bytes(p.size)}{p.personal_use_only ? " · personal use" : ""}</span>
            <Button data-testid={`package-test-${i}`} size="sm" variant="outline" className="border-slate-700 h-7" onClick={() => call("test-package", { install_dir: p.dir, package: p.package }, "Package check queued")}><PlayCircle className="w-3.5 h-3.5 mr-1" />Check</Button>
            <Button data-testid={`package-install-${i}`} size="sm" className="h-7 bg-violet-500 hover:bg-violet-400 text-white" onClick={() => call("install", { install_dir: p.dir, package: p.package }, "Install queued")}><Upload className="w-3.5 h-3.5 mr-1" />Install</Button>
          </div>
        ))}
        {installs.map((j, i) => (
          <div key={j.id} className="flex items-center gap-2 text-xs border border-emerald-500/30 rounded p-2" data-testid={`install-row-${i}`}>
            <span className="font-mono truncate mr-auto">Installed: {j.result.installed_to}</span>
            <Button data-testid={`rollback-${i}`} size="sm" variant="outline" className="border-slate-700 h-7" onClick={() => call("rollback", { install_id: j.result.install_id }, "Rollback queued")}><Undo2 className="w-3.5 h-3.5 mr-1" />Roll back</Button>
          </div>
        ))}
      </div>
      <button data-testid="cleanup-button" onClick={() => window.confirm("Delete extracted and converted copies in the workspace? Packages are kept.") && call("cleanup", { install_dir: src.install_dir }, "Cleanup queued")} className="text-xs text-slate-500 hover:text-rose-300 inline-flex items-center gap-1"><Trash2 className="w-3 h-3" /> Clean up temporary files</button>
    </div>
  );
}
