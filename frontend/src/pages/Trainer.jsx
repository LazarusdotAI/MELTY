import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Power, RotateCcw, ShieldOff, Undo2, Save, Download, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg } from "../lib/api";
import { Button } from "../components/ui/button";
import { Switch } from "../components/ui/switch";
import { Slider } from "../components/ui/slider";
import { Input } from "../components/ui/input";

const ST = {
  Active: "text-emerald-300 border-emerald-500/40", Available: "text-cyan-200 border-cyan-500/40", "Needs Testing": "text-amber-200 border-amber-500/40",
  "Requires Build": "text-slate-300 border-slate-600", "Install First": "text-slate-300 border-slate-600", "Requires Restart": "text-violet-200 border-violet-500/40", Unsupported: "text-slate-500 border-slate-700", Broken: "text-rose-300 border-rose-500/40",
};

function Feature({ f, v, set }) {
  const disabled = ["Requires Build", "Install First", "Unsupported"].includes(f.status);
  return (
    <div className={`border border-slate-800 rounded-lg p-3 space-y-2 ${disabled ? "opacity-60" : ""}`} data-testid={`trainer-feature-${f.key}`}>
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium mr-auto">{f.label}</span>
        <span data-testid={`trainer-status-${f.key}`} className={`text-[10px] px-1.5 py-0.5 rounded border ${ST[f.status]}`}>{f.status}</span>
        <Switch data-testid={`trainer-toggle-${f.key}`} disabled={disabled} checked={!!v.on} onCheckedChange={(on) => set({ ...v, on })} />
      </div>
      {f.kind === "slider" && !disabled && (
        <div className="flex items-center gap-3">
          <Slider data-testid={`trainer-slider-${f.key}`} min={f.min} max={f.max} step={f.max - f.min > 5 ? 1 : 0.1} value={[v.value ?? f.default ?? f.min]} onValueChange={([x]) => set({ ...v, value: x })} className="flex-1" />
          <span className="text-xs font-mono w-10 text-right">{Number(v.value ?? f.default ?? f.min).toFixed(f.max - f.min > 5 ? 0 : 1)}</span>
        </div>
      )}
      {f.kind === "select" && !disabled && (
        <select data-testid={`trainer-select-${f.key}`} value={v.value || ""} onChange={(e) => set({ ...v, value: e.target.value })} className="w-full bg-[#0a0b0e] border border-slate-800 rounded text-xs px-2 py-1">
          <option value="">Choose…</option>{(f.options || []).map((o) => <option key={o} value={o}>{o.replace("24h_weather_", "")}</option>)}
        </select>
      )}
      <p className="text-[11px] text-slate-500">{f.why || f.desc}</p>
    </div>
  );
}

