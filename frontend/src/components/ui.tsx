import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import type { CameraState } from "../lib/api";

export function cx(...classes: (string | false | null | undefined)[]) {
  return classes.filter(Boolean).join(" ");
}

export function Panel({
  title,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cx("panel", className)}>
      {(title || actions) && (
        <header className="flex min-h-10 items-center justify-between gap-3 border-b border-line px-3.5 py-1.5">
          <h2 className="eyebrow text-dim">{title}</h2>
          <div className="flex items-center gap-1.5">{actions}</div>
        </header>
      )}
      <div className={bodyClassName ?? "p-3.5"}>{children}</div>
    </section>
  );
}

const stateTone: Record<CameraState, { dot: string; text: string; label: string }> = {
  running: { dot: "bg-signal", text: "text-signal", label: "LIVE" },
  starting: { dot: "bg-info", text: "text-info", label: "STARTING" },
  connecting: { dot: "bg-warn", text: "text-warn", label: "CONNECTING" },
  waiting: { dot: "bg-info", text: "text-info", label: "STANDBY" },
  error: { dot: "bg-alert", text: "text-alert", label: "FAULT" },
  stopped: { dot: "bg-mute", text: "text-mute", label: "OFFLINE" },
};

export function StatusDot({ state, className }: { state: CameraState; className?: string }) {
  const tone = stateTone[state];
  return (
    <span className={cx("relative inline-flex h-2 w-2 shrink-0", className)}>
      {state === "running" && (
        <span className={cx("absolute inset-0 animate-ping rounded-full opacity-60", tone.dot)} />
      )}
      <span className={cx("relative h-2 w-2 rounded-full", tone.dot)} />
    </span>
  );
}

export function StatusTag({ state }: { state: CameraState }) {
  const tone = stateTone[state];
  return (
    <span className={cx("inline-flex items-center gap-1.5 font-mono text-[10.5px] tracking-wider", tone.text)}>
      <StatusDot state={state} />
      {tone.label}
    </span>
  );
}

/** A big monospace number with a stencil label: the console's main readout. */
export function Readout({
  label,
  value,
  sub,
  tone = "default",
  className,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "default" | "alert" | "signal";
  className?: string;
}) {
  return (
    <div className={cx("min-w-0", className)}>
      <div className="eyebrow">{label}</div>
      <div
        className={cx(
          "mt-1 font-mono text-[28px] leading-none font-semibold tabular-nums",
          tone === "alert" && "text-alert",
          tone === "signal" && "text-signal",
        )}
      >
        {value}
      </div>
      {sub && <div className="mt-1.5 truncate font-mono text-[11px] text-dim">{sub}</div>}
    </div>
  );
}

/** Change indicator such as ▲3 / ▼2 / ±0. */
export function Delta({ value }: { value: number | null }) {
  if (value === null) return <span className="text-mute">—</span>;
  if (value === 0) return <span className="text-mute">±0</span>;
  return value > 0 ? (
    <span className="text-warn">▲{value}</span>
  ) : (
    <span className="text-info">▼{Math.abs(value)}</span>
  );
}

/** Horizontal fill meter for occupancy vs. limit. Turns amber past 80%, red past 100%. */
export function Meter({ value, max }: { value: number; max: number | null }) {
  if (!max) return <div className="h-1 rounded-full bg-line" />;
  const ratio = value / max;
  const color = ratio > 1 ? "bg-alert" : ratio >= 0.8 ? "bg-warn" : "bg-signal";
  return (
    <div className="relative h-1 overflow-hidden rounded-full bg-line" role="meter"
      aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <div className={cx("h-full transition-[width] duration-500", color)}
        style={{ width: `${Math.min(100, ratio * 100)}%` }} />
    </div>
  );
}

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label}
      className="inline-flex h-8 items-center rounded border border-line-strong bg-bg p-0.5">
      {options.map((o) => (
        <button
          key={String(o.value)}
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            "h-full rounded-[3px] px-2.5 font-mono text-[11px] tracking-wide whitespace-nowrap transition-colors",
            o.value === value ? "bg-hover text-ink" : "text-mute hover:text-dim",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div>
      <label htmlFor={htmlFor} className="eyebrow mb-1.5 block text-dim">{label}</label>
      {children}
      {hint && <div className="mt-1.5 text-xs text-mute">{hint}</div>}
    </div>
  );
}

export function ErrorNote({ error }: { error: Error | null | undefined }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded border border-alert/40 bg-alert/10 px-3 py-2 font-mono text-xs text-alert">
      {error.message}
    </p>
  );
}

/** Corner brackets that frame a viewport, like a camera monitor. */
export function Brackets({ className }: { className?: string }) {
  const corner = "absolute h-3 w-3 border-dim/50";
  return (
    <div aria-hidden className={cx("pointer-events-none absolute inset-2", className)}>
      <span className={cx(corner, "top-0 left-0 border-t border-l")} />
      <span className={cx(corner, "top-0 right-0 border-t border-r")} />
      <span className={cx(corner, "bottom-0 left-0 border-b border-l")} />
      <span className={cx(corner, "right-0 bottom-0 border-r border-b")} />
    </div>
  );
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  busy,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onCancel}
      className="m-auto w-[min(92vw,420px)] rounded-md border border-line-strong bg-panel p-0 text-ink backdrop:bg-black/70 backdrop:backdrop-blur-sm"
    >
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <h2 className="eyebrow text-dim">{title}</h2>
        <button className="btn-ghost h-7 px-1.5" onClick={onCancel} aria-label="Close"><X size={14} /></button>
      </div>
      <div className="px-4 py-4 text-sm text-dim">{body}</div>
      <div className="flex justify-end gap-2 border-t border-line px-4 py-3">
        <button className="btn-secondary" onClick={onCancel}>Cancel</button>
        <button className="btn-danger" onClick={onConfirm} disabled={busy}>{confirmLabel}</button>
      </div>
    </dialog>
  );
}
