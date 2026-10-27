import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import type { CameraStatus } from "./api";

export interface LivePoint {
  t: number; // epoch ms
  total: number;
  [cameraId: string]: number;
}

export interface LiveState {
  connected: boolean;
  statuses: Map<number, CameraStatus>;
  history: LivePoint[]; // one point per second, most recent last
}

const HISTORY_SECONDS = 180;
const empty: LiveState = { connected: false, statuses: new Map(), history: [] };
const LiveContext = createContext<LiveState>(empty);

/** One WebSocket to /api/ws/live for the whole app, with a short rolling history. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LiveState>(empty);
  const lastPointAt = useRef(0);

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    let attempt = 0;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${proto}://${location.host}/api/ws/live`);
      socket.onopen = () => {
        attempt = 0;
        setState((s) => ({ ...s, connected: true }));
      };
      socket.onmessage = (event) => {
        const msg = JSON.parse(event.data) as { ts: number; cameras: CameraStatus[] };
        const statuses = new Map(msg.cameras.map((c) => [c.camera_id, c]));
        const now = msg.ts * 1000;
        const addPoint = now - lastPointAt.current >= 1000;
        if (addPoint) lastPointAt.current = now;
        setState((s) => {
          let history = s.history;
          if (addPoint) {
            const point: LivePoint = { t: now, total: 0 };
            for (const c of msg.cameras) {
              point[String(c.camera_id)] = c.occupancy;
              point.total += c.occupancy;
            }
            history = [...history, point].filter((p) => now - p.t <= HISTORY_SECONDS * 1000);
          }
          return { connected: true, statuses, history };
        });
      };
      socket.onclose = (event) => {
        setState((s) => ({ ...s, connected: false }));
        if (closed || event.code === 4401) return;
        // Exponential backoff, capped at 10 s.
        retry = setTimeout(connect, Math.min(10_000, 500 * 2 ** attempt++));
      };
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      socket?.close();
    };
  }, []);

  return <LiveContext.Provider value={state}>{children}</LiveContext.Provider>;
}

export const useLive = () => useContext(LiveContext);

/** Value of `key` in the history point closest to `secondsAgo` seconds before the latest. */
export function valueAgo(history: LivePoint[], key: string, secondsAgo: number): number | null {
  const last = history.at(-1);
  if (!last) return null;
  const target = last.t - secondsAgo * 1000;
  const past = history.find((p) => p.t >= target);
  return past && past !== last ? (past[key] ?? 0) : null;
}
