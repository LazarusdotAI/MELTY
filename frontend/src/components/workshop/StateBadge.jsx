import { CheckCircle2, Loader2, XCircle, Ban, ShieldAlert, Clock } from "lucide-react";

export const STATE_STYLE = {
  Pending: ["text-slate-300 border-slate-600 bg-slate-500/10", Clock],
  Running: ["text-cyan-300 border-cyan-500/40 bg-cyan-500/10", Loader2],
  Completed: ["text-emerald-300 border-emerald-500/40 bg-emerald-500/10", CheckCircle2],
  Failed: ["text-rose-300 border-rose-500/40 bg-rose-500/10", XCircle],
  Unsupported: ["text-amber-200 border-amber-500/40 bg-amber-500/10", Ban],
  "Permission Required": ["text-violet-200 border-violet-500/40 bg-violet-500/10", ShieldAlert],
};

export const LEVEL_STYLE = {
  possible_with_conversion: "text-emerald-300",
  possible_recreated_equivalent: "text-cyan-300",
  possible_not_implemented: "text-amber-200",
  unsupported_by_toolkit: "text-amber-300",
  blocked_by_protection: "text-rose-300",
  impossible: "text-rose-400",
};

export const bytes = (n) => (n == null ? "" : n > 1e9 ? `${(n / 1e9).toFixed(2)} GB` : n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n > 1e3 ? `${(n / 1e3).toFixed(1)} KB` : `${n} B`);

export default function StateBadge({ state, testid }) {
  const [cls, Icon] = STATE_STYLE[state] || STATE_STYLE.Pending;
  return (
    <span data-testid={testid} className={`inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border whitespace-nowrap ${cls}`}>
      <Icon className={`w-3 h-3 ${state === "Running" ? "animate-spin" : ""}`} /> {state}
    </span>
  );
}
