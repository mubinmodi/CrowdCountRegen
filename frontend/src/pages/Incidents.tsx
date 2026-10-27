import { useQuery } from "@tanstack/react-query";
import { Construction, ImageOff, ShieldAlert, Users, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { PageHeader } from "../components/Shell";
import { cx, Panel, Readout } from "../components/ui";
import { api, incidentSnapshotUrl, type Camera, type Incident } from "../lib/api";

const REFRESH_MS = 3000;

function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

const durationMs = (i: Incident, now: number) =>
  (i.ended_at ? Date.parse(i.ended_at) : now) - Date.parse(i.started_at);

export function formatDuration(ms: number) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

function ago(iso: string, now: number) {
  const s = Math.round((now - Date.parse(iso)) / 1000);
  if (s < 60) return `${Math.max(s, 0)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

function ModeIcon({ camera }: { camera?: Camera }) {
  return camera?.mode === "danger_zone"
    ? <Construction size={13} className="shrink-0 text-hazard" aria-label="Danger zone" />
    : <Users size={13} className="shrink-0 text-dim" aria-label="Occupancy" />;
}

function Lightbox({ incident, camera, onClose }: { incident: Incident; camera?: Camera; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div role="dialog" aria-modal aria-label="Incident snapshot" onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4 backdrop-blur-sm">
      <figure className="panel max-w-5xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <figcaption className="flex items-center gap-2 font-mono text-[12px] tracking-[0.08em]">
            <ModeIcon camera={camera} />
            {camera?.name.toUpperCase()} · {new Date(incident.started_at).toLocaleString()}
          </figcaption>
          <button className="btn-ghost h-7 w-7 px-0" onClick={onClose} aria-label="Close"><X size={15} /></button>
        </div>
        <img src={incidentSnapshotUrl(incident.id)} alt="Frame when the incident started" className="block max-h-[80vh] w-full object-contain" />
      </figure>
    </div>
  );
}

export function IncidentsPage() {
  const [params, setParams] = useSearchParams();
  const cameraParam = params.get("camera");
  const cameraId = cameraParam ? Number(cameraParam) : undefined;
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: api.cameras });
  const incidents = useQuery({
    queryKey: ["incidents", cameraId],
    queryFn: () => api.incidents({ cameraId, limit: 200 }),
    refetchInterval: REFRESH_MS,
  });
  const now = useNow();
  const [viewing, setViewing] = useState<Incident | null>(null);

  const byId = new Map((cameras.data ?? []).map((c) => [c.id, c]));
  const list = incidents.data ?? [];
  const open = list.filter((i) => !i.ended_at);
  const lastHour = list.filter((i) => now - Date.parse(i.started_at) <= 3_600_000);
  const longest = list.reduce<Incident | null>((a, b) => (!a || durationMs(b, now) > durationMs(a, now) ? b : a), null);
  const perCamera = new Map<number, number>();
  for (const i of lastHour) perCamera.set(i.camera_id, (perCamera.get(i.camera_id) ?? 0) + 1);
  const [topId, topCount] = [...perCamera.entries()].sort((a, b) => b[1] - a[1])[0] ?? [];

  return (
    <>
      <PageHeader title="Incidents"
        description="Every period a camera spent over its limit, with the frame that triggered it. Danger zones open one for any intrusion.">
        <select aria-label="Filter by camera" className="field w-auto min-w-52 font-mono text-[12px]"
          value={cameraParam ?? ""}
          onChange={(e) => setParams(e.target.value ? { camera: e.target.value } : {})}>
          <option value="">All cameras</option>
          {(cameras.data ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </PageHeader>

      <Panel className="overflow-hidden" bodyClassName="grid grid-cols-2 gap-px bg-line sm:grid-cols-4">
        <div className="bg-panel p-4">
          <Readout label="Open now" value={open.length} tone={open.length ? "alert" : "signal"}
            sub={open.length ? open.map((i) => byId.get(i.camera_id)?.name).join(", ") : "all clear"} />
        </div>
        <div className="bg-panel p-4">
          <Readout label="Last hour" value={lastHour.length} sub={`${list.length} kept in total`} />
        </div>
        <div className="bg-panel p-4">
          <Readout label="Longest" value={longest ? formatDuration(durationMs(longest, now)) : "—"}
            sub={longest ? byId.get(longest.camera_id)?.name : "no incidents yet"} />
        </div>
        <div className="bg-panel p-4">
          <Readout label="Most frequent" value={topCount ?? 0}
            sub={topId !== undefined ? `${byId.get(topId)?.name ?? "camera"} · last hour` : "last hour"} />
        </div>
      </Panel>

      <Panel className="mt-4" bodyClassName="">
        {incidents.isSuccess && list.length === 0 ? (
          <div className="px-4 py-14 text-center">
            <ShieldAlert size={26} strokeWidth={1.5} className="mx-auto text-mute" />
            <p className="mt-3 font-mono text-[12px] tracking-wider text-mute">NO INCIDENTS RECORDED</p>
            <p className="mx-auto mt-1.5 max-w-md text-sm text-dim">
              An incident opens when a camera has been over its limit for a second, and closes once it has been clear
              for a few seconds.
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {list.map((i) => {
              const camera = byId.get(i.camera_id);
              const live = !i.ended_at;
              const danger = camera?.mode === "danger_zone";
              return (
                <li key={i.id} className={cx("flex items-center gap-4 px-4 py-3", live && "bg-alert/5")}>
                  <button type="button" onClick={() => i.has_snapshot && setViewing(i)} disabled={!i.has_snapshot}
                    className="relative aspect-video w-28 shrink-0 overflow-hidden rounded-sm border border-line bg-bg sm:w-40"
                    aria-label="View snapshot">
                    {i.has_snapshot ? (
                      <img src={incidentSnapshotUrl(i.id)} alt="" loading="lazy" className="h-full w-full object-cover" />
                    ) : (
                      <ImageOff size={16} className="absolute inset-0 m-auto text-mute" />
                    )}
                  </button>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <ModeIcon camera={camera} />
                      <span className="truncate font-medium">{camera?.name ?? `Camera ${i.camera_id}`}</span>
                    </div>
                    <div className="mt-1 font-mono text-[11.5px] text-dim">
                      {danger
                        ? `${i.peak} ${i.peak === 1 ? "person" : "people"} inside${i.limit ? ` · ${i.limit} allowed` : ""}`
                        : `peak ${i.peak} · limit ${i.limit}`}
                    </div>
                    <div className="mt-0.5 font-mono text-[11px] text-mute">
                      {new Date(i.started_at).toLocaleTimeString([], { hour12: false })} · {ago(i.started_at, now)}
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    {live ? (
                      <span className="inline-flex items-center gap-1.5 rounded-sm bg-alert px-1.5 py-0.5 font-mono text-[10px] font-semibold text-bg">
                        <span className="h-1.5 w-1.5 animate-blink rounded-full bg-bg" /> {danger ? "INTRUSION" : "OVER LIMIT"}
                      </span>
                    ) : (
                      <span className="rounded-sm border border-line-strong px-1.5 py-0.5 font-mono text-[10px] tracking-wider text-mute">RESOLVED</span>
                    )}
                    <div className={cx("mt-1.5 font-mono text-[13px] tabular-nums", live ? "text-alert" : "text-dim")}>
                      {formatDuration(durationMs(i, now))}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </Panel>

      {viewing && <Lightbox incident={viewing} camera={byId.get(viewing.camera_id)} onClose={() => setViewing(null)} />}
    </>
  );
}