export default function Trainer() {
  const [games, setGames] = useState([]);
  const [params] = useSearchParams();
  const [dir, setDir] = useState(params.get("game") || localStorage.getItem("trainer-game") || "");
  const dev = localStorage.getItem("ws-device") || undefined;
  const [t, setT] = useState(null);
  const [vals, setVals] = useState({});
  const [preset, setPreset] = useState("");
  useEffect(() => { api.get("/workshop/games", { params: { device_id: dev } }).then((r) => setGames(r.data.games.filter((g) => ["redengine4", "unreal"].includes(g.engine)))).catch(() => {}); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const load = useCallback(async (resetVals) => {
    if (!dir) return;
    try {
      const r = await api.get("/trainer/game", { params: { install_dir: dir, device_id: dev } });
      setT(r.data);
      if (resetVals) setVals(Object.fromEntries(r.data.features.map((f) => [f.key, { on: f.on, value: f.value }])));
    } catch (e) { setT({ error: errMsg(e) }); }
  }, [dir, dev]);
  useEffect(() => { localStorage.setItem("trainer-game", dir); setT(null); load(true); const i = setInterval(() => load(false), 5000); return () => clearInterval(i); }, [dir, load]);
  const ref = t ? { install_dir: t.install_dir, device_id: t.device_id } : {};
  const post = async (path, body, msg) => { try { const r = await api.post(path, { ...ref, ...body }); if (msg) toast(msg); return r.data; } catch (e) { toast.error(errMsg(e)); } };
  const apply = async (features, emergency = false) => {
    const live = Object.fromEntries(Object.entries(features).filter(([k]) => t.features.find((f) => f.key === k && !["Requires Build", "Unsupported"].includes(f.status))));
    if (await post("/trainer/apply", { features: live, emergency }, emergency ? "Everything switched off" : "Sent to the game")) setTimeout(() => post("/trainer/refresh", {}), 2500);
  };
  const cats = t?.features ? [...new Set(t.features.map((f) => f.category))] : [];
  return (
    <div className="max-w-6xl mx-auto px-6 py-10 space-y-6" data-testid="trainer-page">
      <div className="flex flex-wrap items-end gap-4">
        <div className="mr-auto">
          <p className="text-xs uppercase tracking-[0.2em] text-cyan-400 font-mono">Trainer</p>
          <h1 className="font-display text-4xl sm:text-5xl font-bold mt-2">Switch things on in your game</h1>
          <p className="text-sm text-slate-400 mt-2">Single-player only. A switch only says Active after the game itself confirms it.</p>
        </div>
        <select data-testid="trainer-game-select" value={dir} onChange={(e) => setDir(e.target.value)} className="bg-[#0a0b0e] border border-slate-800 rounded-md text-sm px-3 py-2">
          <option value="">Choose a game…</option>{games.map((g) => <option key={g.install_dir} value={g.install_dir}>{g.name}</option>)}
        </select>
      </div>
      {t?.error && <p className="text-rose-300 text-sm" data-testid="trainer-error">{t.error}</p>}
      {t && !t.error && !t.supported && <p className="text-amber-200 text-sm" data-testid="trainer-unsupported">{t.reason}</p>}
      {t?.supported && (
        <>
          <div className="panel p-4 flex flex-wrap items-center gap-3 text-sm" data-testid="trainer-header">
            <b>{t.game}</b>
            <span className={t.live && t.tool_ok ? "text-emerald-300" : "text-amber-200"}>{!t.live ? "Live trainer not built for this game yet" : t.tool_ok ? "Mod tools ready" : "Mod tools need setup — open the game in Game Selector to set them up"}</span>
            <span className={t.installed ? "text-emerald-300" : "text-slate-400"}>{t.installed ? "Trainer installed" : "Trainer not installed"}</span>
            <span className={t.in_game ? "text-emerald-300" : "text-slate-400"} data-testid="trainer-in-game">{t.in_game ? "Game running — in a save" : "Not in game"}</span>
            <div className="ml-auto flex gap-2">
              {t.live && !t.installed && <Button data-testid="trainer-install" size="sm" disabled={!t.tool_ok} onClick={() => post("/trainer/install", {}, "Approve the install on My PC")} className="bg-cyan-500 hover:bg-cyan-400 text-[#08090d]"><Download className="w-4 h-4 mr-1" />Install trainer</Button>}
              <Button data-testid="trainer-refresh" size="sm" variant="outline" className="border-slate-700" onClick={() => post("/trainer/refresh", {}, "Checking the game…")}><RefreshCw className="w-4 h-4" /></Button>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button data-testid="trainer-apply" disabled={!t.installed} onClick={() => apply(vals)} className="bg-cyan-500 hover:bg-cyan-400 text-[#08090d]"><Power className="w-4 h-4 mr-1" />Apply to game</Button>
            <Button data-testid="trainer-reset" variant="outline" className="border-slate-700" disabled={!t.installed} onClick={() => { const off = Object.fromEntries(Object.keys(vals).map((k) => [k, { ...vals[k], on: false }])); setVals(off); apply(off); }}><RotateCcw className="w-4 h-4 mr-1" />Reset trainer</Button>
            <Button data-testid="trainer-emergency" variant="outline" className="border-rose-500/50 text-rose-300" disabled={!t.installed} onClick={() => { setVals(Object.fromEntries(Object.keys(vals).map((k) => [k, { ...vals[k], on: false }]))); apply({}, true); }}><ShieldOff className="w-4 h-4 mr-1" />Emergency disable</Button>
            {t.installed && t.install_id && <Button data-testid="trainer-restore" variant="outline" className="border-slate-700" onClick={() => window.confirm("Remove the trainer from the game and restore its files?") && post("/workshop/rollback", { install_id: t.install_id }, "Restoring the original game…")}><Undo2 className="w-4 h-4 mr-1" />Restore original game</Button>}
          </div>
          {cats.map((c) => (
            <div key={c} className="space-y-2">
              <h3 className="text-xs uppercase tracking-widest text-slate-500">{c}</h3>
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {t.features.filter((f) => f.category === c).map((f) => (
                  <div key={f.key} className="relative">
                    <Feature f={f} v={vals[f.key] || {}} set={(nv) => setVals((s) => ({ ...s, [f.key]: nv }))} />
                    {vals[f.key]?.on && <button data-testid={`trainer-reset-${f.key}`} onClick={() => { const n = { ...vals, [f.key]: { ...vals[f.key], on: false } }; setVals(n); apply(n); }} className="absolute bottom-2 right-3 text-[10px] text-slate-500 hover:text-rose-300">reset</button>}
                  </div>
                ))}
              </div>
            </div>
          ))}
          <div className="panel p-4 space-y-3" data-testid="trainer-presets">
            <div className="flex gap-2">
              <Input data-testid="preset-name-input" value={preset} onChange={(e) => setPreset(e.target.value)} placeholder="Preset name, e.g. Super Soldier" className="h-9 bg-[#0a0b0e] border-slate-800 text-sm max-w-xs" />
              <Button data-testid="preset-save" size="sm" disabled={!preset.trim()} onClick={async () => { await post("/trainer/presets", { name: preset, features: vals }, "Preset saved"); setPreset(""); load(false); }}><Save className="w-4 h-4 mr-1" />Save preset</Button>
            </div>
            {(t.presets || []).map((p, i) => {
              const skipped = Object.entries(p.features).filter(([k, v]) => v.on && ["Requires Build", "Unsupported"].includes(t.features.find((f) => f.key === k)?.status)).map(([k]) => k);
              return (
                <div key={p.id} className="flex items-center gap-2 text-sm" data-testid={`preset-row-${i}`}>
                  <span className="mr-auto">{p.name}{skipped.length > 0 && <span className="text-[11px] text-amber-200"> · skips {skipped.join(", ")} (not available)</span>}</span>
                  <button data-testid={`preset-load-${i}`} className="text-cyan-300 text-xs hover:underline" onClick={() => setVals(Object.fromEntries(Object.entries(p.features).map(([k, v]) => [k, skipped.includes(k) ? { ...v, on: false } : v])))}>Load</button>
                  <button data-testid={`preset-rename-${i}`} className="text-slate-400 text-xs hover:underline" onClick={() => { const n = window.prompt("New name", p.name); if (n) api.patch(`/trainer/presets/${p.id}`, { name: n }).then(() => load(false)); }}>Rename</button>
                  <button data-testid={`preset-delete-${i}`} className="text-slate-500 hover:text-rose-300" onClick={() => api.delete(`/trainer/presets/${p.id}`).then(() => load(false))}><Trash2 className="w-3.5 h-3.5" /></button>
                </div>
              );
            })}
            {t.live && <p className="text-[11px] text-slate-500">Hotkeys: open the Cyber Engine Tweaks overlay in game (~ key) → Bindings → MeltyTrainer. Custom MELTY hotkeys aren't built yet.</p>}
          </div>
        </>
      )}
    </div>
  );
}
