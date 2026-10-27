import { useQuery } from "@tanstack/react-query";
import { Cctv, Crosshair, Maximize2, Plus, Smartphone, TriangleAlert, VideoOff, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { PageHeader, useAlerts } from "../components/Shell";
import { Sparkline } from "../components/Sparkline";
import { Brackets, cx, Delta, Meter, Panel, Readout, Segmented, StatusDot, StatusTag } from "../components/ui";
import { api, streamUrl, type Camera, type CameraStatus } from "../lib/api";
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

function isOver(camera: Camera, status?: CameraStatus) {
  return camera.threshold !== null && (status?.occupancy ?? 0) > camera.threshold;
}

/** Video viewport: the MJPEG stream when running, otherwise a status placeholder. */
function Feed({ camera, status, large = false }: { camera: Camera; status?: CameraStatus; large?: boolean }) {
  const state = status?.state ?? "connecting";
  return (
    <div className="relative aspect-video overflow-hidden bg-bg bg-grid">
      {state === "running" ? (
        <img src={streamUrl(camera.id)} alt={`Live feed: ${camera.name}`} className="h-full w-full object-contain" />
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

function CameraTile({ camera, status, onFocus }: { camera: Camera; status?: CameraStatus; onFocus: () => void }) {
  const over = isOver(camera, status);
  const state = status?.state ?? "connecting";
  return (
    <article className={cx("group panel overflow-hidden", over && "animate-alarm border-alert")}>
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
            {over && (
              <span className="flex items-center gap-1 rounded-sm bg-alert px-1.5 py-0.5 font-mono text-[10px] font-semibold text-bg">
                <TriangleAlert size={11} /> OVER LIMIT
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
            <span className={cx("text-[26px] leading-none font-semibold", over && "text-alert")}>{status?.occupancy ?? 0}</span>
            <span className="text-[12px] text-mute">{camera.threshold ? `/ ${camera.threshold}` : "in zone"}</span>
          </div>
          <dl className="flex gap-4 text-right font-mono text-[11px] tabular-nums">
            <div>
              <dt className="text-mute">UNIQUE</dt>
              <dd className="text-dim">{fmt.format(status?.unique_entries ?? 0)}</dd>
            </div>
            <div>
              <dt className="text-mute">FPS</dt>
              <dd className="text-dim">{(status?.fps ?? 0).toFixed(1)}</dd>
            </div>
          </dl>
        </div>
        <div className="mt-2.5">
          <Meter value={status?.occupancy ?? 0} max={camera.threshold} />
        </div>
      </div>
    </article>
  );
}

function FocusView({ camera, status, onClose }: { camera: Camera; status?: CameraStatus; onClose: () => void }) {
  const live = useLive();
  const over = isOver(camera, status);
  const key = String(camera.id);
  const occupancy = status?.occupancy ?? 0;
  const before = valueAgo(live.history, key, 60);

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
            <span className="flex items-center gap-2 font-mono text-[12px] tracking-[0.1em]">
              <StatusDot state={status?.state ?? "connecting"} />
              {camera.name.toUpperCase()}
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
            <Readout label="Limit" value={camera.threshold ?? "—"} sub={camera.threshold ? `${Math.round((occupancy / camera.threshold) * 100)}% used` : "no alert set"} />
            <Readout label="Unique" value={fmt.format(status?.unique_entries ?? 0)} sub="since start" />
            <Readout label="FPS" value={(status?.fps ?? 0).toFixed(1)} sub={<StatusTag state={status?.state ?? "connecting"} />} />
          </div>
          <div className="border-t border-line px-4 pt-3 pb-2">
            <div className="eyebrow mb-1">Occupancy · last 3 min</div>
            <Sparkline data={live.history} dataKey={key} color={over ? colors.alert : colors.signal} height={90} />
          </div>
          <div className="mt-auto flex gap-2 border-t border-line p-4">
            <Link to={`/cameras/${camera.id}`} className="btn-secondary flex-1"><Crosshair size={14} /> Edit zone</Link>
            <Link to={`/analytics?camera=${camera.id}`} className="btn-secondary flex-1">History</Link>
          </div>
        </aside>
      </div>
    </div>
  );
}

export function LivePage() {
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: api.cameras });
  const live = useLive();
  const [columns, setColumns] = usePersistentState<Columns>("cc.live.columns", 3);
  const [focusId, setFocusId] = useState<number | null>(null);

  const list = cameras.data ?? [];
  const { overLimit, faults } = useAlerts(cameras.data);
  const statuses = list.map((c) => live.statuses.get(c.id));
  const total = statuses.reduce((s, st) => s + (st?.occupancy ?? 0), 0);
  const unique = statuses.reduce((s, st) => s + (st?.unique_entries ?? 0), 0);
  const online = statuses.filter((st) => st?.state === "running").length;
  const ago = valueAgo(live.history, "total", 60);
  const focused = list.find((c) => c.id === focusId);

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
      <PageHeader title="Live wall" description="Real-time occupancy inside each camera's counting zone.">
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
            sub={overLimit.length ? overLimit.map((c) => c.name).join(", ") : "none active"} />
        </div>
        <div className="col-span-2 bg-panel px-4 pt-3 pb-2 sm:col-span-4 2xl:col-span-1 2xl:pt-4">
          <div className="eyebrow">Total · last 3 min</div>
          <Sparkline data={live.history} dataKey="total" color={overLimit.length ? colors.alert : colors.signal} />
        </div>
      </Panel>

      <div className={cx("mt-4 grid gap-3", GRID[columns])}>
        {list.map((camera, i) => (
          <CameraTile key={camera.id} camera={camera} status={statuses[i]} onFocus={() => setFocusId(camera.id)} />
        ))}
      </div>

      {focused && (
        <FocusView camera={focused} status={live.statuses.get(focused.id)} onClose={() => setFocusId(null)} />
      )}
    </>
  );
}
