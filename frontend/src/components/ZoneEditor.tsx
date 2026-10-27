import { Eraser, RefreshCw, Undo2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { snapshotUrl, type Point } from "../lib/api";
import { colors } from "../lib/theme";
import { hitTest, toNormalized, toSvgPoints } from "../lib/zone";
import { Brackets, cx } from "./ui";

interface Props {
  cameraId: number;
  value: Point[] | null;
  onChange: (zone: Point[] | null) => void;
  danger?: boolean; // draw as a danger zone
}

/**
 * Draw the counting zone on a still frame from the camera. Click to add points, drag a
 * point to move it, double-click a point to remove it. No zone = count the whole frame.
 */
export function ZoneEditor({ cameraId, value, onChange, danger = false }: Props) {
  const stroke = danger ? colors.alert : colors.zone;
  const fill = danger ? "rgb(255 77 94 / 0.2)" : "rgb(255 138 61 / 0.16)";
  const points = value ?? [];
  const surface = useRef<HTMLDivElement>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  const [hover, setHover] = useState<number>(-1);
  const [frameVersion, setFrameVersion] = useState(() => Date.now());
  const [frameState, setFrameState] = useState<"loading" | "ok" | "waiting">("loading");

  // The camera may still be connecting; keep retrying until a frame is available.
  useEffect(() => {
    if (frameState !== "waiting") return;
    const id = setTimeout(() => setFrameVersion(Date.now()), 2000);
    return () => clearTimeout(id);
  }, [frameState, frameVersion]);

  const pointerPos = (e: React.PointerEvent | React.MouseEvent): Point =>
    toNormalized(e.clientX, e.clientY, surface.current!.getBoundingClientRect());

  const setPoints = (next: Point[]) => onChange(next.length ? next : null);

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const p = pointerPos(e);
    const hit = hitTest(points, p);
    if (hit >= 0) {
      setDragging(hit);
      surface.current!.setPointerCapture(e.pointerId);
    } else {
      setPoints([...points, p]);
    }
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const p = pointerPos(e);
    if (dragging === null) {
      setHover(hitTest(points, p));
      return;
    }
    setPoints(points.map((q, i) => (i === dragging ? p : q)));
  };

  const onDoubleClick = (e: React.MouseEvent) => {
    const hit = hitTest(points, pointerPos(e));
    if (hit >= 0) setPoints(points.filter((_, i) => i !== hit));
  };

  const incomplete = points.length > 0 && points.length < 3;
  const status =
    points.length === 0
      ? "FULL FRAME · click the image to start a zone"
      : incomplete
        ? `NEED ${3 - points.length} MORE POINT${points.length === 2 ? "" : "S"} TO CLOSE`
        : danger
          ? `POLY·${points.length} · anyone whose feet enter this zone is an intrusion`
          : `POLY·${points.length} · feet inside the zone are counted`;

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className={cx("font-mono text-[11px] tracking-wider", incomplete ? "text-warn" : "text-dim")}>{status}</span>
        <div className="flex gap-1">
          <button type="button" className="btn-ghost h-7 px-2 text-xs" onClick={() => setFrameVersion(Date.now())} title="Grab a new frame">
            <RefreshCw size={13} /> Frame
          </button>
          <button type="button" className="btn-ghost h-7 px-2 text-xs" disabled={!points.length} onClick={() => setPoints(points.slice(0, -1))}>
            <Undo2 size={13} /> Undo
          </button>
          <button type="button" className="btn-ghost h-7 px-2 text-xs" disabled={!points.length} onClick={() => onChange(null)}>
            <Eraser size={13} /> Clear
          </button>
        </div>
      </div>

      <div
        ref={surface}
        className={cx(
          "relative touch-none overflow-hidden rounded border border-line-strong bg-bg bg-grid select-none",
          hover >= 0 || dragging !== null ? "cursor-grab" : "cursor-crosshair",
          dragging !== null && "cursor-grabbing",
        )}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={() => setDragging(null)}
        onPointerLeave={() => setHover(-1)}
        onDoubleClick={onDoubleClick}
      >
        <img
          src={`${snapshotUrl(cameraId)}?v=${frameVersion}`}
          alt="Current camera frame"
          draggable={false}
          className={cx("block w-full", frameState !== "ok" && "invisible aspect-video")}
          onLoad={() => setFrameState("ok")}
          onError={() => setFrameState("waiting")}
        />
        {frameState !== "ok" && (
          <div className="absolute inset-0 flex items-center justify-center font-mono text-[11px] tracking-[0.14em] text-mute">
            WAITING FOR FIRST FRAME…
          </div>
        )}
        {points.length === 0 && frameState === "ok" && (
          <div className="pointer-events-none absolute inset-0 shadow-[inset_0_0_0_2px_rgb(255_138_61/0.5)]" />
        )}
        <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1000 1000" preserveAspectRatio="none">
          {points.length >= 3 ? (
            <polygon points={toSvgPoints(points, 1000, 1000)} fill={fill} stroke={stroke}
              strokeWidth={2} vectorEffect="non-scaling-stroke" />
          ) : (
            <polyline points={toSvgPoints(points, 1000, 1000)} fill="none" stroke={stroke} strokeWidth={2}
              strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
          )}
        </svg>
        {points.map(([x, y], i) => (
          <div key={i} className="pointer-events-none absolute -translate-x-1/2 -translate-y-1/2" style={{ left: `${x * 100}%`, top: `${y * 100}%` }}>
            <div className={cx(
              "h-3.5 w-3.5 rounded-sm border-2 border-zone bg-bg transition-transform",
              (hover === i || dragging === i) && "scale-125 bg-zone",
            )} />
            <span className="absolute top-3 left-3 font-mono text-[10px] text-zone">{i + 1}</span>
          </div>
        ))}
        <Brackets />
      </div>
      <p className="mt-2 font-mono text-[10.5px] tracking-wide text-mute">
        CLICK add point · DRAG move · DOUBLE-CLICK remove
      </p>
    </div>
  );
}
