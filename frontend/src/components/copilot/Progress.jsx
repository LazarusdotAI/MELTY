import { Check, X, Loader2, Circle } from "lucide-react";

const ASSET = /asset|extract|convert|container|package/i;

export function steps(gen) {
  const ev = gen?.events || [];
  const has = (f) => ev.some(f);
  const last = (f) => [...ev].reverse().find(f);
  const build = last((e) => /^Build (succeeded|failed)/.test(e.text || ""));
  const test = last((e) => e.type === "test_pass" || e.type === "test_fail");
  const list = [
    gen.kind === "create" && { k: "plan", label: "Plan the mod", s: has((e) => e.text === "Design spec ready") ? "done" : "todo" },
    has((e) => e.type !== "ai" && ASSET.test(e.text || "")) && { k: "assets", label: "Work with the game's files", s: "done" },
    { k: "write", label: "Write the code", s: has((e) => e.type === "file") ? "done" : "todo" },
    { k: "build", label: "Build it on your PC", s: build ? (build.text.startsWith("Build succeeded") ? "done" : "fail") : "todo" },
    { k: "test", label: "Try it in the game", s: test ? (test.type === "test_pass" ? "done" : "fail") : "todo" },
  ].filter(Boolean);
  if (["running", "queued"].includes(gen.status)) {
    const i = list.findIndex((x) => x.s === "todo");
    if (i >= 0) list[i].s = "doing";
  }
  return list;
}

const ICON = {
  done: <Check className="w-3.5 h-3.5 text-emerald-300" />, fail: <X className="w-3.5 h-3.5 text-rose-300" />,
  doing: <Loader2 className="w-3.5 h-3.5 text-cyan-300 animate-spin" />, todo: <Circle className="w-3 h-3 text-slate-600" />,
};

export default function Progress({ gen }) {
  if (!gen) return null;
  const waiting = [...(gen.events || [])].reverse().find((e) => e.type !== "cost")?.text?.startsWith("Waiting for your");
  return (
    <div data-testid="copilot-progress" className="rounded-xl border border-slate-800 bg-[#0d0f15] px-4 py-3 mr-8 space-y-1.5">
      {steps(gen).map((s) => (
        <div key={s.k} data-testid={`progress-${s.k}`} data-state={s.s} className={`flex items-center gap-2.5 text-sm ${s.s === "todo" ? "text-slate-500" : "text-slate-200"}`}>
          <span className="w-4 grid place-items-center">{ICON[s.s]}</span>{s.label}
        </div>
      ))}
      {waiting && <p data-testid="progress-waiting-approval" className="text-xs text-amber-200 pt-1">Waiting for your OK below.</p>}
    </div>
  );
}
