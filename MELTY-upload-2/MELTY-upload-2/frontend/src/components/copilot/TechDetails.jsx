import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Download } from "lucide-react";
import { api, BACKEND, usd } from "../../lib/api";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "../ui/sheet";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import ActivityLog from "../ActivityLog";
import CodeEditor from "../CodeEditor";
import VersionsPanel from "../VersionsPanel";
import ReleasesPanel from "../ReleasesPanel";

// Everything technical lives here, out of the way of the chat.
export default function TechDetails({ open, onOpenChange, mod, gen, busy, onChange }) {
  const [versions, setVersions] = useState([]);
  const [releases, setReleases] = useState([]);
  const load = () => Promise.all([api.get(`/mods/${mod.id}/versions`), api.get(`/mods/${mod.id}/releases`)]).then(([v, r]) => { setVersions(v.data); setReleases(r.data); }).catch(() => {});
  useEffect(() => { if (open) load(); }, [open, mod.current_version_id]); // eslint-disable-line react-hooks/exhaustive-deps
  const refresh = () => { load(); onChange(); };
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-2xl bg-[#0b0c11] border-slate-800 text-slate-100 p-0 flex flex-col" data-testid="tech-details">
        <SheetHeader className="px-5 pt-5 pb-3 border-b border-slate-800">
          <SheetTitle className="font-display text-slate-100 flex items-center gap-3">Technical details
            <span className="text-xs font-mono text-slate-500" data-testid="mod-spent">AI spend {usd(mod.spent, 3)}</span>
            {!mod.hosting_blocked_reason && <a href={`${BACKEND}/api/mods/${mod.id}/export`} data-testid="export-source-button" className="ml-auto mr-6 text-xs text-cyan-300 flex items-center gap-1"><Download className="w-3.5 h-3.5" /> Source</a>}
          </SheetTitle>
        </SheetHeader>
        <Tabs defaultValue="log" className="flex-1 min-h-0 flex flex-col">
          <TabsList className="bg-transparent border-b border-slate-800 rounded-none justify-start px-3">
            {[["log", "Work log"], ["design", "Design"], ["code", "Code"], ["versions", "Versions"], ["releases", "Releases"]].map(([k, l]) => <TabsTrigger key={k} value={k} data-testid={`tech-tab-${k}`}>{l}</TabsTrigger>)}
          </TabsList>
          <TabsContent value="log" className="flex-1 overflow-auto scroll-thin mt-0"><ActivityLog gen={gen} /></TabsContent>
          <TabsContent value="design" className="flex-1 overflow-auto scroll-thin p-5 mt-0"><div className="md" data-testid="design-spec">{mod.spec_md ? <ReactMarkdown remarkPlugins={[remarkGfm]}>{mod.spec_md}</ReactMarkdown> : <p>The plan appears here once Copilot has made one.</p>}</div></TabsContent>
          <TabsContent value="code" className="flex-1 overflow-auto scroll-thin mt-0"><CodeEditor key={mod.current_version_id} mod={mod} onSaved={refresh} readOnly={busy} /></TabsContent>
          <TabsContent value="versions" className="flex-1 overflow-auto scroll-thin mt-0"><VersionsPanel mod={mod} versions={versions} onChange={refresh} busy={busy} /></TabsContent>
          <TabsContent value="releases" className="flex-1 overflow-auto scroll-thin mt-0"><ReleasesPanel mod={mod} releases={releases} onChange={refresh} /></TabsContent>
        </Tabs>
      </SheetContent>
    </Sheet>
  );
}
