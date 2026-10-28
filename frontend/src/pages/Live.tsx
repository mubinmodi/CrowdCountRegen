import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Cctv, ChevronUp, Construction, Crosshair, Info, Maximize2, Pause, Plus, RotateCcw, ShieldAlert, Smartphone, TriangleAlert, Users, VideoOff, X } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { PageHeader, useAlerts } from "../components/Shell";
import { Sparkline } from "../components/Sparkline";
import { Brackets, cx, Delta, Meter, Panel, Readout, Segmented, StatusDot, StatusTag } from "../components/ui";
import { api, streamUrl, type Camera, type CameraStatus } from "../lib/api";
import { useAppConfig } from "../lib/config";
import { useCameraFrames } from "../lib/frames";
import { useVideoPause, videoGate, type VideoPause } from "../lib/video";
import { useLive, valueAgo } from "../lib/live";
import { usePersistentState } from "../lib/storage";
import { colors, fmt } from "../lib/theme";

const GRID = {
  1: "grid-cols-1",
  2: "grid-cols-1 lg:grid-cols-2",
  3: "grid-cols-1 md:grid-cols-2 xl:grid-cols-3",
  4: "grid-cols-1 sm:grid-cols-2 xl:grid-cols-4",
} as const;
type Columns = keyof typeof GRID;

/** Grid tiles: small frames pushed over the shared frames socket. */
function TileVideo({ camera }: { camera: Camera }) {
  const img = useRef<HTMLImageElement>(null);
  useCameraFrames(camera.id, img);
  return <img ref={img} alt={`Live feed: ${camera.name}`} className="h-full w-full object-contain" />;
}

/**
 * Video viewport: live video when running, otherwise a status placeholder. Tiles share one
 * WebSocket of small frames; the enlarged view streams full-size MJPEG for its one camera.
 */
function Feed({ camera, status, large = false }: { camera: Camera; status?: CameraStatus; large?: boolean }) {
  const state = status?.state ?? "connecting";
  const pause = useVideoPause();
  return (
    <div className="relative aspect-video overflow-hidden bg-bg bg-grid">
      {state === "running" && pause ? (
        <div className="flex h-full flex-col items-center justify-center gap-2">
          <Pause size={large ? 26 : 18} className="text-mute" />
          <span className="font-mono text-[11px] tracking-[0.14em] text-mute">VIDEO PAUSED</span>
        </div>
      ) : state === "running" ? (
        large ? (
          // 503 = the server is at its video viewer limit.
          <img src={streamUrl(camera.id)} alt={`Live feed: ${camera.name}`} className="h-full w-full object-contain"
            onError={() => videoGate.busy()} />
        ) : (
          <TileVideo camera={camera} />
        )
      ) : (
        <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center">
          {state === "error" ? (
            <VideoOff size={large ? 28 : 20} className="text-alert" />
          ) : state === "waiting" ? (
            <Smartphone size={large ? 28 : 20} className="text-info" />
          ) : (
            <Cctv size={large ? 28 : 20} className="animate-pulse text-mute" />
          )}
          <span className={cx("font-mono text-[11px] tracking-[0.14em]",
            state === "error" ? "text-alert" : state === "waiting" ? "text-info" : "text-mute")}>
            {state === "error" ? `SIGNAL LOST · ${(status?.error_code ?? "").toUpperCase()}` : state === "waiting" ? "STANDBY · NO DEVICE PUBLISHING" : "ACQUIRING SIGNAL"}
          </span>
          {state === "error" && status?.error && <span className="max-w-sm font-mono text-[11px] text-mute">{status.error}</span>}
          {(state === "error" || state === "waiting") && status?.hint && large && (
            <span className="max-w-sm text-xs text-dim">{status.hint}</span>
          )}
        </div>
      )}
      <Brackets />
    </div>
  );
}

