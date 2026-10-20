import { useCallback, useEffect, useState } from "react";
import { RefreshCw, ArrowLeftRight } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg } from "../lib/api";
import { Button } from "../components/ui/button";
import GamePanel from "../components/workshop/GamePanel";
import AssetBrowser from "../components/workshop/AssetBrowser";
import OpsPanel from "../components/workshop/OpsPanel";
import ResultsPanel from "../components/workshop/ResultsPanel";

const pref = (games, re) => games.find((g) => re.test(g.name))?.install_dir || "";

function Compat({ src, dst }) {
  if (!src?.scan || !dst?.scan) return null;
  const a = src.scan.engine_version, b = dst.scan.engine_version;
  const same = a && b && a === b;
  return (
    <div className="panel p-4 text-sm flex gap-3 items-start" data-testid="engine-compat">
      <ArrowLeftRight className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0" />
      <div>
        <b>{src.name}</b> {a ? `Unreal ${a}` : "(engine build not proven)"} → <b>{dst.name}</b> {b ? `Unreal ${b}` : "(engine build not proven)"}.{" "}
        {same ? "Same engine build: cooked files may load directly, but still check each one." :
          "Different builds: cooked game files can't be dropped in as-is. Textures, audio and config data can be converted (PNG / WAV / JSON) and re-imported; meshes and animations need export to FBX/glTF; materials and game logic are rebuilt as equivalents. Each file gets its own report below."}
      </div>
    </div>
  );
}

export default function AssetWorkshop() {
  const [data, setData] = useState({ device: null, games: [] });
  const [ops, setOps] = useState([]);
  const [srcDir, setSrcDir] = useState(localStorage.getItem("ws-src") || "");
  const [dstDir, setDstDir] = useState(localStorage.getItem("ws-dst") || "");
  const [container, setContainer] = useState(null);
  const load = useCallback(async () => {
    const g = await api.get("/workshop/games", { params: { device_id: localStorage.getItem("ws-device") || undefined } });
    if (g.data.device?.id) localStorage.setItem("ws-device", g.data.device.id);
    const o = await api.get("/workshop/ops", { params: { limit: 60, device_id: g.data.device?.id } });
    setData(g.data);
    setOps(o.data);
    const games = g.data.games;
    setSrcDir((s) => s || pref(games, /s\.?t\.?a\.?l\.?k\.?e\.?r/i));
    setDstDir((s) => s || pref(games, /ready or not/i));
  }, []);
  const active = ops.some((j) => ["Pending", "Running", "Permission Required"].includes(j.state));
  useEffect(() => { load().catch(() => {}); const t = setInterval(() => load().catch(() => {}), active ? 2000 : 6000); return () => clearInterval(t); }, [load, active]);
  useEffect(() => { localStorage.setItem("ws-src", srcDir); setContainer(null); }, [srcDir]);
  useEffect(() => { localStorage.setItem("ws-dst", dstDir); }, [dstDir]);
  const did = data.device?.id;
  const src = data.games.find((g) => g.install_dir === srcDir);
  const dst = data.games.find((g) => g.install_dir === dstDir);
  const go = async (path, body, msg) => {
    try { await api.post(path, { device_id: did, ...body }); toast(msg); load(); } catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <div className="max-w-7xl mx-auto px-6 py-10 space-y-6" data-testid="asset-workshop-page">
      <div className="flex flex-wrap items-end gap-4">
        <div className="mr-auto">
          <p className="text-xs uppercase tracking-[0.2em] text-cyan-400 font-mono">Asset Workshop</p>
          <h1 className="font-display text-4xl sm:text-5xl font-bold mt-2">Work with your games' files</h1>
          <p className="text-sm text-slate-400 mt-2 max-w-2xl">Look inside the games you own, copy out the parts you need, convert them, and build a personal mod — all on your PC. Locked (encrypted) files are reported, never broken into.</p>
        </div>
        <div className="text-xs text-slate-400" data-testid="workshop-device">{data.device ? <>PC: <b>{data.device.hostname}</b> · {data.device.online ? <span className="text-emerald-300">online</span> : <span className="text-rose-300">offline — start the companion</span>}</> : "No PC paired yet"}</div>
        <Button data-testid="detect-games-button" variant="outline" className="border-slate-700" onClick={() => go("/workshop/detect", {}, "Looking for installed games…")}><RefreshCw className="w-4 h-4 mr-1" />Detect games</Button>
      </div>
      {data.device && !data.device.asset_tools && (
        <div className="panel border-amber-500/40 p-4 text-sm text-amber-100" data-testid="companion-too-old">
          Your PC's companion is version {data.device.version || "unknown"}. Asset tools need 0.4.0 or newer: close the companion window and double-click <b>Start MELTY Companion</b> on your desktop — it updates itself.
        </div>
      )}
      <div className="grid lg:grid-cols-2 gap-4">
        <GamePanel role="source" title="Take assets from" game={src} games={data.games} onSelect={setSrcDir} locked={!data.device?.asset_tools} onScan={() => go("/workshop/scan", { install_dir: srcDir }, "Scan queued")}
          onPickContainer={setContainer} selectedContainer={container?.path} onRevoke={() => go("/workshop/grants/revoke", { install_dir: srcDir }, "Permission removed")} />
        <GamePanel role="destination" title="Bring them into" game={dst} games={data.games} onSelect={setDstDir} locked={!data.device?.asset_tools} onScan={() => go("/workshop/scan", { install_dir: dstDir }, "Scan queued")} />
      </div>
      <Compat src={src} dst={dst} />
      <div className="grid xl:grid-cols-[1fr_380px] gap-4 items-start">
        <div className="space-y-4 min-w-0">
          {src && container && <AssetBrowser locked={!data.device?.asset_tools} game={src} container={container} deviceId={did} onQueued={load} />}
          <ResultsPanel locked={!data.device?.asset_tools} src={src} dst={dst} ops={ops} deviceId={did} onQueued={load} />
        </div>
        <OpsPanel ops={ops} onChange={load} />
      </div>
    </div>
  );
}
