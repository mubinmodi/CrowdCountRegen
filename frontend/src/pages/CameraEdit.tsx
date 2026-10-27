import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArrowLeft, Construction, Crosshair, Film, Minus, Plus, Smartphone, Users } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { PublishPanel } from "../components/PublishPanel";
import { PageHeader } from "../components/Shell";
import { draftFrom, SourceEditor, toSourceInput, type SourceDraft } from "../components/SourceEditor";
import { cx, ErrorNote, Field, Panel, StatusTag } from "../components/ui";
import { ZoneEditor } from "../components/ZoneEditor";
import { api, type Camera, type CameraMode, type Point } from "../lib/api";
import { useAppConfig } from "../lib/config";
import { useLive } from "../lib/live";

const MODES: { mode: CameraMode; label: string; icon: typeof Users; blurb: string }[] = [
  { mode: "occupancy", label: "Occupancy", icon: Users, blurb: "Count people in the zone; alert above a limit" },
  { mode: "danger_zone", label: "Danger zone", icon: Construction, blurb: "Anyone entering is an intrusion and opens an incident" },
];

function StreamHealth({ camera }: { camera: Camera }) {
  const status = useLive().statuses.get(camera.id);
  const s = status?.stream;
  return (
    <Panel title={<span className="flex items-center gap-1.5"><Activity size={12} /> Stream health</span>}
      actions={<StatusTag state={status?.state ?? "connecting"} />}>
      {status?.error && (
        <div className="mb-3 rounded border border-alert/40 bg-alert/5 p-3 text-sm">
          <div className="font-mono text-[11px] tracking-wider text-alert uppercase">{status.error_code}</div>
          <div className="mt-0.5">{status.error}</div>
          {status.hint && <div className="mt-1 text-xs text-dim">{status.hint}</div>}
        </div>
      )}
      {status?.state === "waiting" && status.hint && <p className="mb-3 text-sm text-dim">{status.hint}</p>}
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 font-mono text-[11.5px] sm:grid-cols-4">
        {[
          ["RESOLUTION", s?.width && s.height ? `${s.width}×${s.height}` : "—"],
          ["CODEC", s?.codec?.toUpperCase() ?? "—"],
          ["PROCESSING", status ? `${status.fps.toFixed(1)} fps` : "—"],
          ["RECONNECTS", status?.reconnects ?? 0],
        ].map(([k, v]) => (
          <div key={k}>
            <dt className="text-mute">{k}</dt>
            <dd className="mt-0.5 tabular-nums">{v}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

function CameraForm({ camera }: { camera?: Camera }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { demo_mode: demo } = useAppConfig();
  const [name, setName] = useState(camera?.name ?? "");
  const [mode, setMode] = useState<CameraMode>(camera?.mode ?? "occupancy");
  const [threshold, setThresholdValue] = useState<number | null>(camera?.threshold ?? null);
  const [zone, setZone] = useState<Point[] | null>(camera?.zone ?? null);
  // The public demo only adds phone cameras; scenario footage can't be swapped.
  const [source, setSource] = useState<SourceDraft>(() => draftFrom(camera, demo ? "browser" : "stream"));
  const fixedSource = Boolean(camera?.scenario);
  // The config may arrive after the first render; a new demo camera is always a browser one.
  const draft: SourceDraft = demo && !camera && source.kind !== "browser" ? draftFrom(undefined, "browser") : source;
  const danger = mode === "danger_zone";

  const save = useMutation({
    mutationFn: () => {
      const input = { ...(fixedSource ? {} : toSourceInput(draft)), name, threshold, zone, mode };
      return camera ? api.updateCamera(camera.id, input) : api.createCamera(input);
    },
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: ["cameras"] });
      qc.setQueryData(["camera", saved.id], saved);
      // New cameras go straight on to zone drawing (and, for browsers, the publish link).
      navigate(camera ? "/cameras" : `/cameras/${saved.id}`);
    },
  });

  const zoneInvalid = zone !== null && zone.length < 3;
  // Danger zones allow 0 (nobody inside); occupancy limits start at 1, below that = off.
  const minimum = danger ? 0 : 1;
  const setThreshold = (n: number | null) => setThresholdValue(n !== null && n >= minimum ? n : null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
      <form onSubmit={submit} className="space-y-4">
        <Panel title="Camera">
          <div className="space-y-5">
            <Field label="Name" htmlFor="name">
              <input id="name" className="field" required maxLength={200} placeholder="Main entrance"
                value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <div>
              <span className="eyebrow mb-1.5 block text-dim">Mode</span>
              <div role="radiogroup" aria-label="Mode" className="grid grid-cols-2 gap-1.5">
                {MODES.map((m) => (
                  <button key={m.mode} type="button" role="radio" aria-checked={mode === m.mode}
                    onClick={() => setMode(m.mode)}
                    className={cx(
                      "flex flex-col items-start gap-1 rounded border p-2.5 text-left transition-colors",
                      mode === m.mode
                        ? m.mode === "danger_zone" ? "border-hazard bg-hazard/5" : "border-signal bg-signal/5"
                        : "border-line-strong bg-bg hover:border-dim/50",
                    )}>
                    <m.icon size={15} className={mode === m.mode ? (m.mode === "danger_zone" ? "text-hazard" : "text-signal") : "text-dim"} />
                    <span className="text-[12.5px] font-medium">{m.label}</span>
                    <span className="text-[11px] leading-snug text-mute">{m.blurb}</span>
                  </button>
                ))}
              </div>
            </div>
            <Field label={danger ? "People allowed inside" : "Alert limit"} htmlFor="threshold"
              hint={danger
                ? "Usually 0. Raise it if someone, e.g. a banksman, is meant to be in the zone."
                : "Flag the camera when more people than this are in the zone."}>
              <div className="flex items-center gap-1.5">
                <button type="button" className="btn-secondary h-9 w-9 px-0" aria-label="Decrease"
                  onClick={() => setThreshold((threshold ?? minimum) - 1)}><Minus size={14} /></button>
                <input id="threshold" className="field w-24 text-center font-mono" type="number" min={minimum}
                  placeholder={danger ? "0" : "off"}
                  value={threshold ?? ""} onChange={(e) => setThreshold(e.target.value ? Number(e.target.value) : null)} />
                <button type="button" className="btn-secondary h-9 w-9 px-0" aria-label="Increase"
                  onClick={() => setThreshold((threshold ?? 0) + 1)}><Plus size={14} /></button>
                <span className="ml-1 font-mono text-[11px] text-mute">PEOPLE</span>
              </div>
            </Field>
          </div>
        </Panel>

        <Panel title="Video source">
          {fixedSource ? (
            <p className="flex gap-2 rounded border border-line bg-bg p-3 text-sm text-dim">
              <Film size={15} className="mt-0.5 shrink-0 text-mute" />
              <span>{camera?.description ?? "Demo scenario playing looping sample footage."}</span>
            </p>
          ) : (
            <SourceEditor draft={draft} onChange={setSource} camera={camera} kinds={demo ? ["browser"] : undefined} />
          )}
        </Panel>

        <ErrorNote error={save.error} />
        <div className="flex gap-2">
          <button className="btn-primary flex-1" disabled={save.isPending || zoneInvalid}>
            {save.isPending ? "Saving…" : camera ? "Save changes" : "Add camera"}
          </button>
          <Link to="/cameras" className="btn-secondary">Cancel</Link>
        </div>
      </form>

      <div className="space-y-4">
        {camera?.kind === "browser" && camera.publish_token && (
          <Panel title={<span className="flex items-center gap-1.5"><Smartphone size={12} /> Publish link</span>}>
            <PublishPanel camera={camera} />
          </Panel>
        )}
        {camera && <StreamHealth camera={camera} />}
        <Panel title={<span className="flex items-center gap-1.5">
          {danger ? <Construction size={12} className="text-hazard" /> : <Crosshair size={12} />} {danger ? "Danger zone" : "Counting zone"}
        </span>}>
          {camera ? (
            <ZoneEditor cameraId={camera.id} value={zone} onChange={setZone} danger={danger} />
          ) : (
            <div className="flex aspect-video flex-col items-center justify-center gap-2 rounded border border-dashed border-line-strong bg-bg bg-grid px-8 text-center">
              <Crosshair size={22} strokeWidth={1.5} className="text-mute" />
              <p className="max-w-sm text-sm text-dim">
                Add the camera first, then draw its zone on a live frame. Zones keep overlapping cameras
                from counting the same people twice.
              </p>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

export function CameraEditPage() {
  const { id } = useParams();
  const cameraId = id ? Number(id) : undefined;
  const live = useLive();
  const camera = useQuery({
    queryKey: ["camera", cameraId],
    queryFn: () => api.camera(cameraId!),
    enabled: cameraId !== undefined,
  });

  const back = <Link to="/cameras" className="btn-ghost"><ArrowLeft size={14} /> Cameras</Link>;

  if (cameraId === undefined) {
    return (
      <>
        <PageHeader title="Add camera" description="Any IP camera, stream, phone or webcam. Test it before you save.">{back}</PageHeader>
        <CameraForm />
      </>
    );
  }
  if (camera.isPending) return <p className="font-mono text-[12px] text-mute">LOADING…</p>;
  if (camera.isError) return <ErrorNote error={camera.error} />;
  return (
    <>
      <PageHeader title={camera.data.name}
        description={<StatusTag state={live.statuses.get(camera.data.id)?.state ?? "connecting"} />}>
        {back}
      </PageHeader>
      <CameraForm key={camera.data.id} camera={camera.data} />
    </>
  );
}
