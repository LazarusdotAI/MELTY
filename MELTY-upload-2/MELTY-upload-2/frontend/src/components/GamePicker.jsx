import { useMemo, useState } from "react";
import { Search, Check, Gamepad2, Info } from "lucide-react";
import { Input } from "./ui/input";
import { HoverCard, HoverCardContent, HoverCardTrigger } from "./ui/hover-card";
import GameDetailsSheet, { Facts, isWWII } from "./GameDetailsSheet";
import { isColdWar } from "./ColdWarCompatibility";
import { ModStatusBadge } from "./ModToolsPanel";

const ENGINE = { redengine4: "REDengine 4", s2: "Sledgehammer S2", "unity-mono": "Unity", "unity-il2cpp": "Unity IL2CPP", unreal: "Unreal 4/5", unreal3: "Unreal 3", "re-engine": "RE Engine", unknown: "Other" };

function Cover({ g }) {
  const [err, setErr] = useState(false);
  if (g.steam_appid && !err) {
    return <img src={`https://cdn.cloudflare.steamstatic.com/steam/apps/${g.steam_appid}/header.jpg`} alt={g.name} onError={() => setErr(true)} className="w-full h-full object-cover" />;
  }
  return <div className="w-full h-full grid place-items-center bg-gradient-to-br from-slate-800 to-[#0a0b0e]"><span className="font-display text-2xl font-extrabold text-slate-500">{g.name.slice(0, 2).toUpperCase()}</span></div>;
}

export function canHost(g) {
  return !!g.hostable && !isColdWar(g) && !isWWII(g);
}

export default function GamePicker({ games, selected, onToggle, mode, disabledNames = [], testid }) {
  const [q, setQ] = useState("");
  const [details, setDetails] = useState(null);
  const [hover, setHover] = useState(null);
  const [onlyModdable, setOnlyModdable] = useState(mode === "host");
  const hasAssessment = mode === "host" && games.some((g) => isColdWar(g) || isWWII(g));
  const list = useMemo(() => games.filter((g) => (mode !== "secondary" || (!isColdWar(g) && !isWWII(g))) && g.name.toLowerCase().includes(q.toLowerCase()) && (!onlyModdable || canHost(g) || g.mod_status === "SETUP REQUIRED" || isColdWar(g) || isWWII(g))), [games, q, onlyModdable, mode]);
  return (
    <div data-testid={testid}>
      {mode === "secondary" && games.some(isColdWar) && <p data-testid={`${testid}-cold-war-note`} className="text-xs text-amber-200 mb-3">Cold War stays in the host assessment flow; it is not offered as a substitute crossover's source.</p>}
      <div className="flex items-center gap-3 mb-3">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
          <Input data-testid={`${testid}-search`} value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Filter ${games.length} games on your PC`} className="pl-9 h-9 bg-[#0a0b0e] border-slate-800 text-sm" />
        </div>
        {mode === "host" && (
          <button data-testid={`${testid}-moddable-toggle`} onClick={() => setOnlyModdable(!onlyModdable)}
            className={`text-xs px-3 py-1.5 rounded-full border ${onlyModdable ? "border-cyan-500 text-cyan-200 bg-cyan-500/10" : "border-slate-700 text-slate-400"}`}>{hasAssessment ? "Hostable + assessments" : "Hostable only"}</button>
        )}
      </div>
        {hasAssessment && <p data-testid={`${testid}-assessment-note`} className="text-xs text-amber-200 mb-3">Unverified games are included for status review only, not supported hosting.</p>}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-3 max-h-[340px] overflow-auto scroll-thin pr-1">
        {list.map((g) => {
          const on = selected.includes(g.name);
          const off = disabledNames.includes(g.name) || (mode === "host" && !canHost(g) && !isColdWar(g) && !isWWII(g));
          return (
            <HoverCard key={g.install_dir} openDelay={450} closeDelay={80} open={hover === g.install_dir && !on} onOpenChange={(o) => setHover(o ? g.install_dir : null)}>
              <HoverCardTrigger asChild>
                <div role="button" tabIndex={off ? -1 : 0} data-testid={`${testid}-game-${g.name}`} aria-disabled={off}
                  onClick={() => { setHover(null); if (!off) onToggle(g); }} onKeyDown={(e) => { if (!off && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); setHover(null); onToggle(g); } }}
                  className={`relative text-left rounded-lg overflow-hidden border transition-[border-color,transform,opacity] ${on ? "border-cyan-400 ring-2 ring-cyan-400/40" : "border-slate-800 hover:border-slate-600"} ${off ? "opacity-35 cursor-not-allowed" : "cursor-pointer active:scale-[0.98]"}`}>
                  <div className="aspect-[460/215] bg-[#0a0b0e]"><Cover g={g} /></div>
                  <div className="px-2.5 py-2 bg-[#0f1118]">
                    <div className="text-xs font-semibold truncate pr-5">{g.name}</div>
                    {(isColdWar(g) || isWWII(g)) && <p data-testid={`${testid}-support-${g.name}`} className="text-[10px] text-amber-200 mt-1 pr-6 leading-relaxed">Unverified · assessment only</p>}
                    {!isColdWar(g) && !isWWII(g) && <div className="mt-1"><ModStatusBadge status={g.mod_status} testid={`${testid}-status-${g.name}`} /></div>}
                    <div className="text-[10px] text-slate-500 font-mono truncate pr-7">{isColdWar(g) ? "Cold War (T9)" : ENGINE[g.engine] || g.engine} · {g.game_version || g.source}</div>
                  </div>
                  <button data-testid={`${testid}-info-${g.name}`} aria-label={`Details for ${g.name}`} onClick={(e) => { e.stopPropagation(); setHover(null); setDetails(g); }}
                    className="absolute bottom-2 right-2 w-6 h-6 rounded-full bg-slate-800/90 hover:bg-cyan-500 hover:text-[#08090d] text-slate-300 grid place-items-center opacity-100 transition-colors" style={{ opacity: 1 }}>
                    <Info className="w-3.5 h-3.5" />
                  </button>
                  {on && <span className="absolute top-1.5 right-1.5 w-6 h-6 rounded-full bg-cyan-400 grid place-items-center"><Check className="w-3.5 h-3.5 text-[#08090d]" /></span>}
                </div>
              </HoverCardTrigger>
              <HoverCardContent data-testid={`${testid}-hover-${g.name}`} side="top" className="w-72 bg-[#0f1118] border-slate-700 pointer-events-none">
                <p className="font-display font-semibold mb-2">{g.name}</p>
                <Facts g={g} />
                {g.host_reason && <p data-testid={`${testid}-reason-${g.name}`} className={`text-[11px] mt-2 ${g.hostable ? "text-cyan-300" : "text-amber-300"}`}>{g.host_reason}</p>}
                <p className="text-[10px] text-slate-500 mt-2">Tap ⓘ for notes and adapter details</p>
              </HoverCardContent>
            </HoverCard>
          );
        })}
        {list.length === 0 && <div className="col-span-full text-sm text-slate-500 flex items-center gap-2 py-6"><Gamepad2 className="w-4 h-4" /> No matching games.</div>}
      </div>
      <GameDetailsSheet game={details} onClose={() => setDetails(null)} />
    </div>
  );
}
