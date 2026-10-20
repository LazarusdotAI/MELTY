import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Play, Globe, Lock, Copy } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg, ago } from "../lib/api";
import { Button } from "../components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import StatusBadge from "../components/StatusBadge";

export default function Release() {
  const { id } = useParams();
  const [r, setR] = useState(null);
  const [labels, setLabels] = useState({});
  const load = () => api.get(`/releases/${id}`).then((x) => setR(x.data));
  useEffect(() => { load(); api.get("/compat/keys").then((x) => setLabels(x.data)); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!r) return <div className="p-10 text-slate-500">Loading…</div>;
  const noVersion = !r.manifest.host.supported_versions?.length;
  const publish = async (p) => {
    if (p && !window.confirm("Publish this release to the public catalog? Anyone with the app can see and install it.")) return;
    try {
      await api.post(`/releases/${id}/publish`, { publish: p });
      toast.success(p ? "Published" : "Unpublished");
      load();
    } catch (e) { toast.error(errMsg(e)); }
  };
  const install = async () => {
    try {
      const x = await api.post(`/releases/${id}/install`, { launch: true });
      toast.success(`Install & launch sent to ${x.data.device}`);
    } catch (e) {
      toast.error(errMsg(e));
    }
  };
  const setCompat = async (gv, key, status) => {
    try {
      const x = await api.patch(`/releases/${id}/compat`, { key, status, game_version: gv });
      setR(x.data);
    } catch (e) { toast.error(errMsg(e)); }
  };
  const m = r.manifest;
  return (
    <main className="px-8 py-10 max-w-[1300px] mx-auto">
      <Link to={`/mods/${r.project_id}`} className="text-xs text-slate-500 hover:text-cyan-300">← mod project</Link>
      <div className="flex items-end gap-6 mt-2 mb-8">
        <div>
          <h1 data-testid="release-title" className="font-display text-4xl font-extrabold tracking-tight">{r.title} <span className="font-mono text-xl text-slate-500">v{r.version}</span></h1>
          <p className="text-sm text-slate-400 mt-2">Host <span className="text-cyan-300">{m.host.game}</span> {m.secondary.length > 0 && <>· uses your install of <span className="text-violet-300">{m.secondary.map((s) => s.game).join(", ")}</span></>}</p>
        </div>
        <div className="ml-auto flex gap-2">
          <Button data-testid="install-release-button" disabled={!!r.hosting_blocked_reason} onClick={install} className="rounded-full bg-cyan-500 hover:bg-cyan-400 text-[#08090d] font-semibold"><Play className="w-4 h-4 mr-1" /> Install & play on my PC</Button>
          {r.published ? <Button data-testid="unpublish-button" variant="outline" className="rounded-full border-slate-700" onClick={() => publish(false)}><Lock className="w-4 h-4 mr-1" /> Unpublish</Button>
            : <Button data-testid="publish-button" disabled={!!r.hosting_blocked_reason} variant="outline" className="rounded-full border-violet-500/60 text-violet-200" onClick={() => publish(true)}><Globe className="w-4 h-4 mr-1" /> Publish to catalog</Button>}
        </div>
      </div>
      {r.hosting_blocked_reason && <p data-testid="release-host-blocked" className="panel border-amber-500/30 p-4 mb-6 text-sm text-amber-200">{r.hosting_blocked_reason}. Install, mod launch and publishing are unavailable. A manual compatibility entry cannot unlock them.</p>}
      {noVersion && !r.hosting_blocked_reason && <div data-testid="no-version-warning" className="panel border-amber-500/30 p-4 mb-6 text-sm text-amber-200">The companion couldn't detect this game's version, so the package lists no tested version. Installs will work but can't warn about version mismatches.</div>}
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 lg:col-span-7 space-y-6">
          <div className="panel overflow-hidden" data-testid="compat-table">
            <div className="px-5 py-3 border-b border-slate-800"><h3 className="font-display font-semibold">Compatibility</h3><p className="text-xs text-slate-500">Each item is reported separately. Automated tests only prove install & launch; the rest need manual playtesting.</p></div>
            {Object.entries(r.compat).map(([gv, row]) => (
              <div key={gv} className="px-5 py-3">
                <p className="font-mono text-xs text-slate-400 mb-2">Game version {gv}</p>
                {Object.keys(labels).map((k) => (
                  <div key={k} className="flex items-center gap-3 py-1.5 border-t border-slate-800/50">
                    <span className="text-sm flex-1">{labels[k]}</span>
                    <span className="text-[11px] text-slate-500 w-40 truncate">{row[k]?.source || ""} {row[k]?.at ? `· ${ago(row[k].at)}` : ""}</span>
                    <Select value={row[k]?.status || "untested"} onValueChange={(v) => setCompat(gv, k, v)}>
                      <SelectTrigger data-testid={`compat-${k}`} className="h-7 w-32 bg-[#0a0b0e] border-slate-800 text-xs"><SelectValue /></SelectTrigger>
                      <SelectContent className="bg-[#0f1118] border-slate-800">{["untested", "verified", "partial", "failed"].map((s) => <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>)}</SelectContent>
                    </Select>
                    <StatusBadge status={row[k]?.status} />
                  </div>
                ))}
              </div>
            ))}
          </div>
          <div className="panel p-5"><h3 className="font-display font-semibold mb-2">Multiplayer</h3><p className="text-sm text-slate-400">{m.multiplayer?.notes}</p></div>
          {m.first_launch_notes && <div className="panel p-5"><h3 className="font-display font-semibold mb-2">First launch</h3><p className="text-sm text-slate-400">{m.first_launch_notes}</p></div>}
        </div>
        <div className="col-span-12 lg:col-span-5">
          <div className="panel overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-800 flex items-center"><h3 className="font-display font-semibold">meltpack.json</h3>
              <button data-testid="copy-manifest" className="ml-auto" onClick={() => { navigator.clipboard?.writeText(JSON.stringify(m, null, 2)); toast.success("Copied"); }}><Copy className="w-4 h-4 text-slate-400" /></button></div>
            <pre data-testid="manifest-json" className="font-mono text-[11px] text-cyan-100 p-4 overflow-auto max-h-[560px] scroll-thin">{JSON.stringify(m, null, 2)}</pre>
          </div>
        </div>
      </div>
    </main>
  );
}
