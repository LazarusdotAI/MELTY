import { useEffect, useState } from "react";
import { Download, RefreshCw, Monitor, Trash2, Undo2, Check, X, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api, BACKEND, errMsg, ago } from "../lib/api";
import { Button } from "../components/ui/button";
import { Switch } from "../components/ui/switch";
import StatusBadge from "../components/StatusBadge";
import GameDetailsSheet, { isWWII } from "../components/GameDetailsSheet";
import { isColdWar } from "../components/ColdWarCompatibility";
import Checklist from "../components/Checklist";

export function Pairing({ onDone, compact }) {
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState(null);
  const [adv, setAdv] = useState(false);
  const setup = async () => {
    setBusy(true);
    try {
      const r = await api.post("/devices/pairing-code");
      setCode(r.data);
      const q = new URLSearchParams({ code: r.data.code, server: BACKEND });
      window.location.href = `${BACKEND}/api/companion-app/setup.bat?${q}`;
    } catch (e) { toast.error(errMsg(e)); }
    setBusy(false);
  };
  const cmd = code ? `python melty_companion.py pair ${BACKEND} ${code.code}` : "";
  return (
    <div className={compact ? "" : "panel p-6"} data-testid="pairing-panel">
      {!compact && <h2 className="font-display text-xl font-bold mb-1">Connect your Windows PC</h2>}
      <p className={compact ? "hidden" : "text-sm text-slate-400 mb-6"}>One file does everything: installs Python and the .NET SDK if they're missing, downloads the companion, connects this PC and adds a "Start MELTY Companion" shortcut to your desktop.</p>
      <ol className="space-y-5">
        <li className="flex gap-4 items-start"><span className="font-display text-2xl font-extrabold text-cyan-400 w-6">1</span>
          <div>
            <Button data-testid="download-setup-button" disabled={busy} onClick={setup} className="h-11 px-6 rounded-full bg-cyan-500 hover:bg-cyan-400 text-[#08090d] font-semibold">
              <Download className="w-4 h-4 mr-2" /> {code ? "Download setup again" : "Download setup for this PC"}
            </Button>
            <p className="text-xs text-slate-500 mt-2">If your browser asks, choose <b className="text-slate-300">Keep</b>. The file has your private pairing code and works once, within 15 minutes.</p>
          </div></li>
        <li className="flex gap-4 items-start"><span className="font-display text-2xl font-extrabold text-cyan-400 w-6">2</span>
          <div className="text-sm text-slate-300">Open <b>MELTY-Setup.bat</b> from your downloads (double-click it).
            <p className="text-xs text-slate-500 mt-1">If Windows shows "Windows protected your PC", click <b className="text-slate-300">More info</b> → <b className="text-slate-300">Run anyway</b>. If it installs Python, it will ask you to open the file once more.</p></div></li>
        <li className="flex gap-4 items-start"><span className="font-display text-2xl font-extrabold text-cyan-400 w-6">3</span>
          <div className="text-sm text-slate-300 flex items-center gap-2">Leave the black window open — this page turns <span className="text-emerald-300">online</span> by itself.
            <Button data-testid="refresh-devices" size="sm" variant="ghost" onClick={onDone}><RefreshCw className="w-4 h-4" /></Button></div></li>
      </ol>
      <p className="text-xs text-slate-500 mt-6">Next time, just double-click <b className="text-slate-300">Start MELTY Companion</b> on your desktop.</p>
      <button data-testid="advanced-pairing-toggle" onClick={() => setAdv(!adv)} className="text-[11px] text-slate-500 hover:text-slate-300 mt-4">{adv ? "Hide" : "Show"} manual setup</button>
      {adv && (
        <div className="mt-3 text-xs space-y-2 text-slate-400">
          <a data-testid="download-companion" href={`${BACKEND}/api/companion-app/download`} className="text-cyan-300 hover:underline">Download melty_companion.py</a>
          {code && <code data-testid="pair-command" className="block font-mono bg-[#0a0b0e] border border-slate-800 rounded px-3 py-2 break-all">{cmd}</code>}
        </div>
      )}
    </div>
  );
}