/** Danger zones alert on intrusions, occupancy cameras on going over a people limit. */
export const alertLabel = (camera: Camera) => (camera.mode === "danger_zone" ? "INTRUSION" : "OVER LIMIT");

function HazardTag() {
  return (
    <span className="flex shrink-0 items-center gap-1 rounded-sm bg-hazard px-1.5 py-0.5 font-mono text-[10px] font-semibold whitespace-nowrap text-black">
      <Construction size={11} /> DANGER ZONE
    </span>
  );
}

/** Danger zones show clear vs. intrusion; occupancy cameras show how full the zone is. */
function ZoneGauge({ camera, status }: { camera: Camera; status?: CameraStatus }) {
  if (camera.mode !== "danger_zone") {
    return <Meter value={status?.occupancy ?? 0} max={status?.alert_limit ?? camera.threshold} />;
  }
  const over = status?.over_limit ?? false;
  return over ? (
    <div className="hazard-tape h-1.5 rounded-sm" aria-label="Intrusion in progress" />
  ) : (
    <div className="h-1.5 rounded-sm bg-signal/50" aria-label="Zone clear" />
  );
}

function CameraTile({ camera, status, onFocus }: { camera: Camera; status?: CameraStatus; onFocus: () => void }) {
  const over = status?.over_limit ?? false;
  const state = status?.state ?? "connecting";
  const danger = camera.mode === "danger_zone";
  const occupancy = status?.occupancy ?? 0;
  const limit = status?.alert_limit ?? null;
  return (
    <article className={cx("group panel overflow-hidden", over && "animate-alarm border-alert")}>
      {danger && <div className="hazard-tape h-1" />}
      <div className="relative">
        <button onClick={onFocus} className="block w-full cursor-zoom-in text-left" aria-label={`Open ${camera.name}`}>
          <Feed camera={camera} status={status} />
        </button>
        <div className="pointer-events-none absolute inset-x-0 top-0 flex items-center justify-between gap-2 bg-gradient-to-b from-black/70 to-transparent px-3 pt-2.5 pb-6">
          <span className="flex min-w-0 items-center gap-2 font-mono text-[11px] tracking-[0.1em] text-ink">
            <StatusDot state={state} />
            <span className="truncate">{camera.name.toUpperCase()}</span>
          </span>
          <span className="flex items-center gap-1.5">
            {danger && !over && <HazardTag />}
            {over && (
              <span className="flex items-center gap-1 rounded-sm bg-alert px-1.5 py-0.5 font-mono text-[10px] font-semibold text-bg">
                <TriangleAlert size={11} /> {alertLabel(camera)}
              </span>
            )}
            <span className="pointer-events-auto opacity-0 transition-opacity group-hover:opacity-100">
              <button onClick={onFocus} className="btn-ghost h-6 w-6 bg-black/50 px-0 text-ink" aria-label="Expand">
                <Maximize2 size={12} />
              </button>
            </span>
          </span>
        </div>
      </div>
      <div className="border-t border-line px-3 pt-2.5 pb-3">
        <div className="flex items-end justify-between gap-3">
          <div className="flex items-baseline gap-1.5 font-mono tabular-nums">
            <span className={cx("text-[26px] leading-none font-semibold", over && "text-alert")}>{occupancy}</span>
            <span className="text-[12px] text-mute">
              {danger ? (over ? "in danger zone" : limit ? `in zone · ${limit} allowed` : "zone clear") : limit !== null ? `/ ${limit}` : "in zone"}
            </span>
          </div>
          <dl className="flex gap-4 text-right font-mono text-[11px] tabular-nums">
            <div>
              <dt className="text-mute">{danger ? "ENTERED" : "UNIQUE"}</dt>
              <dd className="text-dim">{fmt.format(status?.unique_entries ?? 0)}</dd>
            </div>
            <div>
              <dt className="text-mute">FPS</dt>
              <dd className="text-dim">{(status?.fps ?? 0).toFixed(1)}</dd>
            </div>
          </dl>
        </div>
        <div className="mt-2.5">
          <ZoneGauge camera={camera} status={status} />
        </div>
      </div>
    </article>
  );
}

