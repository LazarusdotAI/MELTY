import { NavLink, Link, useLocation } from "react-router-dom";
import { Flame, Sparkles, Gamepad2, Gauge, Settings } from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from "./ui/dropdown-menu";

const TABS = [
  { to: "/", label: "Copilot", icon: Sparkles, id: "nav-copilot", match: (p) => p === "/" || p.startsWith("/mods/") },
  { to: "/games", label: "Game Selector", icon: Gamepad2, id: "nav-games", match: (p) => p.startsWith("/games") },
  { to: "/trainer", label: "Trainer", icon: Gauge, id: "nav-trainer", match: (p) => p.startsWith("/trainer") },
];

const MORE = [
  ["History", "/mods", "menu-history"],
  ["Settings & AI budget", "/budget", "menu-settings"],
  ["PC connection & permissions", "/companion", "menu-pc"],
  ["Game files workshop", "/workshop", "menu-workshop"],
  ["My uploaded files", "/assets", "menu-assets"],
  ["Game compatibility notes", "/adapters", "menu-adapters"],
  ["Mod ideas", "/ideas", "menu-ideas"],
  ["Community mods", "/discover", "menu-discover"],
];

function GearMenu() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger data-testid="gear-menu-button" aria-label="More" className="w-9 h-9 grid place-items-center rounded-full text-slate-400 hover:text-slate-100 hover:bg-slate-800/70 transition-colors">
        <Settings className="w-4 h-4" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60 bg-[#0f1118] border-slate-800 text-slate-200">
        <DropdownMenuLabel className="text-[11px] uppercase tracking-widest text-slate-500">More</DropdownMenuLabel>
        <DropdownMenuSeparator className="bg-slate-800" />
        {MORE.map(([label, to, id]) => (
          <DropdownMenuItem key={to} asChild><Link to={to} data-testid={id} className="cursor-pointer">{label}</Link></DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default function TopBar() {
  const { pathname } = useLocation();
  return (
    <header className="sticky top-0 z-40 h-14 border-b border-slate-800/80 bg-[#08090d]/90 backdrop-blur-xl">
      <div className="h-full px-3 sm:px-5 flex items-center gap-3 sm:gap-6">
        <Link to="/" className="flex items-center gap-2 shrink-0" data-testid="brand-link">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-400 to-violet-500 grid place-items-center"><Flame className="w-4 h-4 text-[#08090d]" /></div>
          <span className="hidden sm:inline font-display font-extrabold tracking-tight text-lg">MELTY</span>
        </Link>
        <nav data-testid="primary-navigation" className="flex items-center gap-1 min-w-0 overflow-x-auto scroll-thin">
          {TABS.map(({ to, label, icon: Icon, id, match }) => (
            <NavLink key={to} to={to} data-testid={id} aria-label={label}
              className={`flex shrink-0 whitespace-nowrap items-center gap-2 px-3 py-1.5 rounded-full text-sm transition-colors ${match(pathname) ? "bg-cyan-500/15 text-cyan-200" : "text-slate-400 hover:text-slate-100"}`}>
              <Icon className="w-4 h-4" /> <span className="hidden sm:inline">{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto"><GearMenu /></div>
      </div>
    </header>
  );
}
