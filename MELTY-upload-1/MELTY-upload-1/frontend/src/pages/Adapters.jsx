import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";
import { api, ago } from "../lib/api";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import StatusBadge from "../components/StatusBadge";

export default function Adapters() {
  const [items, setItems] = useState([]);
  const [sel, setSel] = useState(null);
  const [note, setNote] = useState("");
  const [ver, setVer] = useState("");
  const load = () => api.get("/adapters").then((r) => { setItems(r.data); setSel((s) => r.data.find((a) => a.id === s?.id) || r.data[0]); });
  useEffect(() => { load(); }, []);
  const add = async () => {
    await api.post("/knowledge", { game: sel.name, note, game_version: ver });
    setNote(""); setVer("");
    toast.success("Note saved — the AI will read it next time");
    load();
  };
  const tone = (s) => (s === "documented" ? "built" : s === "unsupported" ? "failed" : "partial");
  return (
    <main className="px-8 py-10 max-w-[1400px] mx-auto">
      <p className="font-mono text-xs text-cyan-400 tracking-widest uppercase mb-3">Adapter library</p>
      <h1 className="font-display text-4xl sm:text-5xl font-extrabold tracking-tight mb-2">What works, per game</h1>
      <p className="text-slate-400 text-sm mb-8 max-w-2xl">Engine and game adapters list the loaders, supported versions and integration methods. Notes saved by you or the AI after real tests are added to every future build prompt for that game.</p>
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 md:col-span-4 panel divide-y divide-slate-800">
          {items.map((a) => (
            <button key={a.id} data-testid={`adapter-${a.id}`} onClick={() => setSel(a)} className={`w-full text-left px-4 py-3 ${sel?.id === a.id ? "bg-cyan-500/5" : "hover:bg-slate-900/50"}`}>
              <div className="flex items-center gap-2"><span className="font-display font-semibold flex-1">{a.name}</span><StatusBadge status={tone(a.status)} label={a.status} /></div>
              <div className="text-[11px] text-slate-500 font-mono">{a.kind} · {a.engine} · {a.notes.length} notes</div>
            </button>
          ))}
        </div>
        {sel && (
          <div className="col-span-12 md:col-span-8 space-y-5">
            <div className="panel p-5">
              <div className="flex flex-wrap gap-2 mb-4 text-xs">
                {sel.loader && <span className="px-2 py-1 rounded border border-slate-700 font-mono">{sel.loader.name} {sel.loader.version}</span>}
                {(sel.integration_methods || []).map((m) => <span key={m} className="px-2 py-1 rounded border border-violet-500/40 text-violet-200">{m}</span>)}
                {sel.target_framework && <span className="px-2 py-1 rounded border border-slate-700 font-mono">{sel.target_framework}</span>}
              </div>
              <div className="md" data-testid="adapter-doc"><ReactMarkdown remarkPlugins={[remarkGfm]}>{sel.doc_md}</ReactMarkdown></div>
            </div>
            <div className="panel p-5" data-testid="knowledge-panel">
              <h3 className="font-display font-semibold mb-3">Knowledge notes</h3>
              <div className="flex gap-2 mb-4">
                <Input data-testid="note-version-input" value={ver} onChange={(e) => setVer(e.target.value)} placeholder="Game version" className="w-36 bg-[#0a0b0e] border-slate-800 text-xs" />
                <Input data-testid="note-input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. PlayerController.Move is the right hook for dash" className="bg-[#0a0b0e] border-slate-800 text-xs" />
                <Button data-testid="add-note-button" size="sm" disabled={!note.trim()} onClick={add} className="bg-cyan-500 hover:bg-cyan-400 text-[#08090d]">Add</Button>
              </div>
              {sel.notes.length === 0 && <p className="text-sm text-slate-500">No notes yet.</p>}
              {sel.notes.map((n) => <div key={n.id} className="text-sm py-2 border-t border-slate-800/60"><span className="font-mono text-[11px] text-cyan-400 mr-2">{n.game_version || "any"}</span>{n.note}<span className="text-[11px] text-slate-500 ml-2">{n.source} · {ago(n.created_at)}</span></div>)}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
