import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, ExternalLink, RefreshCw, TriangleAlert } from "lucide-react";
import QRCode from "qrcode";
import { useEffect, useState } from "react";
import { api, type Camera } from "../lib/api";
import { useLive } from "../lib/live";
import { usePersistentState } from "../lib/storage";
import { ConfirmDialog, Field } from "./ui";

const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

/** Publish link + QR code for a browser camera, with live publisher status. */
export function PublishPanel({ camera }: { camera: Camera }) {
  const qc = useQueryClient();
  const live = useLive();
  const status = live.statuses.get(camera.id);
  const [base, setBase] = usePersistentState("cc.publish.base", location.origin);
  const [qr, setQr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmRotate, setConfirmRotate] = useState(false);

  const url = `${base.replace(/\/+$/, "")}/publish/${camera.publish_token}`;
  const host = (() => {
    try {
      return new URL(base);
    } catch {
      return null;
    }
  })();
  const isLocal = host ? LOCAL_HOSTS.has(host.hostname) : false;
  const insecure = host ? host.protocol === "http:" && !isLocal : false;

  useEffect(() => {
    let cancelled = false;
    QRCode.toDataURL(url, { margin: 1, width: 360, color: { dark: "#05070a", light: "#dfe6ee" } }).then(
      (data) => !cancelled && setQr(data),
      () => !cancelled && setQr(null),
    );
    return () => {
      cancelled = true;
    };
  }, [url]);

  const rotate = useMutation({
    mutationFn: () => api.rotatePublishToken(camera.id),
    onSuccess: (saved) => {
      qc.setQueryData(["camera", saved.id], saved);
      setConfirmRotate(false);
    },
  });

  const copy = async () => {
    await navigator.clipboard.writeText(url);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 sm:flex-row lg:flex-col xl:flex-row">
        <div className="shrink-0 self-center rounded bg-ink p-2 sm:self-start lg:self-center xl:self-start">
          {qr ? <img src={qr} alt="QR code for the publish link" className="h-40 w-40" /> : <div className="h-40 w-40" />}
        </div>
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex items-center gap-2 font-mono text-[11px] tracking-wider">
            <span className={status?.publisher_connected ? "h-2 w-2 animate-pulse rounded-full bg-signal" : "h-2 w-2 rounded-full bg-mute"} />
            <span className={status?.publisher_connected ? "text-signal" : "text-mute"}>
              {status?.publisher_connected ? "DEVICE CONNECTED · STREAMING" : "NO DEVICE CONNECTED"}
            </span>
          </div>
          <p className="text-sm text-dim">
            Scan with a phone, or open the link on any laptop, then tap <span className="text-ink">Start camera</span>.
            Opening it on a second device takes over from the first.
          </p>
        </div>
      </div>

      <div className="flex gap-1.5">
        <input readOnly aria-label="Publish link" className="field min-w-0 font-mono text-[11px]" value={url} onFocus={(e) => e.target.select()} />
        <button type="button" className="btn-secondary w-9 shrink-0 px-0" onClick={copy} aria-label="Copy link" title={copied ? "Copied" : "Copy"}>
          <Copy size={14} className={copied ? "text-signal" : ""} />
        </button>
        <a href={url} target="_blank" rel="noreferrer" className="btn-secondary w-9 shrink-0 px-0" aria-label="Open publish page" title="Open here">
          <ExternalLink size={14} />
        </a>
      </div>

      {(isLocal || insecure) && (
        <div className="flex gap-2 rounded border border-warn/40 bg-warn/5 p-3 text-xs text-dim">
          <TriangleAlert size={14} className="mt-0.5 shrink-0 text-warn" />
          <div>
            {isLocal
              ? "This link points at localhost, which a phone can't reach. Set the base URL below to this computer's LAN address."
              : "Phones only allow camera access on HTTPS pages. Serve the app over HTTPS (in development: npm run dev:lan)."}
          </div>
        </div>
      )}

      <Field label="Base URL" htmlFor="publish-base" hint="How devices reach this console, e.g. https://192.168.1.23:5173">
        <input id="publish-base" className="field font-mono text-[12px]" value={base} onChange={(e) => setBase(e.target.value)} />
      </Field>

      <button type="button" className="btn-ghost h-7 px-2 text-xs" onClick={() => setConfirmRotate(true)}>
        <RefreshCw size={13} /> New link (revokes this one)
      </button>

      <ConfirmDialog open={confirmRotate} title="Replace publish link"
        body="Anyone using the current link (or QR code) is disconnected and must scan the new one."
        confirmLabel={rotate.isPending ? "Replacing…" : "Replace link"} busy={rotate.isPending}
        onConfirm={() => rotate.mutate()} onCancel={() => setConfirmRotate(false)} />
    </div>
  );
}
