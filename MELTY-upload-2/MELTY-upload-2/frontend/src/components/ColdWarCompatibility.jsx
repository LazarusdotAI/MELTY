import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw, ShieldAlert, ExternalLink } from "lucide-react";
import { api, errMsg } from "../lib/api";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

export function isColdWar(g) {
  const name = (g?.name || g?.game || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const exe = (g?.exe || "").replace(/\\/g, "/").split("/").pop().toLowerCase();
  return name.includes("blackopscoldwar") || ["codcoldwar", "callofdutycoldwar"].includes(name)
    || exe === "blackopscoldwar.exe" || String(g?.steam_appid) === "1985810" || g?.adapter_id === "cold-war-t9";
}

function InstallationFacts({ installation: i, testid }) {
  const exists = (v) => v === true ? "Found" : v === false ? "Not found at last check" : "Unknown";
  const rows = [
    ["store", "Store", i.store || "Unknown"], ["source", "Detection source", i.detection_source || "Unknown"],
    ["path", "Installation", i.install_dir || "Unknown"], ["directory", "Folder at last check", exists(i.installation_exists)],
    ["exe", "Executable", i.exe || "Unknown"], ["present", "Executable at last check", exists(i.executable_exists)],
    ["exe-version", "Executable file version", i.executable_version || "Unknown"],
    ["reported-version", "Library / registry version", i.reported_version || "Unknown"],
    ["manual-version", "User-reported version (unverified)", i.manual_version || "Unknown"],
    ["checked", "Last explicit check", i.checked_at ? new Date(i.checked_at).toLocaleString() : "Not checked yet"],
  ];
  return <dl className="space-y-3 text-xs" data-testid={`${testid}-installation`}>
    {rows.map(([id, label, value]) => <div key={id} className="grid grid-cols-[minmax(100px,0.8fr)_minmax(0,1fr)] gap-3">
      <dt className="text-slate-500">{label}</dt><dd data-testid={`${testid}-${id}`} className="text-slate-200 font-mono break-words">{value}</dd>
    </div>)}
  </dl>;
}

export const ColdWarCompatibility = ({ game, testid = "cold-war", chooseHost = false }) => {
  const [report, setReport] = useState(null);
  const [version, setVersion] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);
  const [job, setJob] = useState(null);
  const [notice, setNotice] = useState("");
  const deviceId = game.device_id;
  const installDir = game.install_dir;
  useEffect(() => {
    let active = true;
    setReport(null); setError(""); setNotice(""); setJob(null); setVersion("");
    api.get("/games/cold-war/compatibility", { params: { device_id: deviceId, install_dir: installDir } })
      .then(({ data }) => { if (active) { setReport(data); setVersion(data.installation.manual_version || ""); } })
      .catch((e) => { if (active) setError(errMsg(e)); });
    return () => { active = false; };
  }, [deviceId, installDir]);
  useEffect(() => {
    if (!job) return undefined;
    let active = true;
    const poll = async () => {
      try {
        const { data } = await api.get(`/jobs/${job.id}`);
        if (!active) return;
        if (["done", "failed", "cancelled"].includes(data.status)) {
          if (data.status !== "done") { setJob(null); setNotice(""); setError(data.result?.error || "Check did not complete. Your game was not changed."); return; }
          const r = await api.get("/games/cold-war/compatibility", { params: { device_id: deviceId, install_dir: installDir } });
          if (active) { setReport(r.data); setNotice("Read-only check complete. Hosting remains unverified; no game changes were made."); setJob(null); }
        } else {
          setNotice(data.status === "needs_approval" ? "Waiting for inspection approval in My PC → Recent operations. Approval only allows reading metadata." : "Waiting for your PC to read installation metadata. If it is offline, start the companion.");
        }
      } catch (e) { if (active) { setJob(null); setError(errMsg(e)); } }
    };
    const timer = setInterval(poll, 2000);
    poll();
    return () => { active = false; clearInterval(timer); };
  }, [job, deviceId, installDir]);
  const check = async () => {
    setChecking(true); setError(""); setNotice("");
    try {
      const { data } = await api.post("/games/cold-war/check", { device_id: deviceId, install_dir: installDir });
      setJob(data);
    } catch (e) { setError(errMsg(e)); }
    finally { setChecking(false); }
  };
  const save = async () => {
    setSaving(true); setError("");
    try {
      const { data } = await api.patch("/games/cold-war/version", { device_id: deviceId, install_dir: installDir, version });
      setReport(data); setVersion(data.installation.manual_version || "");
      setNotice("Version saved as user-reported, not verified. This does not unlock mod actions.");
    } catch (e) { setError(errMsg(e)); }
    finally { setSaving(false); }
  };
  const cancel = async () => {
    try { await api.post(`/jobs/${job.id}/cancel`); setJob(null); setNotice("Stopped waiting. A check already running may still finish; it only reads metadata."); }
    catch (e) { setError(errMsg(e)); }
  };
  return <section data-testid={`${testid}-panel`} className="mt-5 space-y-5 border-t border-slate-800 pt-5">
    <div className="flex items-start gap-2 text-amber-200">
      <ShieldAlert className="w-5 h-5 shrink-0" />
      <h3 data-testid={`${testid}-status`} className="font-display font-semibold text-sm">Not supported by MELTY — host compatibility unverified</h3>
    </div>
    <p data-testid={`${testid}-intended-host`} className="text-xs text-slate-300">Intended host: <strong>{game.name}</strong>. Your choice is retained; no other game is substituted.</p>
    {chooseHost && <Button asChild data-testid={`${testid}-choose-host`} className="w-full bg-cyan-500 text-slate-950 hover:bg-cyan-400 text-xs">
      <Link to={`/?${new URLSearchParams({ host: game.name, device_id: deviceId })}`}>Keep Cold War as intended host</Link>
    </Button>}
    {report ? <>
      <div className="space-y-2 text-xs" data-testid={`${testid}-evidence-status`}>
        <p data-testid={`${testid}-detected`}><span className="text-cyan-300 font-semibold">Detected</span> · Installation recorded by your companion; this is not proof of hosting support.</p>
        <p data-testid={`${testid}-tools`}><span className="text-slate-200 font-semibold">Documented</span> · Unofficial community T9 scripting tools exist.</p>
        <p data-testid={`${testid}-loader`}><span className="text-amber-300 font-semibold">Unverified</span> · No working, authorized MELTY loading route established. Not supported.</p>
      </div>
      <InstallationFacts installation={report.installation} testid={testid} />
      {report.installation.inspection_note && <p data-testid={`${testid}-inspection-note`} className="text-xs text-slate-400">{report.installation.inspection_note}</p>}
      <div className="space-y-2">
        <Button data-testid={`${testid}-check`} disabled={checking || !!job} onClick={check} variant="outline" className="w-full border-cyan-700 text-cyan-200">
          <RefreshCw className={`w-4 h-4 mr-2 ${checking || job ? "animate-spin" : ""}`} /> {job ? "Checking metadata…" : "Run read-only compatibility check"}
        </Button>
        {job && <Button data-testid={`${testid}-cancel`} variant="ghost" onClick={cancel} className="text-xs">Stop waiting for this check</Button>}
        <p data-testid={`${testid}-check-scope`} className="text-xs text-slate-500">Requires companion 0.3.0+. Reads installation metadata only. No compiler, loader, game launch, binary upload, or AI charge.</p>
      </div>
      <div className="space-y-2">
        <label htmlFor={`${testid}-version-input`} className="text-xs text-slate-300">Displayed game version (optional, user-reported)</label>
        <Input id={`${testid}-version-input`} data-testid={`${testid}-version-input`} value={version} maxLength={80} onChange={(e) => setVersion(e.target.value)} placeholder="Enter the version shown by your game" className="bg-[#0a0b0e] border-slate-700 text-xs" />
        <Button data-testid={`${testid}-save-version`} onClick={save} disabled={saving} size="sm" variant="outline" className="border-slate-700">{saving ? "Saving…" : "Save version"}</Button>
        <p data-testid={`${testid}-manual-note`} className="text-xs text-slate-500">Kept separately from executable metadata. Entering a version or accepting a warning cannot unlock support.</p>
      </div>
      <div><h4 className="text-sm font-semibold mb-2">Still needed before hosting</h4>
        <ul data-testid={`${testid}-prerequisites`} className="list-disc pl-4 text-xs text-slate-400 space-y-2">{report.missing_prerequisites.map((p, i) => <li data-testid={`${testid}-prerequisite-${i}`} key={p}>{p}</li>)}</ul>
      </div>
      <div className="space-y-2 text-xs text-slate-400" data-testid={`${testid}-limits`}>{report.limits.map((p, i) => <p data-testid={`${testid}-limit-${i}`} key={p}>{p}</p>)}</div>
      <div className="space-y-2">{report.sources.map((s) => <a data-testid={`${testid}-source-${s.id}`} key={s.id} href={s.url} target="_blank" rel="noopener noreferrer" className="flex items-start gap-2 text-xs text-cyan-300 hover:underline"><ExternalLink className="w-3 h-3 shrink-0 mt-0.5" />{s.label}</a>)}</div>
    </> : !error && <p data-testid={`${testid}-loading`} className="text-xs text-slate-500">Loading saved installation details…</p>}
    {notice && <p data-testid={`${testid}-notice`} role="status" className="text-xs text-cyan-200">{notice}</p>}
    {error && <p data-testid={`${testid}-error`} role="alert" className="text-xs text-rose-300">{error}</p>}
    <div className="border-t border-slate-800 pt-4">
      <div className="flex flex-wrap gap-2">{["Build mod", "Install mod", "Launch mod"].map((label, i) => <Button key={label} data-testid={`${testid}-blocked-action-${i}`} disabled aria-describedby={`${testid}-blocked-reason`} size="sm" variant="outline" className="border-slate-700 text-xs">{label}</Button>)}</div>
      <p id={`${testid}-blocked-reason`} data-testid={`${testid}-blocked-reason`} className="text-xs text-amber-200 mt-3">Unavailable: no verified Cold War loading route. No runnable package will be generated and no AI credits will be spent. Any future host integration requires separate approval and may never become feasible.</p>
    </div>
  </section>;
};
