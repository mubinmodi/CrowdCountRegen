import { useQuery } from "@tanstack/react-query";
import {
  Cctv,
  ChartLine,
  LogOut,
  MonitorPlay,
  PanelLeftClose,
  PanelLeftOpen,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { api, type Camera } from "../lib/api";
import { useAuthActions, useCurrentUser } from "../lib/auth";
import { LiveProvider, useLive } from "../lib/live";
import { usePersistentState } from "../lib/storage";
import { cx } from "./ui";

interface NavItem {
  to: string;
  label: string;
  short: string;
  icon: LucideIcon;
  end?: boolean;
}

const NAV: NavItem[] = [
  { to: "/", label: "Live wall", short: "Live", icon: MonitorPlay, end: true },
  { to: "/cameras", label: "Cameras", short: "Cameras", icon: Cctv },
  { to: "/analytics", label: "Analytics", short: "Analytics", icon: ChartLine },
];

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden>
      <rect x="1" y="1" width="30" height="30" rx="4" fill="none" stroke="currentColor" strokeOpacity=".35" />
      <circle cx="11" cy="12.5" r="3" fill="currentColor" />
      <circle cx="21" cy="12.5" r="3" fill="currentColor" />
      <path d="M5.5 24c0-3.2 2.4-5.6 5.5-5.6s5.5 2.4 5.5 5.6M15.5 24c0-3.2 2.4-5.6 5.5-5.6s5.5 2.4 5.5 5.6"
        stroke="currentColor" strokeWidth="2.2" fill="none" strokeLinecap="round" />
    </svg>
  );
}

/** Cameras currently over their limit, and cameras in a fault state. */
export function useAlerts(cameras: Camera[] | undefined) {
  const { statuses } = useLive();
  const list = cameras ?? [];
  const overLimit = list.filter((c) => {
    const s = statuses.get(c.id);
    return c.threshold !== null && s !== undefined && s.occupancy > c.threshold;
  });
  const faults = list.filter((c) => statuses.get(c.id)?.state === "error");
  return { overLimit, faults };
}

function Clock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <time className="font-mono text-[12px] tabular-nums text-dim" dateTime={now.toISOString()}>
      {now.toLocaleTimeString([], { hour12: false })}
    </time>
  );
}

