import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { Check, X } from "lucide-react";
import ModToolsPanel from "./ModToolsPanel";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "./ui/sheet";
import { api, ago } from "../lib/api";
import StatusBadge from "./StatusBadge";
import { Button } from "./ui/button";
import { ColdWarCompatibility, isColdWar } from "./ColdWarCompatibility";

export function isWWII(g) {
  const name = (g?.name || g?.game || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  const exe = (g?.exe || "").replace(/\\/g, "/").split("/").pop().toLowerCase();
  return ["callofdutywwii", "codwwii", "callofdutywwiimultiplayer", "callofdutywwiisingleplayer", "callofdutywwiicampaign"].includes(name)
    || ["s2_sp64_ship.exe", "s2_mp64_ship.exe"].includes(exe) || String(g?.steam_appid) === "476600" || g?.adapter_id === "cod-wwii-s2";
}

export const WwiiCampaignStatus = ({ game, testid = "wwii", chooseHost = false }) => {
  const found = game.campaign_executable_found;
  return <section data-testid={`${testid}-status-panel`} className="mt-5 space-y-4 border-t border-slate-800 pt-5 text-xs">
    <h3 data-testid={`${testid}-status`} className="text-sm font-semibold text-amber-200">Not supported by MELTY — WWII campaign loader compatibility unverified</h3>
    <p data-testid={`${testid}-mode`} className="text-slate-300">Intended mode: <strong>single-player campaign</strong>. This replaces the generic online-game restriction; it does not enable mod loading.</p>
    <dl className="space-y-3 text-slate-400">
      <div><dt>Expected campaign executable</dt><dd data-testid={`${testid}-expected-exe`} className="font-mono text-slate-200">s2_sp64_ship.exe</dd></div>
      <div><dt>Campaign file at last scan</dt><dd data-testid={`${testid}-campaign-file`} className="font-mono text-slate-200 break-all">{found === true ? `Found: ${game.campaign_exe}` : found === false ? "Not found — campaign files were not detected" : "Unknown — update the companion and rescan"}</dd></div>
      <div><dt>Multiplayer executable (not campaign)</dt><dd data-testid={`${testid}-multiplayer-file`} className="font-mono text-slate-200 break-all">{game.multiplayer_exe || (typeof found === "boolean" ? "Not found" : "Unknown")}</dd></div>
      <div><dt>Steam / library build (not loader compatibility)</dt><dd data-testid={`${testid}-library-build`} className="font-mono text-slate-200">{game.game_version || "Unknown"}</dd></div>
    </dl>
    <p data-testid={`${testid}-helper-note`} className="text-slate-400">DLogUploader.exe is a helper, not the game. A multiplayer executable or a detected campaign file is not evidence that campaign mods can load.</p>
    <p data-testid={`${testid}-update-note`} className="text-slate-400">Use companion 0.3.1 or newer, then Rescan now in My PC. Detection only reads installation metadata; it does not launch the game, install tools, change game files or spend AI credits.</p>
    <p data-testid={`${testid}-limits`} className="text-slate-400">S2MP-Mod documents Multiplayer/Zombies, not campaign hosting. S2x describes modding support as unfinished. A verified campaign loader and matching retail-build compatibility are still needed; single-player use is not a permission or account-safety guarantee.</p>
    <div className="space-y-2">
      <a data-testid={`${testid}-campaign-source`} href="https://steamdb.info/depot/476601/" target="_blank" rel="noopener noreferrer" className="block text-cyan-300 hover:underline">Steam campaign binary depot</a>
      <a data-testid={`${testid}-mp-source`} href="https://github.com/Rattpak/S2MP-Mod" target="_blank" rel="noopener noreferrer" className="block text-cyan-300 hover:underline">S2MP-Mod scope</a>
      <a data-testid={`${testid}-s2x-source`} href="https://github.com/Brentdevent/S2x" target="_blank" rel="noopener noreferrer" className="block text-cyan-300 hover:underline">S2x development status</a>
    </div>
    {chooseHost && <Button asChild data-testid={`${testid}-choose-host`} variant="outline" className="w-full border-cyan-700 text-cyan-200 text-xs"><Link to={`/?${new URLSearchParams({ host: game.name, device_id: game.device_id })}`}>Keep WWII campaign as intended host</Link></Button>}
    <div className="flex flex-wrap gap-2">{["Build mod", "Install mod", "Launch mod"].map((label, i) => <Button data-testid={`${testid}-blocked-${i}`} key={label} disabled variant="outline" size="sm" aria-describedby={`${testid}-blocked-reason`} className="text-xs border-slate-700">{label}</Button>)}</div>
    <p data-testid={`${testid}-blocked-reason`} id={`${testid}-blocked-reason`} className="text-amber-200">These actions remain unavailable. Recognition is fixed, but no working campaign host integration is claimed.</p>
  </section>;
};

export const ENGINE = { redengine4: "REDengine 4", s2: "Sledgehammer S2 (WWII)", "unity-mono": "Unity (Mono)", "unity-il2cpp": "Unity (IL2CPP)", unreal: "Unreal Engine 4/5", unreal3: "Unreal Engine 3", "re-engine": "RE Engine", unknown: "Unknown engine" };
const TOOLCHAIN = { "cet-lua": "Cyber Engine Tweaks · Lua", "bepinex5-csharp": "BepInEx 5 · C#", "ue3-unrealscript": "Game SDK · UnrealScript", "ue4ss-lua": "UE4SS · Lua" };

export function Facts({ g }) {
  const coldWar = isColdWar(g);
  const rows = isWWII(g) ? [
    ["Mode", "WWII single-player campaign"], ["Host support", "Unverified — not supported"],
    ["Campaign", g.campaign_executable_found === true ? g.campaign_exe : g.campaign_executable_found === false ? "Not found" : "Unknown — rescan with 0.3.1"],
    ["Library build", g.game_version || "Unknown"],
  ] : coldWar ? [
    ["Detected", "Installation recorded"], ["Host support", "Unverified — not supported"],
    ["File version", g.executable_version || "Unknown"],
    ["Store", { steam: "Steam", epic: "Epic Games", gog: "GOG", "battle.net": "Battle.net" }[g.source] || "Unknown"],
  ] : [
    ["Version", g.game_version || "not reported"],
    ["Engine", ENGINE[g.engine] || g.engine],
    ...(g.engine?.startsWith("unity") ? [["Unity", g.unity_version || "—"]] : []),
    ["Mod toolchain", g.toolchain ? TOOLCHAIN[g.toolchain] : "—"],
    ["Mod loader", g.loader_installed ? "installed" : "none yet"],
    ["Adapter", `${g.adapter_id || "none"}${g.adapter_status ? ` (${g.adapter_status})` : ""}`],
    ["Store", g.store_locked ? "Xbox / Game Pass" : g.source],
  ];
  return (
    <dl className="grid grid-cols-[96px_1fr] gap-y-1.5 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents"><dt className="text-slate-500">{k}</dt><dd className="font-mono text-slate-200 truncate">{v}</dd></div>
      ))}
    </dl>
  );
}

