import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { PageHeader } from "../components/Shell";
import { ConfirmDialog, cx, Meter, Panel, StatusTag } from "../components/ui";
import { api, type Camera } from "../lib/api";
import { useLive } from "../lib/live";

/** Short tag for the source type, e.g. RTSP, HLS, SNAPSHOT, PHONE. */
function sourceTag(c: Camera) {
  switch (c.kind) {
    case "browser":
      return "PHONE";
    case "webcam":
      return "WEBCAM";
    case "file":
      return "FILE";
    case "snapshot":
      return "SNAPSHOT";
    default: {
      const scheme = c.source.match(/^([a-z][a-z0-9+.-]*):\/\//i)?.[1]?.toUpperCase() ?? "STREAM";
      return /\.m3u8(\?|$)/i.test(c.source) ? "HLS" : scheme;
    }
  }
}

const sourceText = (c: Camera) =>
  c.kind === "browser" ? "Publish link (open on any device)" : `${c.username ? `${c.username}@ ` : ""}${c.source}`;

export function CamerasPage() {
  const qc = useQueryClient();
  const cameras = useQuery({ queryKey: ["cameras"], queryFn: api.cameras });
  const live = useLive();
  const [pendingDelete, setPendingDelete] = useState<Camera | null>(null);
  const remove = useMutation({
    mutationFn: (c: Camera) => api.deleteCamera(c.id),
    onSuccess: () => {
      setPendingDelete(null);
      qc.invalidateQueries({ queryKey: ["cameras"] });
    },
  });

  const list = cameras.data ?? [];

  return (
    <>
      <PageHeader title="Cameras" description={`${list.length} configured · sources, zones and alert limits`}>
        <Link to="/cameras/new" className="btn-primary"><Plus size={15} /> Add camera</Link>
      </PageHeader>

      <Panel bodyClassName="">
        {/* Wide screens: table. Narrower (incl. desktop with sidebar): stacked rows. */}
        <table className="hidden w-full text-left text-[13px] xl:table">
          <thead>
            <tr className="border-b border-line">
              {["Status", "Name", "Source", "Zone", "Now / limit", "FPS", ""].map((h) => (
                <th key={h} className="eyebrow px-4 py-2.5 font-medium whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {list.map((c) => {
              const s = live.statuses.get(c.id);
              const over = c.threshold !== null && (s?.occupancy ?? 0) > c.threshold;
              return (
                <tr key={c.id} className="border-b border-line last:border-0 hover:bg-raised/60">
                  <td className="w-32 px-4 py-3"><StatusTag state={s?.state ?? "connecting"} /></td>
                  <td className="min-w-[11rem] px-4 py-3">
                    <Link to={`/cameras/${c.id}`} className="font-medium hover:text-signal">{c.name}</Link>
                    {s?.state === "error" && <div className="mt-0.5 max-w-xs truncate font-mono text-[11px] text-alert">{s.error}</div>}
                  </td>
                  <td className="max-w-[14rem] px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="shrink-0 rounded-sm border border-line-strong px-1 font-mono text-[9.5px] tracking-wider text-dim">{sourceTag(c)}</span>
                      <span className="truncate font-mono text-[12px] text-dim" title={sourceText(c)}>{sourceText(c)}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-[12px] whitespace-nowrap text-dim">{c.zone ? `POLY·${c.zone.length}` : "FULL FRAME"}</td>
                  <td className="w-44 px-4 py-3">
                    <div className="mb-1.5 font-mono text-[12px] tabular-nums">
                      <span className={over ? "text-alert" : ""}>{s?.occupancy ?? 0}</span>
                      <span className="text-mute"> / {c.threshold ?? "—"}</span>
                    </div>
                    <Meter value={s?.occupancy ?? 0} max={c.threshold} />
                  </td>
                  <td className="px-4 py-3 font-mono text-[12px] tabular-nums text-dim">{(s?.fps ?? 0).toFixed(1)}</td>
                  <td className="px-4 py-3 text-right whitespace-nowrap">
                    <Link to={`/cameras/${c.id}`} className="btn-ghost h-8 w-8 px-0" aria-label={`Edit ${c.name}`}><Pencil size={14} /></Link>
                    <button className="btn-ghost h-8 w-8 px-0 hover:text-alert" aria-label={`Delete ${c.name}`} onClick={() => setPendingDelete(c)}>
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        <ul className="divide-y divide-line xl:hidden">
          {list.map((c) => {
            const s = live.statuses.get(c.id);
            return (
              <li key={c.id} className="flex items-center gap-3 px-4 py-3">
                <Link to={`/cameras/${c.id}`} className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium">{c.name}</span>
                    <StatusTag state={s?.state ?? "connecting"} />
                  </div>
                  <div className="mt-1 truncate font-mono text-[11px] text-mute">{sourceTag(c)} · {sourceText(c)}</div>
                  <div className="mt-1.5 font-mono text-[11px] text-dim">
                    {s?.occupancy ?? 0} / {c.threshold ?? "—"} · {c.zone ? `POLY·${c.zone.length}` : "FULL FRAME"}
                  </div>
                </Link>
                <button className="btn-ghost h-9 w-9 px-0" aria-label={`Delete ${c.name}`} onClick={() => setPendingDelete(c)}>
                  <Trash2 size={15} />
                </button>
              </li>
            );
          })}
        </ul>

        {cameras.isSuccess && list.length === 0 && (
          <div className={cx("px-4 py-14 text-center")}>
            <p className="font-mono text-[12px] tracking-wider text-mute">NO DEVICES REGISTERED</p>
            <Link to="/cameras/new" className="btn-secondary mt-4"><Plus size={14} /> Add your first camera</Link>
          </div>
        )}
      </Panel>

      <ConfirmDialog
        open={pendingDelete !== null}
        title="Delete camera"
        body={<>Remove <span className="text-ink">{pendingDelete?.name}</span> and all of its recorded counts? This can't be undone.</>}
        confirmLabel={remove.isPending ? "Deleting…" : "Delete camera"}
        busy={remove.isPending}
        onConfirm={() => pendingDelete && remove.mutate(pendingDelete)}
        onCancel={() => setPendingDelete(null)}
      />
    </>
  );
}