function FocusView({ camera, status, onClose }: { camera: Camera; status?: CameraStatus; onClose: () => void }) {
  const live = useLive();
  const over = status?.over_limit ?? false;
  const key = String(camera.id);
  const occupancy = status?.occupancy ?? 0;
  const before = valueAgo(live.history, key, 60);
  const danger = camera.mode === "danger_zone";
  const limit = status?.alert_limit ?? null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div role="dialog" aria-modal aria-label={camera.name} className="fixed inset-0 z-50 flex bg-black/80 p-2 backdrop-blur-sm sm:p-6" onClick={onClose}>
      <div className="m-auto flex max-h-full w-full max-w-7xl flex-col overflow-auto rounded-md border border-line-strong bg-panel lg:flex-row" onClick={(e) => e.stopPropagation()}>
        <div className={cx("min-w-0 flex-1", over && "shadow-[inset_0_0_0_1px_var(--color-alert)]")}>
          <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
            <span className="flex min-w-0 items-center gap-2 font-mono text-[12px] tracking-[0.1em]">
              <StatusDot state={status?.state ?? "connecting"} />
              <span className="truncate">{camera.name.toUpperCase()}</span>
              {danger && <HazardTag />}
            </span>
            <button className="btn-ghost h-7 w-7 px-0 lg:hidden" onClick={onClose} aria-label="Close"><X size={15} /></button>
          </div>
          <Feed camera={camera} status={status} large />
        </div>
        <aside className="flex w-full shrink-0 flex-col border-t border-line lg:w-80 lg:border-t-0 lg:border-l">
          <div className="hidden items-center justify-between border-b border-line px-4 py-2.5 lg:flex">
            <span className="eyebrow">Telemetry</span>
            <button className="btn-ghost h-7 w-7 px-0" onClick={onClose} aria-label="Close"><X size={15} /></button>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-5 p-4">
            <Readout label="In zone" value={occupancy} tone={over ? "alert" : "default"}
              sub={<>60s <Delta value={before === null ? null : occupancy - before} /></>} />
            {danger ? (
              <Readout label="Allowed" value={limit ?? 0} tone={over ? "alert" : "signal"}
                sub={over ? <span className="text-alert">intrusion now</span> : "zone clear"} />
            ) : (
              <Readout label="Limit" value={limit ?? "—"} sub={limit ? `${Math.round((occupancy / limit) * 100)}% used` : "no alert set"} />
            )}
            <Readout label={danger ? "Entered" : "Unique"} value={fmt.format(status?.unique_entries ?? 0)}
              sub={danger ? "people since start" : "since start"} />
            <Readout label="FPS" value={(status?.fps ?? 0).toFixed(1)} sub={<StatusTag state={status?.state ?? "connecting"} />} />
          </div>
          {camera.description && (
            <p className="flex gap-2 border-t border-line px-4 py-3 text-[12.5px] leading-relaxed text-dim">
              <Info size={14} className="mt-0.5 shrink-0 text-mute" />
              {camera.description}
            </p>
          )}
          <div className="border-t border-line px-4 pt-3 pb-2">
            <div className="eyebrow mb-1">{danger ? "People in zone" : "Occupancy"} · last 3 min</div>
            <Sparkline data={live.history} dataKey={key} color={over ? colors.alert : colors.signal} height={90} />
          </div>
          <div className="mt-auto flex gap-2 border-t border-line p-4">
            <Link to={`/cameras/${camera.id}`} className="btn-secondary flex-1"><Crosshair size={14} /> Edit zone</Link>
            <Link to={danger ? `/incidents?camera=${camera.id}` : `/analytics?camera=${camera.id}`} className="btn-secondary flex-1">
              {danger ? "Incidents" : "History"}
            </Link>
          </div>
        </aside>
      </div>
    </div>
  );
}

