import { Camera as CameraIcon, CameraOff, RefreshCcw, SwitchCamera } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router";
import { BrandMark } from "../components/Shell";
import { Brackets, cx, Segmented } from "../components/ui";
import type { CameraStatus } from "../lib/api";
import { Publisher } from "../lib/publisher";
import { usePersistentState } from "../lib/storage";

type Phase = "idle" | "starting" | "live" | "reconnecting" | "taken_over" | "invalid" | "error";
type Quality = "low" | "standard" | "high";

const WIDTH: Record<Quality, number> = { low: 640, standard: 960, high: 1280 };

/**
 * Turns any phone or laptop into a camera: streams JPEG frames to the server over a
 * WebSocket. Opened from a camera's publish link, so it needs no login.
 */
export function PublishPage() {
  const { token } = useParams();
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const publisher = useRef<Publisher | null>(null);
  const wakeLock = useRef<WakeLockSentinel | null>(null);

  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [cameraName, setCameraName] = useState<string | null>(null);
  const [server, setServer] = useState<CameraStatus | null>(null);
  const [facing, setFacing] = usePersistentState<"environment" | "user">("cc.publish.facing", "environment");
  const [quality, setQuality] = usePersistentState<Quality>("cc.publish.quality", "standard");
  const [fps, setFps] = usePersistentState("cc.publish.fps", 10);
  const [sent, setSent] = useState({ fps: 0, kbps: 0 });
  // The send loop reads the latest settings without restarting.
  const settings = useRef({ maxWidth: WIDTH[quality], fps });
  useEffect(() => {
    settings.current = { maxWidth: WIDTH[quality], fps };
  }, [quality, fps]);

  const secure = window.isSecureContext;
  const supported = Boolean(navigator.mediaDevices?.getUserMedia);

  const releaseDevice = () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    wakeLock.current?.release().catch(() => {});
    wakeLock.current = null;
  };

  const stopAll = () => {
    publisher.current?.stop();
    publisher.current = null;
    releaseDevice();
  };

  // Release the camera if the page is closed or navigated away from.
  useEffect(
    () => () => {
      publisher.current?.stop();
      stream.current?.getTracks().forEach((t) => t.stop());
    },
    [],
  );

  const openCamera = async (mode: "environment" | "user") => {
    stream.current?.getTracks().forEach((t) => t.stop());
    const media = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: mode }, width: { ideal: 1280 }, height: { ideal: 720 } },
    });
    stream.current = media;
    if (video.current) {
      video.current.srcObject = media;
      await video.current.play();
    }
  };

  const start = async () => {
    if (!token || !video.current) return;
    setError(null);
    setPhase("starting");
    try {
      await openCamera(facing);
    } catch (e) {
      setPhase("error");
      setError(e instanceof DOMException && e.name === "NotAllowedError"
        ? "Camera permission was denied. Allow camera access for this site in your browser settings, then try again."
        : `Couldn't open the camera: ${(e as Error).message}`);
      return;
    }
    try {
      wakeLock.current = await navigator.wakeLock?.request("screen");
    } catch {
      // Not supported or denied; the screen may sleep and pause streaming.
    }
    publisher.current = new Publisher(token, video.current, () => settings.current, {
      onPhase: (p) => {
        setPhase(p);
        if (p === "taken_over" || p === "invalid") releaseDevice();
      },
      onHello: setCameraName,
      onStatus: (s) => setServer(s as CameraStatus),
      onStats: setSent,
    });
    publisher.current.start();
  };

  const flip = async () => {
    const next = facing === "environment" ? "user" : "environment";
    setFacing(next);
    if (stream.current) {
      try {
        await openCamera(next);
      } catch {
        setError("This device has no other camera.");
      }
    }
  };

  const stop = () => {
    stopAll();
    setPhase("idle");
    setServer(null);
  };

  const active = phase === "live" || phase === "reconnecting" || phase === "starting";
  const pill: Record<Phase, [string, string]> = {
    idle: ["READY", "text-dim border-line-strong"],
    starting: ["STARTING", "text-info border-info/50"],
    live: ["● LIVE", "text-signal border-signal/50"],
    reconnecting: ["RECONNECTING", "text-warn border-warn/50"],
    taken_over: ["TAKEN OVER", "text-warn border-warn/50"],
    invalid: ["LINK REVOKED", "text-alert border-alert/50"],
    error: ["ERROR", "text-alert border-alert/50"],
  };

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <header className="flex h-12 items-center gap-2.5 border-b border-line px-4">
        <BrandMark className="h-5 w-5 text-signal" />
        <span className="font-mono text-[12px] font-semibold tracking-[0.1em]">CROWDCOUNT</span>
        <span className="truncate font-mono text-[11px] tracking-wider text-mute">/ {cameraName ?? "PUBLISH"}</span>
        <span className={cx("ml-auto shrink-0 rounded-sm border px-1.5 py-0.5 font-mono text-[10px] tracking-wider", pill[phase][1])}>
          {pill[phase][0]}
        </span>
      </header>

      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 p-4">
        <div className="relative aspect-[3/4] overflow-hidden rounded-md border border-line-strong bg-panel bg-grid sm:aspect-video">
          <video ref={video} playsInline muted
            className={cx("h-full w-full object-cover", facing === "user" && "-scale-x-100", !active && "hidden")} />
          {!active && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
              <CameraIcon size={32} strokeWidth={1.25} className="text-mute" />
              <p className="max-w-xs text-sm text-dim">
                {phase === "taken_over"
                  ? "Another device started streaming to this camera, so this one stopped."
                  : phase === "invalid"
                    ? "This publish link was revoked or the camera was deleted. Ask for a new link."
                    : "Stream this device's camera to the crowd counter. Point it at the area to count."}
              </p>
            </div>
          )}
          {phase === "live" && server && (
            <div className="absolute inset-x-0 bottom-0 flex items-end justify-between bg-gradient-to-t from-black/80 to-transparent px-4 pt-10 pb-3 font-mono">
              <div>
                <div className="text-[10px] tracking-[0.14em] text-dim">IN ZONE</div>
                <div className="text-3xl leading-none font-semibold tabular-nums">{server.occupancy}</div>
              </div>
              <div className="text-right text-[10.5px] text-dim tabular-nums">
                {sent.fps.toFixed(0)} fps · {Math.round(sent.kbps)} kbps
              </div>
            </div>
          )}
          <Brackets />
        </div>

        {!secure || !supported ? (
          <div className="rounded border border-warn/40 bg-warn/5 p-3 text-sm text-dim">
            {!secure
              ? "Browsers only allow camera access on secure (HTTPS) pages. Open this link over https://, or on the computer running the server (localhost)."
              : "This browser can't access cameras. Try a recent Chrome, Safari or Firefox."}
          </div>
        ) : null}
        {error && <p role="alert" className="rounded border border-alert/40 bg-alert/10 px-3 py-2 text-sm text-alert">{error}</p>}

        <div className="grid grid-cols-[1fr_auto] gap-2">
          {active ? (
            <button className="btn-danger h-11" onClick={stop}><CameraOff size={16} /> Stop</button>
          ) : (
            <button className="btn-primary h-11" disabled={!secure || !supported || phase === "invalid"} onClick={start}>
              {phase === "taken_over" ? <><RefreshCcw size={16} /> Take back over</> : <><CameraIcon size={16} /> Start camera</>}
            </button>
          )}
          <button className="btn-secondary h-11 w-11 px-0" onClick={flip} aria-label="Switch camera" title="Switch camera">
            <SwitchCamera size={17} />
          </button>
        </div>

        <div className="panel grid gap-4 p-4 sm:grid-cols-2">
          <div>
            <div className="eyebrow mb-1.5 text-dim">Quality</div>
            <Segmented<Quality> label="Quality" value={quality} onChange={setQuality}
              options={[{ value: "low", label: "640" }, { value: "standard", label: "960" }, { value: "high", label: "1280" }]} />
          </div>
          <div>
            <div className="eyebrow mb-1.5 text-dim">Frames / second</div>
            <Segmented<number> label="Frames per second" value={fps} onChange={setFps}
              options={[5, 10, 15].map((n) => ({ value: n, label: String(n) }))} />
          </div>
          <p className="text-xs text-mute sm:col-span-2">
            Keep this page open and the screen on while streaming. Lower quality or frame rate on slow connections.
          </p>
        </div>
      </main>
    </div>
  );
}
