import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Radar, X } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { createPortal } from "react-dom";
import { api, type OnvifDevice } from "../lib/api";
import { cx, ErrorNote, Field } from "./ui";

export interface OnvifPick {
  uri: string;
  username: string;
  password: string;
}

/** Scan the LAN for ONVIF cameras, log in to one, and pick a stream profile. */
export function OnvifDialog({
  open,
  onClose,
  onPick,
}: {
  open: boolean;
  onClose: () => void;
  onPick: (pick: OnvifPick) => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [device, setDevice] = useState<Pick<OnvifDevice, "xaddr" | "host" | "name"> | null>(null);
  const [manual, setManual] = useState("");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");

  const scan = useMutation({ mutationFn: api.onvifDiscover });
  const streams = useMutation({
    mutationFn: () => api.onvifStreams(device!.xaddr, username, password),
  });

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      if (!scan.data && !scan.isPending) scan.mutate();
    }
    if (!open && d.open) d.close();
  }, [open, scan]);

  const back = () => {
    setDevice(null);
    streams.reset();
  };

  const login = (e: FormEvent) => {
    e.preventDefault();
    e.stopPropagation(); // React events bubble through portals to the camera form
    streams.mutate();
  };

  // Portalled out of the camera form: forms can't nest.
  return createPortal(
    <dialog ref={ref} onClose={onClose}
      className="m-auto w-[min(94vw,520px)] rounded-md border border-line-strong bg-panel p-0 text-ink backdrop:bg-black/70 backdrop:backdrop-blur-sm">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h2 className="eyebrow flex items-center gap-1.5 text-dim"><Radar size={12} /> ONVIF discovery</h2>
        <button className="btn-ghost h-7 px-1.5" onClick={onClose} aria-label="Close"><X size={14} /></button>
      </div>

      {!device ? (
        <div className="space-y-4 p-4">
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm text-dim">Cameras on the server's local network:</p>
            <button className="btn-secondary h-7 text-xs" disabled={scan.isPending} onClick={() => scan.mutate()}>
              {scan.isPending ? <Loader2 size={13} className="animate-spin" /> : <Radar size={13} />} Rescan
            </button>
          </div>
          <ErrorNote error={scan.error} />
          <ul className="max-h-64 divide-y divide-line overflow-auto rounded border border-line">
            {scan.isPending && <li className="px-3 py-6 text-center font-mono text-[11px] tracking-wider text-mute">SCANNING… (3 s)</li>}
            {scan.data?.map((d) => (
              <li key={d.xaddr}>
                <button className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-hover" onClick={() => setDevice(d)}>
                  <span className="min-w-0">
                    <span className="block truncate text-sm">{d.name ?? d.hardware ?? "ONVIF camera"}</span>
                    <span className="block truncate font-mono text-[11px] text-mute">{d.hardware ? `${d.hardware} · ` : ""}{d.host}</span>
                  </span>
                  <span className="font-mono text-[10.5px] text-signal">SELECT →</span>
                </button>
              </li>
            ))}
            {scan.isSuccess && scan.data.length === 0 && (
              <li className="px-3 py-5 text-center text-sm text-mute">
                No ONVIF cameras answered. Check that ONVIF is enabled on the camera and it's on the same subnet as this server.
              </li>
            )}
          </ul>
          <form className="flex gap-2" onSubmit={(e) => {
            e.preventDefault();
            e.stopPropagation();
            const addr = manual.trim();
            const xaddr = /^https?:\/\//.test(addr) ? addr : `http://${addr}/onvif/device_service`;
            setDevice({ xaddr, host: addr, name: null });
          }}>
            <input aria-label="Camera address" className="field font-mono text-[12px]" placeholder="Not listed? Enter its IP"
              value={manual} onChange={(e) => setManual(e.target.value)} />
            <button className="btn-secondary" disabled={!manual.trim()}>Connect</button>
          </form>
        </div>
      ) : (
        <div className="space-y-4 p-4">
          <button className="btn-ghost h-7 px-1.5 text-xs" onClick={back}><ArrowLeft size={13} /> Devices</button>
          <div>
            <div className="text-sm font-medium">{device.name ?? device.host}</div>
            <div className="font-mono text-[11px] text-mute">{device.xaddr}</div>
          </div>
          {!streams.data && (
            <form onSubmit={login} className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="Username" htmlFor="onvif-user">
                  <input id="onvif-user" className="field font-mono text-[12px]" autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} />
                </Field>
                <Field label="Password" htmlFor="onvif-pass">
                  <input id="onvif-pass" className="field font-mono text-[12px]" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
                </Field>
              </div>
              <ErrorNote error={streams.error} />
              <button className="btn-primary w-full" disabled={streams.isPending}>
                {streams.isPending ? <><Loader2 size={14} className="animate-spin" /> Asking the camera…</> : "List streams"}
              </button>
            </form>
          )}
          {streams.data && (
            <div>
              <p className="mb-2 text-sm text-dim">
                {[streams.data.manufacturer, streams.data.model].filter(Boolean).join(" ") || "Camera"}: pick a stream.
                A sub-stream is usually plenty for counting and much lighter.
              </p>
              <ul className="divide-y divide-line rounded border border-line">
                {streams.data.profiles.map((p) => (
                  <li key={p.token}>
                    <button disabled={!p.uri}
                      className={cx("flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left", p.uri ? "hover:bg-hover" : "opacity-50")}
                      onClick={() => p.uri && onPick({ uri: p.uri, username, password })}>
                      <span className="min-w-0">
                        <span className="block text-sm">{p.name ?? p.token}</span>
                        <span className="block truncate font-mono text-[11px] text-mute">{p.uri ?? "no RTSP URI"}</span>
                      </span>
                      <span className="shrink-0 font-mono text-[11px] text-dim">
                        {p.width && p.height ? `${p.width}×${p.height}` : ""} {p.encoding ?? ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </dialog>,
    document.body,
  );
}
