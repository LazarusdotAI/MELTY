import { useEffect, useRef, useState } from "react";
import { Upload, Wand2, Trash2, Loader2, Music, Image as ImageIcon } from "lucide-react";
import { toast } from "sonner";
import { api, BACKEND, errMsg, usd } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";

export default function AssetsPage() {
  const [items, setItems] = useState([]);
  const [sfx, setSfx] = useState({ enabled: false });
  const [prompt, setPrompt] = useState("");
  const [dur, setDur] = useState(2);
  const [busy, setBusy] = useState(false);
  const ref = useRef();
  const load = () => api.get("/assets").then((r) => setItems(r.data));
  useEffect(() => { load(); api.get("/sfx/status").then((r) => setSfx(r.data)); }, []);
  const upload = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const fd = new FormData();
    fd.append("file", f);
    fd.append("license", "User-provided — you confirm you may use it");
    try { await api.post("/assets/upload", fd); toast.success("Uploaded"); load(); } catch (er) { toast.error(errMsg(er)); }
  };
  const gen = async () => {
    setBusy(true);
    try { const r = await api.post("/sfx/generate", { prompt, duration: dur }); toast.success(`Generated (${usd(r.data.cost)})`); setPrompt(""); load(); } catch (e) { toast.error(errMsg(e)); }
    setBusy(false);
  };
  return (
    <main className="px-8 py-10 max-w-[1300px] mx-auto">
      <p className="font-mono text-xs text-cyan-400 tracking-widest uppercase mb-3">Asset vault</p>
      <h1 className="font-display text-4xl sm:text-5xl font-extrabold tracking-tight mb-2">Your own assets</h1>
      <p className="text-sm text-slate-400 mb-8 max-w-2xl">Original or licensed sounds and textures you can use in mods. Assets from games you own are read from your install at runtime and never uploaded.</p>
      <div className="grid md:grid-cols-2 gap-5 mb-8">
        <div className="panel p-5">
          <h3 className="font-display font-semibold mb-1">Upload</h3>
          <p className="text-xs text-slate-500 mb-3">png, jpg, wav, ogg, mp3 up to 8 MB</p>
          <input ref={ref} type="file" className="hidden" onChange={upload} data-testid="asset-file-input" />
          <Button data-testid="asset-upload-button" onClick={() => ref.current.click()} variant="outline" className="border-slate-700"><Upload className="w-4 h-4 mr-1" /> Choose file</Button>
        </div>
        <div className="panel p-5" data-testid="sfx-panel">
          <h3 className="font-display font-semibold mb-1">Sound effects · ElevenLabs</h3>
          {sfx.enabled ? <p className="text-xs text-slate-500 mb-3">≈ {usd(sfx.cost_per_second)} per second, counted in your daily limit</p>
            : <p className="text-xs text-amber-300 mb-3" data-testid="sfx-disabled">Not connected. Add your ElevenLabs API key to turn this on.</p>}
          <div className="flex gap-2">
            <Input data-testid="sfx-prompt-input" disabled={!sfx.enabled} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="metallic dash whoosh with spark" className="bg-[#0a0b0e] border-slate-800 text-sm" />
            <Input data-testid="sfx-duration-input" disabled={!sfx.enabled} type="number" min={0.5} max={10} step={0.5} value={dur} onChange={(e) => setDur(Number(e.target.value))} className="w-20 bg-[#0a0b0e] border-slate-800 text-sm" />
            <Button data-testid="sfx-generate-button" disabled={!sfx.enabled || prompt.length < 3 || busy} onClick={gen} className="bg-violet-500 hover:bg-violet-400 disabled:bg-slate-700 disabled:text-slate-400">{busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wand2 className="w-4 h-4" />}</Button>
          </div>
        </div>
      </div>
      <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4" data-testid="asset-grid">
        {items.map((a) => (
          <div key={a.id} className="panel p-4 group" data-testid={`asset-${a.id}`}>
            <div className="flex items-center gap-2 mb-3">{a.kind === "sfx" ? <Music className="w-4 h-4 text-violet-300" /> : <ImageIcon className="w-4 h-4 text-cyan-300" />}<span className="text-sm truncate flex-1">{a.name}</span>
              <button data-testid={`asset-delete-${a.id}`} onClick={async () => { await api.delete(`/assets/${a.id}`); load(); }} className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-rose-400"><Trash2 className="w-4 h-4" /></button></div>
            {a.kind === "sfx" ? <audio controls src={`${BACKEND}${a.url}`} className="w-full h-8" /> : <img src={`${BACKEND}${a.url}`} alt={a.name} className="w-full h-32 object-contain bg-[#0a0b0e] rounded" />}
            <p className="text-[10px] text-slate-500 mt-2">{a.source} · {a.license}</p>
          </div>
        ))}
        {items.length === 0 && <p className="text-sm text-slate-500">No assets yet.</p>}
      </div>
    </main>
  );
}
