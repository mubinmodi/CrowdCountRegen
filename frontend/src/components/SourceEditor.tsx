import { useMutation } from "@tanstack/react-query";
import {
  CircleCheck,
  CircleX,
  FileVideo,
  Image,
  Loader2,
  Radar,
  Radio,
  Smartphone,
  Usb,
  Wand2,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { api, type Camera, type ProbeResult, type SourceInput, type SourceKind, type SourceOptions } from "../lib/api";
import { TEMPLATES, type Quality } from "../lib/cameraTemplates";
import { OnvifDialog } from "./OnvifDialog";
import { cx, Field, Segmented } from "./ui";

export interface SourceDraft {
  kind: SourceKind;
  source: string;
  username: string;
  password: string; // typed by the user; blank = keep the stored password
  clearPassword: boolean;
  options: SourceOptions;
}

export function draftFrom(camera?: Camera): SourceDraft {
  return {
    kind: camera?.kind ?? "stream",
    source: camera && camera.kind !== "browser" ? camera.source : "",
    username: camera?.username ?? "",
    password: "",
    clearPassword: false,
    options: camera?.options ?? {},
  };
}

/** Moves "user:pass@" out of a pasted URL into the credential fields, so it's visible. */
export function liftCredentials(d: SourceDraft): SourceDraft {
  const m = d.source.match(/^([a-z][a-z0-9+.-]*:\/\/)([^@/?#]*)@(.*)$/i);
  if (!m) return d;
  const [, scheme, userinfo, rest] = m;
  const sep = userinfo!.indexOf(":");
  const decode = (v: string) => {
    try {
      return decodeURIComponent(v);
    } catch {
      return v;
    }
  };
  const user = decode(sep < 0 ? userinfo! : userinfo!.slice(0, sep));
  const pass = sep < 0 ? "" : decode(userinfo!.slice(sep + 1));
  return {
    ...d,
    source: `${scheme}${rest}`,
    username: user || d.username,
    password: pass || d.password,
    clearPassword: pass ? false : d.clearPassword,
  };
}

/** Request fields for a draft. Only sends a password when one was typed or explicitly cleared. */
export function toSourceInput(d: SourceDraft): SourceInput {
  const input: SourceInput = { kind: d.kind, options: d.options };
  if (d.kind === "browser") return input;
  input.source = d.source.trim();
  if (d.kind === "stream" || d.kind === "snapshot") {
    input.username = d.username.trim() || null;
    if (d.password) input.password = d.password;
    else if (d.clearPassword) input.password = null;
  }
  return input;
}

const KINDS: { kind: SourceKind; label: string; icon: LucideIcon; blurb: string }[] = [
  { kind: "stream", label: "Network stream", icon: Radio, blurb: "RTSP, RTMP, SRT, HLS, HTTP MJPEG" },
  { kind: "snapshot", label: "Snapshot URL", icon: Image, blurb: "Camera serves still JPEGs" },
  { kind: "browser", label: "Phone / browser", icon: Smartphone, blurb: "Any device's camera, no app" },
  { kind: "webcam", label: "USB webcam", icon: Usb, blurb: "Attached to this server" },
  { kind: "file", label: "Video file", icon: FileVideo, blurb: "On the server, loops" },
];

const PLACEHOLDER: Record<SourceKind, string> = {
  stream: "rtsp://192.168.1.20:554/Streaming/Channels/101",
  snapshot: "http://192.168.1.20/cgi-bin/snapshot.cgi",
  browser: "",
  webcam: "0",
  file: "/videos/lobby.mp4",
};

function TemplateBuilder({ kind, onUse }: { kind: SourceKind; onUse: (url: string) => void }) {
  const choices = TEMPLATES.filter((t) => t.kind === kind);
  const [id, setId] = useState(choices[0]?.id ?? "");
  const template = choices.find((t) => t.id === id) ?? choices[0];
  const [host, setHost] = useState("");
  const [port, setPort] = useState<number | "">("");
  const [channel, setChannel] = useState(1);
  const [quality, setQuality] = useState<Quality>("main");
  if (!template) return null;

  const url = template.build({ host: host.trim() || "<camera-ip>", port: port || template.port, channel, quality });
  return (
    // Enter here shouldn't submit the surrounding camera form.
    <div className="space-y-3 rounded border border-line bg-bg p-3"
      onKeyDown={(e) => e.key === "Enter" && e.preventDefault()}>
      <div className="grid gap-2 sm:grid-cols-2">
        <select aria-label="Camera brand" className="field font-mono text-[12px] sm:col-span-2" value={template.id}
          onChange={(e) => setId(e.target.value)}>
          {choices.map((t) => <option key={t.id} value={t.id}>{t.brand}</option>)}
        </select>
        <input aria-label="Camera IP or host" className="field font-mono text-[12px]" placeholder="IP or host, e.g. 192.168.1.64"
          value={host} onChange={(e) => setHost(e.target.value)} />
        <input aria-label="Port" className="field font-mono text-[12px]" type="number" placeholder={`port ${template.port}`}
          value={port} onChange={(e) => setPort(e.target.value ? Number(e.target.value) : "")} />
        {template.channels && (
          <input aria-label="Channel" className="field font-mono text-[12px]" type="number" min={1} value={channel}
            onChange={(e) => setChannel(Math.max(1, Number(e.target.value) || 1))} />
        )}
        <Segmented<Quality> label="Stream quality" value={quality} onChange={setQuality}
          options={[{ value: "main", label: "MAIN" }, { value: "sub", label: "SUB" }]} />
      </div>
      <div className="truncate font-mono text-[11px] text-dim" title={url}>{url}</div>
      {template.note && <p className="text-xs text-mute">{template.note}</p>}
      <p className="text-xs text-mute">
        Sub-streams are lower resolution: lighter on bandwidth and usually plenty for counting.
      </p>
      <button type="button" className="btn-secondary h-7 text-xs" disabled={!host.trim()} onClick={() => onUse(url)}>
        Use this URL
      </button>
    </div>
  );
}

function ProbeCard({ result }: { result: ProbeResult }) {
  if (!result.ok) {
    return (
      <div role="status" className="rounded border border-alert/40 bg-alert/5 p-3">
        <div className="flex items-start gap-2">
          <CircleX size={16} className="mt-0.5 shrink-0 text-alert" />
          <div className="min-w-0 text-sm">
            <div className="font-mono text-[11px] tracking-wider text-alert uppercase">{result.error_code}</div>
            <div className="mt-0.5 text-ink">{result.message}</div>
            {result.hint && <div className="mt-1.5 text-xs text-dim">{result.hint}</div>}
          </div>
        </div>
      </div>
    );
  }
  const s = result.stream;
  return (
    <div role="status" className="overflow-hidden rounded border border-signal/40 bg-signal/5">
      {result.preview && <img src={result.preview} alt="Frame received from the camera" className="block w-full" />}
      <div className="flex items-start gap-2 p-3">
        <CircleCheck size={16} className="mt-0.5 shrink-0 text-signal" />
        <dl className="grid flex-1 grid-cols-2 gap-x-4 gap-y-1 font-mono text-[11px]">
          <dt className="text-mute">RESOLUTION</dt>
          <dd>{s?.width && s.height ? `${s.width}×${s.height}` : "—"}</dd>
          <dt className="text-mute">CODEC</dt>
          <dd>{s?.codec?.toUpperCase() ?? "—"}</dd>
          <dt className="text-mute">SOURCE FPS</dt>
          <dd>{s?.fps ? s.fps.toFixed(1) : "—"}</dd>
          <dt className="text-mute">FIRST FRAME</dt>
          <dd>{result.first_frame_ms} ms</dd>
        </dl>
      </div>
    </div>
  );
}

export function SourceEditor({
  draft,
  onChange,
  camera,
}: {
  draft: SourceDraft;
  onChange: (d: SourceDraft) => void;
  camera?: Camera;
}) {
  const [builderOpen, setBuilderOpen] = useState(false);
  const [onvifOpen, setOnvifOpen] = useState(false);
  const set = (patch: Partial<SourceDraft>) => onChange({ ...draft, ...patch });
  const setOption = (patch: Partial<SourceOptions>) => set({ options: { ...draft.options, ...patch } });

  const test = useMutation({
    mutationFn: () => api.probe({ ...toSourceInput(draft), camera_id: camera?.id }),
  });

  const isUrl = draft.kind === "stream" || draft.kind === "snapshot";
  const scheme = draft.source.trim().split(":")[0]?.toLowerCase();
  const storedPassword = camera?.has_password && !draft.clearPassword;
  const canTest = draft.kind === "browser" ? Boolean(camera) : Boolean(draft.source.trim());

  return (
    <div className="space-y-5">
      <div>
        <span className="eyebrow mb-1.5 block text-dim">Source type</span>
        <div role="radiogroup" aria-label="Source type" className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
          {KINDS.map((k) => (
            <button key={k.kind} type="button" role="radio" aria-checked={draft.kind === k.kind}
              onClick={() => {
                test.reset();
                set({ kind: k.kind, source: k.kind === draft.kind ? draft.source : "" });
              }}
              className={cx(
                "flex flex-col items-start gap-1 rounded border p-2.5 text-left transition-colors",
                draft.kind === k.kind ? "border-signal bg-signal/5" : "border-line-strong bg-bg hover:border-dim/50",
              )}>
              <k.icon size={15} className={draft.kind === k.kind ? "text-signal" : "text-dim"} />
              <span className="text-[12.5px] font-medium">{k.label}</span>
              <span className="text-[11px] leading-snug text-mute">{k.blurb}</span>
            </button>
          ))}
        </div>
      </div>

      {draft.kind === "browser" ? (
        <p className="rounded border border-line bg-bg p-3 text-sm text-dim">
          {camera
            ? "Open the publish link (right) on a phone or laptop and allow camera access. It streams straight to this server."
            : "Save the camera to get a publish link and QR code. Open it on any phone or laptop to stream its camera; nothing to install."}
        </p>
      ) : (
        <Field
          label={draft.kind === "webcam" ? "Device" : draft.kind === "file" ? "Path on the server" : "URL"}
          htmlFor="source"
          hint={
            draft.kind === "webcam"
              ? "0 is the first camera attached to the server; /dev/videoN on Linux."
              : draft.kind === "file"
                ? "A video file readable by the backend process. It plays on a loop like a live camera."
                : "Credentials pasted in the URL (user:pass@host) are moved to the fields below."
          }
        >
          <input id="source" className="field font-mono text-[12px]" required spellCheck={false} autoComplete="off"
            placeholder={PLACEHOLDER[draft.kind]} value={draft.source}
            onChange={(e) => set({ source: e.target.value })}
            onBlur={() => isUrl && onChange(liftCredentials(draft))} />
          {isUrl && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              <button type="button" className="btn-ghost h-7 px-2 text-xs" onClick={() => setBuilderOpen(!builderOpen)}>
                <Wand2 size={13} /> {builderOpen ? "Hide" : "Build from"} brand template
              </button>
              {draft.kind === "stream" && (
                <button type="button" className="btn-ghost h-7 px-2 text-xs" onClick={() => setOnvifOpen(true)}>
                  <Radar size={13} /> Find on network (ONVIF)
                </button>
              )}
            </div>
          )}
          {isUrl && builderOpen && (
            <div className="mt-2">
              <TemplateBuilder kind={draft.kind} onUse={(url) => { set({ source: url }); setBuilderOpen(false); }} />
            </div>
          )}
        </Field>
      )}

      {isUrl && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Username" htmlFor="username">
            <input id="username" className="field font-mono text-[12px]" autoComplete="off" spellCheck={false}
              placeholder="optional" value={draft.username} onChange={(e) => set({ username: e.target.value })} />
          </Field>
          <Field label="Password" htmlFor="password"
            hint={storedPassword ? (
              <button type="button" className="hover:text-alert" onClick={() => set({ clearPassword: true, password: "" })}>
                Saved and encrypted. Leave blank to keep · remove
              </button>
            ) : undefined}>
            <input id="password" className="field font-mono text-[12px]" type="password" autoComplete="new-password"
              placeholder={storedPassword ? "••••••••" : "optional"} value={draft.password}
              onChange={(e) => set({ password: e.target.value, clearPassword: false })} />
          </Field>
        </div>
      )}

      {draft.kind === "snapshot" && (
        <Field label="Poll interval" htmlFor="interval" hint="How often to fetch a new image. 500 ms ≈ 2 frames per second.">
          <div className="flex items-center gap-2">
            <input id="interval" className="field w-28 font-mono" type="number" min={100} step={100}
              value={draft.options.snapshot_interval_ms ?? 500}
              onChange={(e) => setOption({ snapshot_interval_ms: Number(e.target.value) || undefined })} />
            <span className="font-mono text-[11px] text-mute">MS</span>
          </div>
        </Field>
      )}

      {draft.kind === "webcam" && (
        <Field label="Capture width" htmlFor="width" hint="Optional; the webcam's default is used when blank.">
          <input id="width" className="field w-28 font-mono" type="number" min={160} step={160} placeholder="auto"
            value={draft.options.width ?? ""} onChange={(e) => setOption({ width: Number(e.target.value) || undefined })} />
        </Field>
      )}

      {isUrl && (scheme?.startsWith("rtsp") || scheme === "https") && (
        <details className="group rounded border border-line">
          <summary className="cursor-pointer list-none px-3 py-2 font-mono text-[11px] tracking-wider text-dim select-none group-open:border-b group-open:border-line">
            ADVANCED
          </summary>
          <div className="space-y-3 p-3">
            {scheme?.startsWith("rtsp") && (
              <div>
                <div className="eyebrow mb-1.5 text-dim">RTSP transport</div>
                <Segmented label="RTSP transport" value={draft.options.rtsp_transport ?? "tcp"}
                  onChange={(v) => setOption({ rtsp_transport: v })}
                  options={[{ value: "tcp", label: "TCP" }, { value: "udp", label: "UDP" }, { value: "auto", label: "AUTO" }]} />
                <p className="mt-1.5 text-xs text-mute">TCP avoids grey, smeared frames over Wi-Fi and VPNs. UDP has slightly lower latency on a clean LAN.</p>
              </div>
            )}
            {scheme === "https" && (
              <label className="flex items-center gap-2 text-sm text-dim">
                <input type="checkbox" className="accent-signal" checked={draft.options.insecure_tls ?? false}
                  onChange={(e) => setOption({ insecure_tls: e.target.checked || undefined })} />
                Accept the camera's self-signed certificate
              </label>
            )}
          </div>
        </details>
      )}

      {draft.kind !== "browser" || camera ? (
        <div className="space-y-3">
          <button type="button" className="btn-secondary w-full" disabled={!canTest || test.isPending} onClick={() => test.mutate()}>
            {test.isPending ? <><Loader2 size={14} className="animate-spin" /> Connecting…</> : "Test connection"}
          </button>
          {test.error && <p className="font-mono text-xs text-alert">{test.error.message}</p>}
          {test.data && <ProbeCard result={test.data} />}
        </div>
      ) : null}

      <OnvifDialog open={onvifOpen} onClose={() => setOnvifOpen(false)}
        onPick={({ uri, username, password }) => {
          set({ kind: "stream", source: uri, username, password, clearPassword: false });
          setOnvifOpen(false);
          test.reset();
        }} />
    </div>
  );
}
