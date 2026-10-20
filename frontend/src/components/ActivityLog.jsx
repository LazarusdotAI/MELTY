import { useEffect, useState } from "react";
import { Image as ImageIcon, FileText } from "lucide-react";
import { api, BACKEND } from "../lib/api";
import StatusBadge from "./StatusBadge";

const COLOR = { cost: "text-slate-500", file: "text-cyan-300", test: "text-violet-300", test_pass: "text-emerald-300", test_fail: "text-rose-300", warn: "text-amber-300", error: "text-rose-400", done: "text-emerald-300", visual: "text-fuchsia-300", ai: "text-slate-200", step: "text-cyan-200" };

function Evidence({ jobId }) {
  const [job, setJob] = useState(null);
  useEffect(() => { api.get(`/jobs/${jobId}`).then((r) => setJob(r.data)).catch(() => {}); }, [jobId]);
  if (!job?.artifacts?.length) return null;
  const shot = job.artifacts.find((a) => a.name === "screenshot.png");
  return (
    <div className="flex flex-wrap gap-2 mt-1 items-start">
      {shot && <a href={`${BACKEND}/api/jobs/${job.id}/artifact/screenshot.png`} target="_blank" rel="noreferrer"><img data-testid={`screenshot-thumb-${job.id}`} src={`${BACKEND}/api/jobs/${job.id}/artifact/screenshot.png`} alt="In-game test screenshot" className="w-56 rounded border border-slate-700 hover:border-fuchsia-400" /></a>}
      {job.artifacts.map((a) => (
        <a key={a.name} data-testid={`artifact-${a.name}`} target="_blank" rel="noreferrer" href={`${BACKEND}/api/jobs/${job.id}/artifact/${a.name}`}
          className="text-[11px] flex items-center gap-1 px-2 py-0.5 rounded border border-slate-700 text-slate-300 hover:text-cyan-300">
          {a.name.endsWith(".png") ? <ImageIcon className="w-3 h-3" /> : <FileText className="w-3 h-3" />} {a.name}
        </a>
      ))}
    </div>
  );
}

export default function ActivityLog({ gen }) {
  if (!gen) return <p className="p-5 text-sm text-slate-500">No AI runs yet.</p>;
  return (
    <div className="p-4 space-y-1.5 font-mono text-[11.5px]" data-testid="activity-log">
      <div className="flex items-center gap-2 mb-3 font-sans">
        <span className="text-sm font-display font-semibold">{gen.kind === "create" ? "Initial build" : `Change: ${gen.prompt?.slice(0, 60)}`}</span>
        <StatusBadge testid="generation-status" status={gen.status} />
        <span className="ml-auto text-xs text-slate-400" data-testid="generation-cost">AI ${Number(gen.cost || 0).toFixed(4)} · {gen.calls || 0} calls</span>
      </div>
      {(gen.events || []).map((e, i) => (
        <div key={i} className={`${COLOR[e.type] || "text-slate-400"} leading-relaxed`}>
          <span className="text-slate-600 mr-2">{new Date(e.t).toLocaleTimeString()}</span>{e.text}
          {e.verification?.melty_checks?.length > 0 && (
            <ul className="ml-16 mt-1">{e.verification.melty_checks.map((c) => <li key={c.name} className={c.pass ? "text-emerald-300" : "text-rose-300"}>{c.pass ? "✓" : "✗"} {c.name} {c.detail}</li>)}</ul>
          )}
          {e.job_id && <div className="ml-16"><Evidence jobId={e.job_id} /></div>}
        </div>
      ))}
      {gen.error && <div className="text-rose-400 mt-2">Error: {gen.error}</div>}
    </div>
  );
}
