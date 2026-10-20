import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Square, Loader2, Clock, X, Check, CircleDashed, Wrench, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg } from "../../lib/api";
import { Textarea } from "../ui/textarea";
import Progress from "./Progress";
import Approvals from "./Approvals";
import PlayActions from "./PlayActions";
import TechDetails from "./TechDetails";

const STATUS = { verified: ["Working in your game", "text-emerald-300 border-emerald-500/40"], built: ["Ready to try", "text-amber-200 border-amber-500/40"], unbuilt: ["Not built yet", "text-slate-400 border-slate-700"] };

const STAGES = [["built", "Built"], ["installed", "Installed"], ["loaded", "Loaded in game"], ["confirmed", "Confirmed"]];

function Stages({ stage }) {
  const at = STAGES.findIndex(([k]) => k === stage);
  return (
    <div className="hidden lg:flex items-center gap-1 text-[11px]" data-testid="mod-stage" data-stage={stage || "planned"}>
      {STAGES.map(([k, l], i) => <span key={k} data-testid={`stage-${k}`} className={`px-2 py-0.5 rounded-full ${i <= at ? "bg-emerald-500/15 text-emerald-200" : "text-slate-600"}`}>{l}</span>)}
    </div>
  );
}

function Features({ list }) {
  if (!list?.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5" data-testid="message-features">
      {list.map((f) => (
        <span key={f.name} data-testid={`feature-${f.name}`} className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border ${f.pass ? "border-emerald-500/40 text-emerald-200" : f.seen ? "border-rose-500/40 text-rose-200" : "border-slate-700 text-slate-400"}`}>
          {f.pass ? <Check className="w-3 h-3" /> : f.seen ? <X className="w-3 h-3" /> : <CircleDashed className="w-3 h-3" />}{f.name.replace(/_/g, " ")}
        </span>
      ))}
    </div>
  );
}

function Bubble({ m, mod, busy, onChange }) {
  if (m.role === "user") {
    return (
      <div data-testid={m.queued ? "queued-message" : "user-message"} className={`ml-auto max-w-[80%] rounded-2xl rounded-br-md px-4 py-2.5 text-sm whitespace-pre-wrap bg-cyan-500/10 border ${m.queued ? "border-dashed border-cyan-500/50" : "border-cyan-500/20"}`}>
        {m.queued && (
          <div className="flex items-center gap-2 text-[11px] text-cyan-300 mb-1">
            <Clock className="w-3 h-3" /> {busy ? "In line — starts after the current job" : "Waiting to start"}
            {!busy && <button data-testid="start-queued-message" onClick={() => api.post(`/mods/${mod.id}/queue/start`).then(onChange).catch((e) => toast.error(errMsg(e)))} className="hover:underline">Start now</button>}
            <button data-testid="remove-queued-message" title="Remove" onClick={() => api.delete(`/mods/${mod.id}/queue/${m.id}`).then(onChange).catch((e) => toast.error(errMsg(e)))} className="ml-auto text-slate-500 hover:text-rose-300"><X className="w-3 h-3" /></button>
          </div>
        )}
        {m.content}
      </div>
    );
  }
  return (
    <div data-testid={m.role === "system" ? "system-message" : "assistant-message"} className={`mr-8 max-w-[85%] text-sm whitespace-pre-wrap leading-relaxed ${m.role === "system" ? "rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-2.5 text-amber-100" : "text-slate-200"}`}>
      {m.content}<Features list={m.features} />
    </div>
  );
}

function useMod(id) {
  const [s, setS] = useState({ mod: null, messages: [], gen: null, play: null, missing: false });
  const load = useCallback(async () => {
    try {
      const [m, msg, play] = await Promise.all([api.get(`/mods/${id}`), api.get(`/mods/${id}/messages`), api.get(`/mods/${id}/play`)]);
      const gid = m.data.active_generation_id || (await api.get(`/mods/${id}/generations`)).data[0]?.id;
      const gen = gid ? (await api.get(`/generations/${gid}`)).data : null;
      setS({ mod: m.data, messages: msg.data, gen, play: play.data, missing: false });
    } catch (e) { if (e?.response?.status === 404) setS((x) => ({ ...x, missing: true })); }
  }, [id]);
  const busy = !!s.mod?.active_generation_id;
  useEffect(() => { load(); }, [load]);
  useEffect(() => { const t = setInterval(load, busy || s.play?.checking ? 2500 : 7000); return () => clearInterval(t); }, [busy, s.play?.checking, load]);
  return { ...s, busy, load };
}

export default function ModChat({ id }) {
  const { mod, messages, gen, play, missing, busy, load } = useMod(id);
  const key = `chat-draft-${id}`;
  const [text, setTextRaw] = useState(() => localStorage.getItem(key) || "");
  const setText = (v) => { setTextRaw(v); v ? localStorage.setItem(key, v) : localStorage.removeItem(key); };
  const [sending, setSending] = useState(false);
  const [details, setDetails] = useState(false);
  const [stopping, setStopping] = useState("");
  const end = useRef();
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [messages.length, busy]);
  if (missing) return <div className="p-10 text-slate-400" data-testid="mod-not-found">This mod doesn't exist any more.</div>;
  if (!mod) return <div className="p-10 text-slate-500">Loading…</div>;
  const send = async () => {
    const m = text.trim();
    if (!m) return;
    setSending(true);
    try {
      const r = await api.post(`/mods/${id}/chat`, { message: m });
      setText("");
      if (r.data.queued) toast("Got it — I'll do that right after the current job.");
      load();
    } catch (e) { toast.error(errMsg(e)); }
    setSending(false);
  };
  const stop = () => { setStopping(mod.active_generation_id); api.post(`/generations/${mod.active_generation_id}/cancel`).then(() => { toast("Stopping after this step. Your progress is kept."); load(); }).catch((e) => { setStopping(""); toast.error(errMsg(e)); }); };
  const isStopping = busy && stopping === mod.active_generation_id;
  const [label, tone] = isStopping ? ["Stopping…", "text-rose-200 border-rose-500/40"] : busy ? ["Working…", "text-cyan-200 border-cyan-500/40"] : STATUS[mod.build_status] || STATUS.unbuilt;
  return (
    <div className="h-full flex flex-col" data-testid="mod-chat">
      <div className="px-5 py-3 border-b border-slate-800/80 flex items-center gap-3">
        <div className="min-w-0">
          <h1 data-testid="mod-title" className="font-display text-lg font-bold truncate">{mod.title}</h1>
          <p className="text-xs text-slate-500 truncate">{mod.host.name}{mod.secondary?.map((s) => ` + ${s.name}`).join("")}</p>
        </div>
        <span data-testid="mod-build-status" className={`shrink-0 text-[11px] px-2 py-0.5 rounded-full border ${tone}`}>{label}</span>
        <div className="ml-auto"><Stages stage={play?.stage} /></div>
        <button data-testid="open-tech-details" onClick={() => setDetails(true)} className=" flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-100"><SlidersHorizontal className="w-3.5 h-3.5" /> Technical details</button>
      </div>
      <div className="flex-1 overflow-auto scroll-thin" data-testid="chat-messages">
        <div className="max-w-3xl mx-auto px-5 py-6 flex flex-col gap-4">
          {mod.description && <div className="ml-auto max-w-[80%] rounded-2xl rounded-br-md px-4 py-2.5 text-sm bg-cyan-500/10 border border-cyan-500/20 whitespace-pre-wrap" data-testid="original-request">{mod.description}</div>}
          {messages.map((m) => <Bubble key={m.id} m={m} mod={mod} busy={busy} onChange={load} />)}
          {busy && <Progress gen={gen} />}
          {mod.hosting_blocked_reason && <p data-testid="chat-blocked-reason" className="text-xs text-amber-200">{mod.hosting_blocked_reason}</p>}
          <div ref={end} />
        </div>
      </div>
      <div className="border-t border-slate-800/80 bg-[#08090d]">
        <div className="max-w-3xl mx-auto px-5 py-3 space-y-3">
          <Approvals deviceId={mod.device_id} />
          <PlayActions mod={mod} play={play} busy={busy} onDone={load} />
          <div className="rounded-2xl border border-slate-700 bg-[#0d0f15] focus-within:border-cyan-500/60 transition-colors p-2 flex items-end gap-2">
            <Textarea data-testid="chat-input" value={text} disabled={!!mod.hosting_blocked_reason} onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder={busy ? "Type anyway — it waits in line until I'm done" : mod.build_status === "built" ? "Ask for a change, or say “fix it”…" : "Ask for a change…"}
              className="border-0 bg-transparent min-h-[44px] max-h-40 text-sm focus-visible:ring-0 resize-none" />
            {busy && <button data-testid="cancel-generation" onClick={stop} disabled={isStopping} title={isStopping ? "Stopping…" : "Stop"} className="w-9 h-9 shrink-0 rounded-full grid place-items-center border border-slate-600 text-slate-200 hover:border-rose-400 hover:text-rose-300 disabled:opacity-50 transition-colors">{isStopping ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Square className="w-3.5 h-3.5" />}</button>}
            <button data-testid="chat-send" disabled={sending || !text.trim() || !!mod.hosting_blocked_reason} onClick={send} aria-label="Send"
              className="w-9 h-9 shrink-0 rounded-full grid place-items-center bg-cyan-500 text-[#08090d] disabled:bg-slate-800 disabled:text-slate-500 hover:bg-cyan-400 transition-colors">
              {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowUp className="w-4 h-4" />}
            </button>
          </div>
          {!busy && !play?.built && !mod.hosting_blocked_reason && messages.length > 0 && <p className="text-[11px] text-slate-500 flex items-center gap-1"><Wrench className="w-3 h-3" /> Not built yet — make sure your PC is online, then ask me to build it.</p>}
        </div>
      </div>
      <TechDetails open={details} onOpenChange={setDetails} mod={mod} gen={gen} busy={busy} onChange={load} />
    </div>
  );
}
