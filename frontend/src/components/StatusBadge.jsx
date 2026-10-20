import { CheckCircle2, XCircle, CircleDashed, AlertTriangle, Loader2 } from "lucide-react";

const MAP = {
  verified: ["text-emerald-300 bg-emerald-500/10 border-emerald-500/30", CheckCircle2],
  done: ["text-emerald-300 bg-emerald-500/10 border-emerald-500/30", CheckCircle2],
  built: ["text-cyan-300 bg-cyan-500/10 border-cyan-500/30", CheckCircle2],
  installed: ["text-cyan-300 bg-cyan-500/10 border-cyan-500/30", CheckCircle2],
  restored: ["text-slate-300 bg-slate-500/10 border-slate-500/30", CheckCircle2],
  partial: ["text-amber-300 bg-amber-500/10 border-amber-500/30", AlertTriangle],
  paused: ["text-amber-300 bg-amber-500/10 border-amber-500/30", AlertTriangle],
  needs_approval: ["text-amber-300 bg-amber-500/10 border-amber-500/30", AlertTriangle],
  failed: ["text-rose-300 bg-rose-500/10 border-rose-500/30", XCircle],
  cancelled: ["text-slate-400 bg-slate-500/10 border-slate-600/30", XCircle],
  running: ["text-violet-300 bg-violet-500/10 border-violet-500/30", Loader2],
  queued: ["text-violet-300 bg-violet-500/10 border-violet-500/30", Loader2],
};

export default function StatusBadge({ status, label, testid }) {
  const [cls, Icon] = MAP[status] || ["text-slate-400 bg-slate-500/10 border-slate-600/30", CircleDashed];
  const spin = status === "running" || status === "queued";
  return (
    <span data-testid={testid} className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border ${cls}`}>
      <Icon className={`w-3 h-3 ${spin ? "animate-spin" : ""}`} /> {label || (status || "untested").replace("_", " ")}
    </span>
  );
}