function Sidebar({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const { data: user } = useCurrentUser();
  const { logout } = useAuthActions();
  const navigate = useNavigate();
  const live = useLive();
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: api.cameras });
  const { overLimit, faults } = useAlerts(cameras.data);
  const total = cameras.data?.length ?? 0;
  const online = cameras.data?.filter((c) => live.statuses.get(c.id)?.state === "running").length ?? 0;

  const badge: Record<string, ReactNode> = {
    "/": overLimit.length > 0 && <CountBadge tone="alert" n={overLimit.length} />,
    "/cameras": faults.length > 0 && <CountBadge tone="warn" n={faults.length} />,
  };

  return (
    <aside
      className={cx(
        "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-line bg-panel transition-[width] duration-200 md:flex",
        collapsed ? "w-[60px]" : "w-[216px]",
      )}
    >
      <div className={cx("flex h-12 items-center gap-2.5 border-b border-line", collapsed ? "justify-center" : "px-4")}>
        <BrandMark className="h-6 w-6 shrink-0 text-signal" />
        {!collapsed && (
          <div className="leading-none">
            <div className="font-mono text-[13px] font-semibold tracking-[0.08em]">CROWDCOUNT</div>
            <div className="mt-0.5 font-mono text-[9.5px] tracking-[0.2em] text-mute">CONSOLE · V2</div>
          </div>
        )}
      </div>

      <nav className="flex flex-1 flex-col gap-0.5 p-2" aria-label="Main">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            title={collapsed ? item.label : undefined}
            className={({ isActive }) =>
              cx(
                "group relative flex h-9 items-center gap-3 rounded text-[13px] transition-colors",
                collapsed ? "justify-center" : "px-2.5",
                isActive ? "bg-hover text-ink" : "text-dim hover:bg-hover/60 hover:text-ink",
              )
            }
          >
            {({ isActive }) => (
              <>
                {isActive && <span className="absolute top-1.5 bottom-1.5 left-0 w-0.5 rounded-full bg-signal" />}
                <item.icon size={16} strokeWidth={1.75} className={isActive ? "text-signal" : ""} />
                {!collapsed && <span className="flex-1">{item.label}</span>}
                {badge[item.to] && (
                  <span className={collapsed ? "absolute top-1 right-1" : ""}>{badge[item.to]}</span>
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-line p-2">
        {!collapsed && (
          <dl className="mb-2 grid grid-cols-2 gap-px overflow-hidden rounded border border-line bg-line font-mono text-[10.5px]">
            <div className="bg-bg px-2.5 py-2">
              <dt className="tracking-wider text-mute">LINK</dt>
              <dd className={cx("mt-0.5", live.connected ? "text-signal" : "text-warn")}>
                {live.connected ? "ONLINE" : "RETRYING"}
              </dd>
            </div>
            <div className="bg-bg px-2.5 py-2">
              <dt className="tracking-wider text-mute">CAMS</dt>
              <dd className="mt-0.5 text-ink tabular-nums">{online}/{total}</dd>
            </div>
          </dl>
        )}
        <div className={cx("flex items-center gap-2", collapsed && "flex-col")}>
          <span title={user?.email}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded border border-line-strong bg-raised font-mono text-[11px] text-dim">
            {initials(user?.name)}
          </span>
          {!collapsed && (
            <div className="min-w-0 flex-1 leading-tight">
              <div className="truncate text-[12.5px]">{user?.name}</div>
              <div className="truncate font-mono text-[10.5px] text-mute">{user?.email}</div>
            </div>
          )}
          <button className="btn-ghost h-8 w-8 px-0" title="Sign out" aria-label="Sign out"
            onClick={() => logout.mutate(undefined, { onSuccess: () => navigate("/login") })}>
            <LogOut size={15} />
          </button>
        </div>
        <button onClick={onToggle}
          className="btn-ghost mt-2 h-7 w-full px-0 font-mono text-[10.5px] tracking-wider text-mute"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}>
          {collapsed ? <PanelLeftOpen size={15} /> : <><PanelLeftClose size={15} /> COLLAPSE</>}
        </button>
      </div>
    </aside>
  );
}

function CountBadge({ n, tone }: { n: number; tone: "alert" | "warn" }) {
  return (
    <span className={cx(
      "inline-flex h-4 min-w-4 items-center justify-center rounded-sm px-1 font-mono text-[10px] font-semibold text-bg",
      tone === "alert" ? "bg-alert" : "bg-warn",
    )}>
      {n}
    </span>
  );
}

function initials(name?: string) {
  if (!name) return "··";
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "··";
}

function Topbar() {
  const location = useLocation();
  const { data: user } = useCurrentUser();
  const { logout } = useAuthActions();
  const navigate = useNavigate();
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: api.cameras });
  const { overLimit } = useAlerts(cameras.data);
  const live = useLive();
  const section = NAV.find((n) => (n.end ? location.pathname === n.to : location.pathname.startsWith(n.to)));

  return (
    <div className="sticky top-0 z-20 flex h-12 items-center gap-3 border-b border-line bg-bg/85 px-4 backdrop-blur md:px-6">
      <BrandMark className="h-5 w-5 text-signal md:hidden" />
      <div className="min-w-0 truncate font-mono text-[11px] tracking-[0.14em] whitespace-nowrap text-mute">
        <span className="hidden sm:inline">CONSOLE / </span>
        <span className="text-dim">{(section?.label ?? "").toUpperCase()}</span>
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-3">
        {overLimit.length > 0 && (
          <NavLink to="/" title={`${overLimit.length} over limit`} className="flex h-7 shrink-0 items-center gap-1.5 rounded border border-alert/50 bg-alert/10 px-2 font-mono text-[11px] whitespace-nowrap text-alert">
            <TriangleAlert size={13} />
            <span>{overLimit.length}<span className="hidden sm:inline"> OVER LIMIT</span></span>
          </NavLink>
        )}
        <span className="hidden items-center gap-1.5 font-mono text-[11px] sm:flex">
          <span className={cx("h-1.5 w-1.5 rounded-full", live.connected ? "bg-signal" : "animate-blink bg-warn")} />
          <span className={live.connected ? "text-dim" : "text-warn"}>{live.connected ? "LIVE" : "RECONNECTING"}</span>
        </span>
        <Clock />
        <button className="btn-ghost h-8 w-8 px-0 md:hidden" aria-label={`Sign out ${user?.name ?? ""}`}
          onClick={() => logout.mutate(undefined, { onSuccess: () => navigate("/login") })}>
          <LogOut size={15} />
        </button>
      </div>
    </div>
  );
}

function MobileTabs() {
  return (
    <nav aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-3 border-t border-line bg-panel/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
      {NAV.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.end}
          className={({ isActive }) =>
            cx("flex h-14 flex-col items-center justify-center gap-1 font-mono text-[10px] tracking-wider",
              isActive ? "text-signal" : "text-mute")
          }>
          <item.icon size={18} strokeWidth={1.75} />
          {item.short.toUpperCase()}
        </NavLink>
      ))}
    </nav>
  );
}

export function Shell() {
  const [collapsed, setCollapsed] = usePersistentState("cc.sidebar.collapsed", false);
  return (
    <LiveProvider>
      <div className="flex min-h-dvh bg-bg">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar />
          <main className="flex-1 px-4 pt-5 pb-24 md:px-6 md:pb-8">
            <Outlet />
          </main>
        </div>
        <MobileTabs />
      </div>
    </LiveProvider>
  );
}

/** Page title row with optional description and right-aligned actions. */
export function PageHeader({
  title,
  description,
  children,
}: {
  title: string;
  description?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-[19px] font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-0.5 text-[13px] text-dim">{description}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </div>
  );
}
