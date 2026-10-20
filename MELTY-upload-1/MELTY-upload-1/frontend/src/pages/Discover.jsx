import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, Monitor, Package, Gamepad2, ArrowRight } from "lucide-react";
import { api } from "../lib/api";
import { Button } from "../components/ui/button";
import StatusBadge from "../components/StatusBadge";

function CompatDots({ compat }) {
  const row = Object.values(compat || {})[0] || {};
  return (
    <div className="flex gap-1" title="install · single-player · save/load · MP join · MP sync">
      {["install_launch", "singleplayer", "save_load", "mp_join", "mp_sync"].map((k) => {
        const s = row[k]?.status;
        const c = s === "verified" ? "bg-emerald-400" : s === "failed" ? "bg-rose-500" : s === "partial" ? "bg-amber-400" : "bg-slate-700";
        return <span key={k} className={`w-2 h-2 rounded-full ${c}`} />;
      })}
    </div>
  );
}

function Step({ n, title, text, icon: Icon }) {
  return (
    <div className="panel p-5 fade-up" style={{ animationDelay: `${n * 80}ms` }}>
      <div className="flex items-center gap-3 mb-2">
        <span className="font-mono text-xs text-cyan-400">0{n}</span>
        <Icon className="w-4 h-4 text-slate-400" />
        <h3 className="font-display font-semibold">{title}</h3>
      </div>
      <p className="text-sm text-slate-400 leading-relaxed">{text}</p>
    </div>
  );
}

export default function Discover() {
  const [items, setItems] = useState([]);
  useEffect(() => { api.get("/catalog").then((r) => setItems(r.data)); }, []);
  return (
    <main className="px-8 py-10 max-w-[1500px] mx-auto">
      <section className="grid grid-cols-12 gap-8 items-end mb-12">
        <div className="col-span-12 lg:col-span-8">
          <p className="font-mono text-xs text-cyan-400 tracking-widest uppercase mb-4">Discover · Play · Create</p>
          <h1 className="font-display text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight leading-[1.04]">
            Crossover mods for the games<br />you already own.
          </h1>
          <p className="text-slate-400 mt-5 max-w-2xl text-sm md:text-base">
            One game hosts, the other lends its assets or ideas. Kimi K3 writes the mod, your PC builds and tests it in the real game, and every install can be rolled back.
          </p>
        </div>
        <div className="col-span-12 lg:col-span-4 flex gap-3 lg:justify-end">
          <Link to="/companion"><Button data-testid="hero-companion-button" variant="outline" className="h-11 rounded-full border-slate-700 bg-[#0f1118]"><Monitor className="w-4 h-4 mr-2" /> Connect my PC</Button></Link>
          <Link to="/"><Button data-testid="hero-create-button" className="h-11 rounded-full bg-cyan-500 hover:bg-cyan-400 text-[#08090d] font-semibold"><Plus className="w-4 h-4 mr-1" /> Create a mashup</Button></Link>
        </div>
      </section>
      <section className="grid md:grid-cols-3 gap-4 mb-14">
        <Step n={1} icon={Monitor} title="Pair the companion" text="A small Python app on your Windows PC finds your games, their engines and versions. It only runs a fixed list of operations." />
        <Step n={2} icon={Gamepad2} title="Describe the crossover" text="Pick a host game and a second game. The AI plans the integration, writes a BepInEx mod, then builds and tests it in the real game on your PC." />
        <Step n={3} icon={Package} title="Release & install" text="Releases ship as meltpack.json packages with checksums, tested versions and an install journal that restores every changed file." />
      </section>
      <div className="flex items-center justify-between mb-5">
        <h2 className="font-display text-2xl font-bold">Published mashups</h2>
        <span className="text-xs text-slate-500">Only releases you explicitly publish appear here</span>
      </div>
      {items.length === 0 ? (
        <div data-testid="catalog-empty" className="panel p-10 text-slate-400 max-w-xl">Nothing published yet. Build a mod, cut a release, then publish it from the release page.</div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5" data-testid="catalog-grid">
          {items.map((r) => (
            <Link key={r.id} to={`/releases/${r.id}`} data-testid={`catalog-item-${r.id}`} className="panel p-5 hover:border-cyan-500/50 transition-colors group">
              <div className="flex items-center justify-between">
                <span className="font-mono text-[11px] text-slate-500">v{r.version}</span>
                <CompatDots compat={r.compat} />
              </div>
              <h3 className="font-display text-xl font-bold mt-2">{r.title}</h3>
              <p className="text-sm text-slate-400 mt-1">Host: <span className="text-cyan-300">{r.host}</span>{r.secondary?.length ? <> · with <span className="text-violet-300">{r.secondary.join(", ")}</span></> : null}</p>
              <div className="flex items-center justify-between mt-4">
                <StatusBadge status={r.manifest?.multiplayer?.supported ? "partial" : "untested"} label={r.manifest?.multiplayer?.supported ? "MP attempted" : "single-player"} />
                <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-cyan-300 group-hover:translate-x-1 transition-transform" />
              </div>
            </Link>
          ))}
        </div>
      )}
    </main>
  );
}
