import { useSyncExternalStore } from "react";

/**
 * Why live video is paused, or null when it may play. Video is the one thing whose cost grows
 * with every viewer (bandwidth, and on a CDN, money), so it stops when nobody is watching:
 *
 * - hidden:  the tab is in the background; resumes when it's visible again.
 * - idle:    no input for the server's idle timeout; resumes on any input.
 * - busy:    the server is at its video viewer limit; retries by itself after a delay.
 * - expired: the server ended a long video session; resumes only when the viewer asks, so an
 *            abandoned tab stays paused.
 *
 * Counts, alerts and incidents are unaffected: they come over the status socket.
 */
export type VideoPause = "hidden" | "idle" | "busy" | "expired" | null;

export const BUSY_RETRY_MS = 30_000;

export class VideoGate {
  private pause: VideoPause = null;
  private listeners = new Set<() => void>();
  private idleMs: number | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | undefined;
  private busyTimer: ReturnType<typeof setTimeout> | undefined;

  get state(): VideoPause {
    return this.pause;
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** From /api/config. null disables the idle pause. */
  setIdleTimeout(seconds: number | null) {
    this.idleMs = seconds ? seconds * 1000 : null;
    this.activity();
  }

  /** Any viewer input: restarts the idle clock, and lifts an idle pause. */
  activity() {
    clearTimeout(this.idleTimer);
    if (this.idleMs !== null) {
      this.idleTimer = setTimeout(() => this.pause === null && this.set("idle"), this.idleMs);
    }
    if (this.pause === "idle") this.set(null);
  }

  setHidden(hidden: boolean) {
    if (hidden && this.pause === null) this.set("hidden");
    else if (!hidden && this.pause === "hidden") {
      this.set(null);
      this.activity();
    }
  }

  busy() {
    this.set("busy");
    clearTimeout(this.busyTimer);
    this.busyTimer = setTimeout(() => this.pause === "busy" && this.set(null), BUSY_RETRY_MS);
  }

  expired() {
    this.set("expired");
  }

  /** The viewer asked for video back (Resume / Retry now). */
  resume() {
    clearTimeout(this.busyTimer);
    this.set(null);
    this.activity();
  }

  private set(pause: VideoPause) {
    if (pause === this.pause) return;
    this.pause = pause;
    this.listeners.forEach((fn) => fn());
  }
}

export const videoGate = new VideoGate();

let attached = false;

/** Wires the page's visibility and input events to the gate (once per page). */
export function attachVideoGate(idleTimeoutS: number | null) {
  videoGate.setIdleTimeout(idleTimeoutS);
  if (attached || typeof document === "undefined") return;
  attached = true;
  document.addEventListener("visibilitychange", () => videoGate.setHidden(document.hidden));
  videoGate.setHidden(document.hidden);
  let last = 0;
  const onInput = () => {
    const now = Date.now();
    if (now - last > 1000) {
      last = now;
      videoGate.activity();
    }
  };
  for (const event of ["pointerdown", "pointermove", "keydown", "wheel", "touchstart"]) {
    window.addEventListener(event, onInput, { passive: true });
  }
}

export function useVideoPause(): VideoPause {
  return useSyncExternalStore(videoGate.subscribe, () => videoGate.state, () => null);
}