export default function GameDetailsSheet({ game, onClose }) {
  const [d, setD] = useState(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (game) api.get("/games/details", { params: { device_id: game.device_id, install_dir: game.install_dir } }).then((r) => setD(r.data)).catch(() => setD({ error: true }));
    else setD(null);
  }, [game, tick]);
  return (
    <Sheet open={!!game} onOpenChange={(o) => !o && onClose()}>
      <SheetContent data-testid="game-details-drawer" className="bg-[#0f1118] border-slate-800 w-full sm:w-[440px] sm:max-w-[440px] overflow-y-auto scroll-thin">
        {game && (
          <>
            <SheetHeader className="mb-4">
              {game.steam_appid && <img src={`https://cdn.cloudflare.steamstatic.com/steam/apps/${game.steam_appid}/header.jpg`} alt="" className="rounded-lg mb-3" onError={(e) => { e.currentTarget.style.display = "none"; }} />}
              <SheetTitle data-testid="game-details-name" className="font-display text-2xl text-left">{game.name}</SheetTitle>
              <SheetDescription data-testid="game-details-install-path" className="text-[11px] font-mono text-slate-500 break-all text-left">{game.install_dir}</SheetDescription>
            </SheetHeader>
            {isColdWar(game) ? <ColdWarCompatibility game={game} testid="cold-war-drawer" chooseHost /> : isWWII(game) ? <WwiiCampaignStatus game={d?.game || game} testid="wwii-drawer" chooseHost /> : <Facts g={game} />}
            {d && !d.error && !isColdWar(game) && !isWWII(game) && (
              <div className="mt-6 space-y-6">
                <div className="flex items-center gap-2 text-xs" data-testid="game-details-buildable">
                  {d.game.hostable ? <Check className="w-4 h-4 text-emerald-400" /> : <X className="w-4 h-4 text-rose-400" />}
                  {d.game.hostable ? "Can be a host: mods for this game can be built and tested" : "Can't host — it can still be a game to borrow from."}
                  <span className="ml-auto text-slate-500">{d.game.managed_count} game code files</span>
                </div>
                {d.game.host_reason && <p data-testid="game-details-reason" className={`text-xs ${d.game.hostable ? "text-cyan-300" : "text-amber-300"}`}>{d.game.host_reason}</p>}
                <ModToolsPanel game={d.game} onChanged={() => setTimeout(() => setTick((t) => t + 1), 1500)} />
                {d.adapter && (
                  <div>
                    <div className="flex items-center gap-2 mb-2"><h4 className="font-display font-semibold text-sm">{d.adapter.name}</h4><StatusBadge status={d.adapter.status === "unsupported" ? "failed" : d.adapter.status === "documented" ? "built" : "partial"} label={d.adapter.status} /></div>
                    {d.adapter.loader && <p className="text-xs font-mono text-slate-400 mb-2">{d.adapter.loader.name} {d.adapter.loader.version}{d.adapter.target_framework ? ` · ${d.adapter.target_framework}` : ""}</p>}
                    <div className="md max-h-48 overflow-auto scroll-thin border border-slate-800 rounded-lg p-3"><ReactMarkdown>{d.adapter.doc_md}</ReactMarkdown></div>
                  </div>
                )}
                <div data-testid="game-details-notes">
                  <h4 className="font-display font-semibold text-sm mb-2">What worked before ({d.notes.length})</h4>
                  {d.notes.length === 0 ? <p className="text-xs text-slate-500">No notes yet. They're added after real builds and tests.</p>
                    : d.notes.map((n) => <div key={n.id} className="text-xs py-1.5 border-t border-slate-800/60"><span className="font-mono text-cyan-400 mr-2">{n.game_version || "any"}</span>{n.note}<span className="text-slate-500 ml-1">· {n.source} {ago(n.created_at)}</span></div>)}
                </div>
                {d.mods.length > 0 && (
                  <div>
                    <h4 className="font-display font-semibold text-sm mb-2">Your mods using it</h4>
                    {d.mods.map((m) => <Link key={m.id} to={`/mods/${m.id}`} className="flex items-center gap-2 text-xs py-1.5 hover:text-cyan-300">{m.title}<StatusBadge status={m.build_status} /></Link>)}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
