import { useEffect, useState } from "react";
import { ShieldQuestion } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg } from "../../lib/api";
import { Button } from "../ui/button";

// Things the PC companion wants permission for, shown inline so nobody has to leave Copilot.
export default function Approvals({ deviceId }) {
  const [jobs, setJobs] = useState([]);
  useEffect(() => {
    if (!deviceId) return undefined;
    const load = () => api.get(`/jobs?device_id=${deviceId}`).then((r) => setJobs(r.data.filter((j) => j.status === "needs_approval"))).catch(() => {});
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [deviceId]);
  const act = async (j, ok) => {
    try { await api.post(`/jobs/${j.id}/${ok ? "approve" : "cancel"}`); setJobs((s) => s.filter((x) => x.id !== j.id)); } catch (e) { toast.error(errMsg(e)); }
  };
  if (!jobs.length) return null;
  return (
    <div className="space-y-2" data-testid="copilot-approvals">
      {jobs.map((j) => (
        <div key={j.id} data-testid={`approval-${j.id}`} className="flex flex-wrap items-center gap-3 rounded-xl border border-amber-500/40 bg-amber-500/5 px-4 py-2.5 text-sm">
          <ShieldQuestion className="w-4 h-4 text-amber-300 shrink-0" />
          <span className="flex-1 min-w-[180px] text-amber-100">OK to do this on your PC? <b className="font-medium">{j.label}</b></span>
          <Button data-testid={`approve-${j.id}`} size="sm" onClick={() => act(j, true)} className="h-8 rounded-full bg-amber-400 hover:bg-amber-300 text-black">Allow</Button>
          <Button data-testid={`decline-${j.id}`} size="sm" variant="ghost" onClick={() => act(j, false)} className="h-8 rounded-full text-slate-400">Not now</Button>
        </div>
      ))}
    </div>
  );
}