function OpsPanel({ device, ops, onChange }) {
  const set = async (op, on) => {
    const next = on ? [...device.approved_ops, op] : device.approved_ops.filter((o) => o !== op);
    await api.patch(`/devices/${device.id}`, { approved_ops: next });
    onChange();
  };
  return (
    <div className="panel p-5" data-testid="ops-panel">
      <h3 className="font-display font-semibold mb-1">Auto-run operations</h3>
      <p className="text-xs text-slate-500 mb-4">Approved types run without asking. Others wait for your OK here.</p>
      <div className="space-y-2.5">
        {Object.entries(ops).map(([k, v]) => (
          <div key={k} className="flex items-center gap-3">
            <Switch data-testid={`op-toggle-${k}`} checked={device.approved_ops.includes(k)} onCheckedChange={(c) => set(k, c)} />
            <div className="min-w-0"><div className="font-mono text-xs text-slate-200">{k}</div><div className="text-[11px] text-slate-500 truncate">{v}</div></div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Companion() {
  const [devices, setDevices] = useState([]);
  const [ops, setOps] = useState({});
  const [games, setGames] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [installs, setInstalls] = useState([]);
  const [details, setDetails] = useState(null);
  const [latest, setLatest] = useState(null);
  const d = devices.find((x) => x.online) || devices[0];
  const load = async () => {
    const r = await api.get("/devices");
    setDevices(r.data);
    const dev = r.data.find((x) => x.online) || r.data[0];
    if (dev) {
      const [g, j, i] = await Promise.all([api.get(`/devices/${dev.id}/games`), api.get(`/jobs?device_id=${dev.id}`), api.get(`/installs?device_id=${dev.id}`)]);
      setGames(g.data); setJobs(j.data); setInstalls(i.data);
    }
  };
  useEffect(() => {
    api.get("/companion/ops").then((r) => setOps(r.data));
    api.get("/companion-app/version").then((r) => setLatest(r.data.version));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);
  const job = async (op, params = {}) => {
    try { await api.post(`/devices/${d.id}/jobs`, { op, params }); toast.success(`Sent ${op}`); load(); } catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <main className="px-8 py-10 max-w-[1500px] mx-auto">
      <p className="font-mono text-xs text-cyan-400 tracking-widest uppercase mb-3">Desktop companion</p>
      <h1 className="font-display text-4xl sm:text-5xl font-extrabold tracking-tight mb-8">My PC</h1>
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 lg:col-span-8 space-y-6">
          {d ? (
            <div className="panel p-5 flex flex-wrap items-center gap-4" data-testid="device-card">
              <Monitor className="w-8 h-8 text-cyan-300" />
              <div className="flex-1 min-w-[140px] max-w-full break-words">
                <div className="font-display font-semibold text-lg">{d.hostname}</div>
                <div className="text-xs text-slate-500 font-mono">{d.os} · companion {d.status?.version || d.companion_version} · .NET {d.status?.dotnet || "not found"} · seen {ago(d.last_seen)}</div>
              </div>
              <StatusBadge testid="device-online-status" status={d.online ? "done" : "failed"} label={d.online ? "online" : "offline"} />
              <Button data-testid="detect-games-button" size="sm" disabled={!d.online} onClick={() => job("detect_games")} className="bg-cyan-500 hover:bg-cyan-400 text-[#08090d]"><RefreshCw className="w-4 h-4 mr-1" /> Rescan now</Button>
              <Button data-testid="doctor-button" size="sm" variant="outline" disabled={!d.online} onClick={() => job("doctor")} className="border-slate-700">Doctor</Button>
              <button data-testid="revoke-device" title="Revoke" onClick={async () => { if (window.confirm("Revoke this PC?")) { await api.delete(`/devices/${d.id}`); load(); } }} className="text-slate-500 hover:text-rose-400"><Trash2 className="w-4 h-4" /></button>
            </div>
          ) : null}
          {d && latest && latest.localeCompare(d.status?.version || d.companion_version, undefined, { numeric: true }) > 0 && (
            <div data-testid="companion-update-banner" className="panel border-amber-500/40 p-5">
              <h3 className="font-display font-semibold text-amber-200">Update your companion ({d.status?.version || d.companion_version} → {latest})</h3>
              <p className="text-sm text-slate-400 mt-1 mb-4">Fixes WWII campaign detection and adds Cold War read-only checks. Easiest way: close the companion window, then double-click <b>Start MELTY Companion</b> on your desktop — it updates itself on start. If that doesn't work, download the updater below and double-click <b>MELTY-Update.bat</b>. Your pairing is kept.</p>
              <Button asChild data-testid="download-companion-update" className="bg-cyan-500 hover:bg-cyan-400 text-[#08090d]"><a href={`${BACKEND}/api/companion-app/update.bat?${new URLSearchParams({ server: BACKEND })}`}><Download className="w-4 h-4 mr-2" /> Download updater (MELTY-Update.bat)</a></Button>
            </div>
          )}
          {(!d || !d.online) && <Pairing onDone={load} />}
          {d && (
            <div className="panel overflow-hidden" data-testid="games-table">
              <div className="px-5 py-3 border-b border-slate-800 flex justify-between items-center"><h3 className="font-display font-semibold">Detected games</h3><span data-testid="auto-scan-status" className="text-xs text-slate-500">{games.length} found · auto-scan {d.last_scan_at ? `last ran ${ago(d.last_scan_at)}` : "pending"} · repeats every 30 min</span></div>
              <div className="max-h-[380px] overflow-auto scroll-thin">
                <table className="w-full text-sm">
                  <thead className="text-[11px] uppercase text-slate-500 sticky top-0 bg-[#0f1118]"><tr>{["Game", "Engine", "Toolchain", "Version", "Loader / SDK", "Host?"].map((h) => <th key={h} className="text-left px-5 py-2 font-medium">{h}</th>)}</tr></thead>
                  <tbody>
                    {games.map((g) => (
                      <tr key={g.install_dir} onClick={() => setDetails(g)} className="border-t border-slate-800/60 cursor-pointer hover:bg-slate-900/60" data-testid={`game-row-${g.name}`}>
                        <td className="px-5 py-2"><div>{g.name}</div><div className="text-[10px] text-slate-600 font-mono truncate max-w-[260px]">{g.install_dir}</div></td>
                        <td className="px-5 py-2 font-mono text-xs">{g.engine}</td>
                        <td className="px-5 py-2 font-mono text-xs text-slate-400">{g.toolchain || "—"}{g.unity_version ? ` · ${g.unity_version}` : ""}</td>
                        <td className="px-5 py-2 font-mono text-xs text-slate-400">{g.game_version || "—"}</td>
                        <td className="px-5 py-2">{g.loader_installed ? <Check className="w-4 h-4 text-emerald-400" /> : <X className="w-4 h-4 text-slate-600" />}</td>
                        <td className="px-5 py-2"><span title={g.host_reason || ""}><StatusBadge testid={`host-status-${g.name}`} status={isColdWar(g) || isWWII(g) ? "partial" : g.hostable ? "built" : g.adapter_status === "blocked" ? "failed" : "untested"} label={isColdWar(g) || isWWII(g) ? "Unverified" : g.hostable ? "hostable" : g.adapter_status === "blocked" ? "blocked" : "borrow only"} /></span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {games.length === 0 && <p className="p-5 text-sm text-slate-500">{d.online ? "Scanning your Steam, Epic, GOG, Xbox, Ubisoft, EA and installed-programs lists…" : "Start the companion and your games are scanned automatically."}</p>}
              </div>
            </div>
          )}
          {installs.length > 0 && (
            <div className="panel p-5" data-testid="installs-panel">
              <h3 className="font-display font-semibold mb-3">Installed packages</h3>
              {installs.map((i) => (
                <div key={i.install_id} className="flex items-center gap-3 py-2 border-t border-slate-800/60 text-sm">
                  <span className="flex-1">{i.name} <span className="text-xs text-slate-500 font-mono">{i.install_id.slice(0, 8)} · +{i.files_created} new, {i.files_replaced} replaced</span></span>
                  <StatusBadge status={i.status} />
                  {i.status === "installed" && <Button data-testid={`restore-install-${i.install_id}`} size="sm" variant="outline" className="border-slate-700" onClick={async () => { await api.post(`/installs/${i.install_id}/restore`); toast.success("Restore queued"); load(); }}><Undo2 className="w-4 h-4 mr-1" /> Uninstall & restore</Button>}
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="col-span-12 lg:col-span-4 space-y-6">
          <Checklist deviceId={d?.id} />
          {d && <OpsPanel device={d} ops={ops} onChange={load} />}
          {d && (
            <div className="panel p-5" data-testid="jobs-panel">
              <h3 className="font-display font-semibold mb-3">Recent operations</h3>
              <div className="space-y-2 max-h-[420px] overflow-auto scroll-thin">
                {jobs.map((j) => (
                  <div key={j.id} className="text-xs border-t border-slate-800/60 pt-2" data-testid={`job-${j.id}`}>
                    <div className="flex items-center gap-2"><span className="font-mono text-slate-200">{j.op}</span><StatusBadge status={j.status} /><span className="ml-auto text-slate-500">{ago(j.created_at)}</span></div>
                    <div className="text-slate-500 truncate">{j.label}{j.result?.error ? ` — ${j.result.error}` : ""}</div>
                    {j.status === "needs_approval" && <Button data-testid={`approve-job-${j.id}`} size="sm" className="mt-1 h-7 bg-amber-500 text-black" onClick={async () => { await api.post(`/jobs/${j.id}/approve`); load(); }}>Approve</Button>}
                    {j.status === "running" && <Loader2 className="w-3 h-3 animate-spin text-violet-300 mt-1" />}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
      <GameDetailsSheet game={details} onClose={() => setDetails(null)} />
    </main>
  );
}
