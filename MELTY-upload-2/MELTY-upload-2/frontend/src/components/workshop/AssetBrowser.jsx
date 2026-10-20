import { useEffect, useState } from "react";
import { Search, Download, Lock, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg } from "../../lib/api";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { bytes } from "./StateBadge";

export default function AssetBrowser({ locked, game, container, deviceId, onQueued }) {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [sel, setSel] = useState(new Set());
  const load = async (offset = 0) => {
    setBusy(true);
    try {
      const r = await api.post("/workshop/list", { install_dir: game.install_dir, device_id: deviceId, container: container.path, filter: q, offset, limit: 500 });
      setData((d) => (offset && d ? { ...r.data, items: [...d.items, ...r.data.items] } : r.data));
    } catch (e) { toast.error(errMsg(e)); }
    setBusy(false);
  };
  useEffect(() => { setSel(new Set()); setData(null); load(0); }, [container.path]); // eslint-disable-line react-hooks/exhaustive-deps
  const items = (data?.items || []).filter((i) => !type || i.type === type);
  const toggle = (p) => setSel((s) => { const n = new Set(s); n.has(p) ? n.delete(p) : n.add(p); return n; });
  const extract = async () => {
    try {
      const r = await api.post("/workshop/extract", { install_dir: game.install_dir, device_id: deviceId, container: container.path, paths: [...sel] });
      toast(r.data.state === "Permission Required" ? "Approve the extraction below to start" : "Extraction queued");
      setSel(new Set());
      onQueued();
    } catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <div className="panel p-5 space-y-3" data-testid="asset-browser">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-display font-semibold mr-auto">Files in <span className="font-mono text-cyan-300 text-sm">{container.rel}</span></h3>
        <div className="relative">
          <Search className="w-3.5 h-3.5 absolute left-2 top-2.5 text-slate-500" />
          <Input data-testid="asset-search-input" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load(0)}
            placeholder="Search names, e.g. Weapons" className="pl-7 h-9 w-56 bg-[#0a0b0e] border-slate-800 text-sm" />
        </div>
        <select data-testid="asset-type-filter" value={type} onChange={(e) => setType(e.target.value)} className="bg-[#0a0b0e] border border-slate-800 rounded-md text-sm h-9 px-2">
          <option value="">All types</option>
          {Object.keys(container.types || {}).map((t) => <option key={t} value={t}>{t} ({container.types[t]})</option>)}
        </select>
        <Button data-testid="asset-search-button" size="sm" variant="outline" className="border-slate-700" onClick={() => load(0)}>Search</Button>
        <Button data-testid="extract-selected-button" size="sm" disabled={locked || !sel.size} onClick={extract} className="bg-cyan-500 hover:bg-cyan-400 text-[#08090d]">
          <Download className="w-4 h-4 mr-1" /> Extract {sel.size || ""}
        </Button>
      </div>
      <p className="text-xs text-slate-500">Copies go to your MELTY workspace on your PC. The game's own files are only read, never changed. The first extraction from each game asks your permission.</p>
      {data?.issues?.map((x) => <p key={x} className="text-xs text-amber-200">{x}</p>)}
      <div className="max-h-[420px] overflow-auto scroll-thin border border-slate-800 rounded-md" data-testid="asset-list">
        {busy && !data ? <div className="p-6 text-sm text-slate-400 flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Reading the file list from your PC…</div> : (
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-[#11131a] text-slate-500"><tr><th className="w-8" /><th className="text-left py-1.5">Path</th><th className="text-left">Type</th><th className="text-right pr-3">Size</th><th className="text-left">Packed</th></tr></thead>
            <tbody>
              {items.map((i, n) => (
                <tr key={i.path} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                  <td className="text-center"><input type="checkbox" data-testid={`asset-row-checkbox-${n}`} disabled={i.encrypted} checked={sel.has(i.path)} onChange={() => toggle(i.path)} /></td>
                  <td className="py-1 font-mono truncate max-w-[520px]" title={i.path}>{i.path}</td>
                  <td>{i.type}</td><td className="text-right pr-3">{bytes(i.size)}</td>
                  <td>{i.encrypted ? <span className="text-rose-300 inline-flex items-center gap-1"><Lock className="w-3 h-3" /> encrypted</span> : i.compression || "none"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      {data && (
        <div className="flex justify-between text-xs text-slate-500">
          <span data-testid="asset-count">{data.items.length} of {data.total} shown</span>
          {data.items.length < data.total && <button data-testid="asset-load-more" onClick={() => load(data.items.length)} className="text-cyan-300 hover:underline">Load more</button>}
        </div>
      )}
    </div>
  );
}