const GUIDE: { title: string; body: ReactNode }[] = [
  {
    title: "Watch the wall",
    body: (
      <>
        <b className="font-medium text-ink">Site safety</b> cameras raise an <b className="font-medium text-alert">INTRUSION</b> the
        moment someone steps into their danger zone. <b className="font-medium text-ink">Occupancy</b> cameras count the people in
        their zone against a limit.
      </>
    ),
  },
  { title: "Open a camera", body: "Click any tile for full-size video, live counts, its limit and a 3-minute chart." },
  {
    title: "Check the incidents",
    body: (
      <>
        <Link to="/incidents" className="text-info hover:underline">Incidents</Link> keeps every alert with how long it lasted,
        its peak, and the frame that triggered it.
      </>
    ),
  },
  {
    title: "Change a rule",
    body: (
      <>
        On <Link to="/cameras" className="text-info hover:underline">Cameras</Link>, open one to switch its mode, change its
        limit or redraw its zone. It applies right away.
      </>
    ),
  },
  {
    title: "Go live with your phone",
    body: "Use my phone gives you a QR code. Scan it and your phone becomes a camera: draw a danger zone and step into it.",
  },
];

/** Public demo: what visitors are looking at and what to try. Collapses to a slim bar. */
function DemoGuide() {
  const qc = useQueryClient();
  const [open, setOpen] = usePersistentState("zw.demo.guide", true);
  const reset = useMutation({
    mutationFn: api.resetDemo,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cameras"] }),
  });
  const actions = (
    <div className="flex flex-wrap gap-2">
      <Link to="/cameras/new" className="btn-secondary h-8"><Smartphone size={14} /> Use my phone</Link>
      <button className="btn-ghost h-8" onClick={() => reset.mutate()} disabled={reset.isPending}
        title="Restore every scenario's zone, mode and limit">
        <RotateCcw size={14} /> {reset.isPending ? "Resetting…" : "Reset scenarios"}
      </button>
    </div>
  );

  if (!open) {
    return (
      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2 rounded border border-info/30 bg-info/5 px-4 py-2.5 text-[13px]">
        <span className="rounded-sm border border-info/50 px-1.5 py-0.5 font-mono text-[10px] tracking-wider text-info">PUBLIC DEMO</span>
        <p className="min-w-0 flex-1 text-dim">Live people detection on looping sample footage.</p>
        {actions}
        <button className="btn-ghost h-8" onClick={() => setOpen(true)} aria-expanded={false}>
          <BookOpen size={14} /> Show guide
        </button>
      </div>
    );
  }

  return (
    <section aria-labelledby="demo-guide-title" className="panel mb-4 overflow-hidden border-info/30">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line bg-info/5 px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded-sm border border-info/50 px-1.5 py-0.5 font-mono text-[10px] tracking-wider text-info">PUBLIC DEMO</span>
            <h2 id="demo-guide-title" className="text-[15px] font-semibold">Welcome to Zonewatch</h2>
          </div>
          <p className="mt-1 max-w-3xl text-[13px] text-dim">
            Seven cameras play looping sample footage while the server detects and tracks people in real time: three
            construction-site danger zones and four crowd-occupancy scenarios. No sign-in needed. Here's what to try:
          </p>
        </div>
        <button className="btn-ghost h-8 w-8 shrink-0 px-0" onClick={() => setOpen(false)}
          aria-label="Hide guide" aria-expanded={true} title="Hide guide">
          <ChevronUp size={16} />
        </button>
      </div>
      <ol className="grid gap-px bg-line sm:grid-cols-2 xl:grid-cols-5">
        {GUIDE.map((step, i) => (
          <li key={step.title} className="flex gap-3 bg-panel px-4 py-3">
            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line-strong font-mono text-[11px] text-dim">
              {i + 1}
            </span>
            <div className="min-w-0">
              <h3 className="text-[13px] font-medium">{step.title}</h3>
              <p className="mt-0.5 text-[12.5px] leading-relaxed text-dim">{step.body}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-4 py-2.5">
        <p className="text-[12px] text-mute">
          Everyone shares this demo, so others may have changed a camera. Reset puts every scenario back.
        </p>
        {actions}
      </div>
    </section>
  );
}

const PAUSE_TEXT: Record<Exclude<VideoPause, "hidden" | null>, { text: string; action: string }> = {
  idle: { text: "Live video paused after a while without activity, to save bandwidth.", action: "Resume video" },
  busy: {
    text: "The demo is at its limit for live video viewers. Video retries by itself in 30 seconds.",
    action: "Retry now",
  },
  expired: { text: "Live video session ended. Counts and alerts kept updating.", action: "Resume video" },
};

/** Explains why video stopped. Counts, alerts and incidents keep updating either way. */
function VideoPauseBanner() {
  const pause = useVideoPause();
  if (!pause || pause === "hidden") return null;
  const { text, action } = PAUSE_TEXT[pause];
  return (
    <div role="status" className="mb-4 flex flex-wrap items-center gap-3 rounded border border-warn/40 bg-warn/5 px-4 py-3 text-[13px]">
      <Pause size={15} className="shrink-0 text-warn" />
      <p className="min-w-0 flex-1 text-dim">{text}</p>
      <button className="btn-secondary h-8" onClick={() => videoGate.resume()}>{action}</button>
    </div>
  );
}

function WallSection({ icon, title, sub, children }: { icon: ReactNode; title: string; sub: string; children: ReactNode }) {
  return (
    <section className="mt-6 first-of-type:mt-4">
      <h2 className="mb-2.5 flex items-baseline gap-2">
        <span className="flex items-center gap-1.5 font-mono text-[11px] tracking-[0.14em] text-dim">{icon}{title.toUpperCase()}</span>
        <span className="text-[12px] text-mute">{sub}</span>
      </h2>
      {children}
    </section>
  );
}

export function LivePage() {
  const { demo_mode: demo } = useAppConfig();
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: api.cameras });
  const live = useLive();
  const [columns, setColumns] = usePersistentState<Columns>("zw.live.columns", 3);
  const [focusId, setFocusId] = useState<number | null>(null);

  const list = cameras.data ?? [];
  const { overLimit, faults } = useAlerts(cameras.data);
  const statuses = list.map((c) => live.statuses.get(c.id));
  const total = statuses.reduce((s, st) => s + (st?.occupancy ?? 0), 0);
  const unique = statuses.reduce((s, st) => s + (st?.unique_entries ?? 0), 0);
  const online = statuses.filter((st) => st?.state === "running").length;
  const ago = valueAgo(live.history, "total", 60);
  const focused = list.find((c) => c.id === focusId);
  const statusOf = (c: Camera) => live.statuses.get(c.id);
  const dangerCams = list.filter((c) => c.mode === "danger_zone");
  const occupancyCams = list.filter((c) => c.mode !== "danger_zone");
  const intrusions = dangerCams.filter((c) => statusOf(c)?.over_limit).length;

  const grid = (cams: Camera[]) => (
    <div className={cx("grid gap-3", GRID[columns])}>
      {cams.map((camera) => (
        <CameraTile key={camera.id} camera={camera} status={statusOf(camera)} onFocus={() => setFocusId(camera.id)} />
      ))}
    </div>
  );

  if (cameras.isSuccess && list.length === 0 && demo) {
    return (
      <>
        <DemoGuide />
        <div className="panel mx-auto mt-10 max-w-xl p-8 text-center">
          <Cctv size={30} strokeWidth={1.25} className="mx-auto animate-pulse text-mute" />
          <h1 className="mt-3 text-lg font-semibold">Preparing the demo scenarios</h1>
          <p className="mx-auto mt-1.5 max-w-sm text-sm text-dim">
            The server is downloading and trimming the sample footage. Cameras appear here one by one over the next
            minute or two.
          </p>
        </div>
      </>
    );
  }

  if (cameras.isSuccess && list.length === 0) {
    return (
      <div className="panel mx-auto mt-10 max-w-xl overflow-hidden">
        <div className="relative flex aspect-[16/7] items-center justify-center bg-bg bg-grid">
          <Cctv size={36} strokeWidth={1.25} className="text-mute" />
          <Brackets className="inset-4" />
        </div>
        <div className="border-t border-line p-6 text-center">
          <h1 className="text-lg font-semibold">No cameras on the wall yet</h1>
          <p className="mx-auto mt-1.5 max-w-sm text-sm text-dim">
            Connect an RTSP/HTTP stream, a webcam or a video file. Counting starts as soon as the first frame arrives.
          </p>
          <Link to="/cameras/new" className="btn-primary mt-5"><Plus size={15} /> Add camera</Link>
        </div>
      </div>
    );
  }

  return (
    <>
      {demo && <DemoGuide />}
      <VideoPauseBanner />
      <PageHeader title="Live wall" description="Real-time occupancy and danger-zone intrusions, from each camera's zone.">
        <div className="hidden md:block">
          <Segmented label="Grid columns" value={columns} onChange={setColumns}
            options={([1, 2, 3, 4] as const).map((n) => ({ value: n, label: `${n}×` }))} />
        </div>
        <Link to="/cameras/new" className="btn-secondary"><Plus size={14} /> Camera</Link>
      </PageHeader>

      <Panel bodyClassName="grid grid-cols-2 gap-px bg-line sm:grid-cols-4 2xl:grid-cols-[repeat(4,minmax(0,1fr))_minmax(0,1.6fr)]"
        className="overflow-hidden">
        <div className="bg-panel p-4">
          <Readout label="People now" value={fmt.format(total)} tone={overLimit.length ? "alert" : "signal"}
            sub={<>60s <Delta value={ago === null ? null : total - ago} /></>} />
        </div>
        <div className="bg-panel p-4">
          <Readout label="Unique visitors" value={fmt.format(unique)} sub="since start" />
        </div>
        <div className="bg-panel p-4">
          <Readout label="Cameras online" value={`${online}/${list.length}`}
            sub={faults.length ? <span className="text-alert">{faults.length} fault{faults.length > 1 ? "s" : ""}</span> : "all nominal"} />
        </div>
        <div className="bg-panel p-4">
          <Readout label="Alerts" value={overLimit.length} tone={overLimit.length ? "alert" : "default"}
            sub={overLimit.length
              ? `${intrusions} intrusion${intrusions === 1 ? "" : "s"} · ${overLimit.length - intrusions} over limit`
              : "none active"} />
        </div>
        <div className="col-span-2 bg-panel px-4 pt-3 pb-2 sm:col-span-4 2xl:col-span-1 2xl:pt-4">
          <div className="eyebrow">Total · last 3 min</div>
          <Sparkline data={live.history} dataKey="total" color={overLimit.length ? colors.alert : colors.signal} />
        </div>
      </Panel>

      {dangerCams.length > 0 && occupancyCams.length > 0 ? (
        <>
          <WallSection icon={<ShieldAlert size={13} className="text-hazard" />} title="Site safety"
            sub="Anyone inside a danger zone raises an intrusion and opens an incident.">
            {grid(dangerCams)}
          </WallSection>
          <WallSection icon={<Users size={13} className="text-signal" />} title="Occupancy"
            sub="People inside each counting zone, against its limit.">
            {grid(occupancyCams)}
          </WallSection>
        </>
      ) : (
        <div className="mt-4">{grid(list)}</div>
      )}

      {focused && (
        <FocusView camera={focused} status={live.statuses.get(focused.id)} onClose={() => setFocusId(null)} />
      )}
    </>
  );
}
