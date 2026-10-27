import type { Point } from "./api";

const round = (v: number) => Math.round(v * 1000) / 1000;
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

/** Converts a pointer position to normalized [0, 1] image coordinates. */
export function toNormalized(
  clientX: number,
  clientY: number,
  rect: { left: number; top: number; width: number; height: number },
): Point {
  return [
    round(clamp01((clientX - rect.left) / rect.width)),
    round(clamp01((clientY - rect.top) / rect.height)),
  ];
}

/** Index of the point within `radius` (normalized units) of `p`, or -1. */
export function hitTest(points: Point[], p: Point, radius = 0.025): number {
  let best = -1;
  let bestDist = radius;
  points.forEach(([x, y], i) => {
    const d = Math.hypot(x - p[0], y - p[1]);
    if (d <= bestDist) {
      best = i;
      bestDist = d;
    }
  });
  return best;
}

export const toSvgPoints = (points: Point[], w: number, h: number) =>
  points.map(([x, y]) => `${x * w},${y * h}`).join(" ");
