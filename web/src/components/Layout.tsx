import clsx from "clsx";
import { Activity, BookOpen, BrainCircuit, CandlestickChart, LayoutDashboard, LineChart, Monitor, Moon, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useLive } from "../lib/api";
import { useTheme } from "../lib/theme";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/research", label: "Research", icon: BookOpen },
  { to: "/backtests", label: "Backtests", icon: LineChart },
  { to: "/live", label: "Live", icon: Activity },
  { to: "/journal", label: "Journal", icon: BrainCircuit },
  { to: "/orb", label: "ORB day", icon: CandlestickChart },
];

function ThemeToggle() {
  const { choice, setChoice } = useTheme();
  const opts = [
    { v: "light" as const, icon: Sun, label: "Light" },
    { v: "system" as const, icon: Monitor, label: "System" },
    { v: "dark" as const, icon: Moon, label: "Dark" },
  ];
  return (
    <div className="flex rounded-lg border border-line bg-panel-2 p-0.5">
      {opts.map(({ v, icon: Icon, label }) => (
        <button
          key={v}
          title={label}
          onClick={() => setChoice(v)}
          className={clsx(
            "flex flex-1 items-center justify-center rounded-md py-1 transition-colors",
            choice === v ? "bg-panel text-fg shadow-sm ring-1 ring-line" : "text-faint hover:text-fg",
          )}
        >
          <Icon className="size-3.5" />
        </button>
      ))}
    </div>
  );
}

function HealthDot() {
  const live = useLive();
  const h = live.data?.health ?? [];
  const bad = h.filter((x) => x.status !== "ok").length;
  if (!h.length) return null;
  return (
    <span
      title={bad ? `${bad} check${bad > 1 ? "s" : ""} need attention` : "All checks OK"}
      className={clsx("ml-auto size-1.5 rounded-full", bad ? "bg-warn" : "bg-pos")}
    />
  );
}

function Item({ to, label, icon: Icon, end, extra }: { to: string; label: string; icon: typeof Activity; end?: boolean; extra?: ReactNode }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        clsx(
          "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors",
          isActive ? "bg-hover text-fg" : "text-muted hover:bg-hover/60 hover:text-fg",
        )
      }
    >
      <Icon className="size-4" />
      {label}
      {extra}
    </NavLink>
  );
}

export function Layout() {
  return (
    <div className="min-h-dvh">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-56 flex-col border-r border-line bg-panel/60 px-3 py-4 backdrop-blur md:flex">
        <div className="mb-6 flex items-center gap-2.5 px-2">
          <img src="/favicon.svg" alt="" className="size-7" />
          <div>
            <div className="text-[13px] font-semibold tracking-tight text-fg">horizon-trader</div>
            <div className="text-[11px] text-faint">research &amp; trading</div>
          </div>
        </div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map((n) => (
            <Item key={n.to} {...n} extra={n.to === "/live" ? <HealthDot /> : undefined} />
          ))}
        </nav>
        <div className="mt-auto space-y-3 px-1">
          <ThemeToggle />
          <p className="px-1 text-[11px] leading-snug text-faint">Read-only. Nothing here places orders.</p>
        </div>
      </aside>

      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-line bg-bg/85 px-4 py-2.5 backdrop-blur md:hidden">
        <div className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="size-6" />
          <span className="text-[13px] font-semibold text-fg">horizon-trader</span>
        </div>
        <div className="w-28">
          <ThemeToggle />
        </div>
      </header>

      <main className="overflow-x-clip px-4 pb-24 pt-5 sm:px-6 md:ml-56 md:px-8 md:pb-12 md:pt-8">
        <div className="mx-auto max-w-[1400px]">
          <Outlet />
        </div>
      </main>

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-6 border-t border-line bg-panel/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              clsx("flex flex-col items-center gap-0.5 py-2 text-[10.5px] font-medium", isActive ? "text-accent" : "text-muted")
            }
          >
            <Icon className="size-5" />
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
