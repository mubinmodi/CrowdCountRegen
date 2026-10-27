import { useEffect, type RefObject } from "react";

type Listener = (url: string) => void;

/**
 * One WebSocket to /api/ws/frames carrying every camera's latest small JPEG, shared by all
 * the tiles on the page. Each message is a 4-byte camera id followed by the image.
 *
 * Why not one MJPEG <img> per tile: over HTTP/1.1 (local dev, plain nginx) a browser opens
 * at most six connections per host, and a wall of never-ending MJPEG responses uses them all
 * up, stalling every API call. Frames are handed straight to <img> elements, without going
 * through React state, so a wall at 8 fps doesn't re-render the page 50 times a second.
 */
class FrameFeed {
  private socket: WebSocket | null = null;
  private listeners = new Map<number, Set<Listener>>();
  private urls = new Map<number, string>();
  private retry: ReturnType<typeof setTimeout> | undefined;
  private idle: ReturnType<typeof setTimeout> | undefined;
  private attempt = 0;

  subscribe(cameraId: number, listener: Listener): () => void {
    clearTimeout(this.idle);
    let set = this.listeners.get(cameraId);
    if (!set) this.listeners.set(cameraId, (set = new Set()));
    set.add(listener);
    const last = this.urls.get(cameraId);
    if (last) listener(last);
    if (!this.socket) this.connect();
    return () => {
      set.delete(listener);
      if (set.size === 0) this.listeners.delete(cameraId);
      // Navigating between pages unmounts and remounts tiles; don't reconnect in between.
      if (this.listeners.size === 0) this.idle = setTimeout(() => this.disconnect(), 5000);
    };
  }

  private connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const socket = new WebSocket(`${proto}://${location.host}/api/ws/frames?size=small`);
    socket.binaryType = "arraybuffer";
    socket.onopen = () => (this.attempt = 0);
    socket.onmessage = (event) => {
      const data = event.data as ArrayBuffer;
      const cameraId = new DataView(data).getUint32(0);
      const url = URL.createObjectURL(new Blob([data.slice(4)], { type: "image/jpeg" }));
      const previous = this.urls.get(cameraId);
      this.urls.set(cameraId, url);
      this.listeners.get(cameraId)?.forEach((fn) => fn(url));
      if (previous) URL.revokeObjectURL(previous);
    };
    socket.onclose = (event) => {
      if (this.socket !== socket) return;
      this.socket = null;
      if (this.listeners.size === 0 || event.code === 4401) return;
      this.retry = setTimeout(() => this.connect(), Math.min(10_000, 500 * 2 ** this.attempt++));
    };
    this.socket = socket;
  }

  private disconnect() {
    clearTimeout(this.retry);
    const socket = this.socket;
    this.socket = null;
    socket?.close();
    this.urls.forEach((url) => URL.revokeObjectURL(url));
    this.urls.clear();
  }
}

const feed = new FrameFeed();

/** Keeps `img.src` on the camera's newest frame while the component is mounted. */
export function useCameraFrames(cameraId: number, img: RefObject<HTMLImageElement | null>, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    return feed.subscribe(cameraId, (url) => {
      if (img.current) img.current.src = url;
    });
  }, [cameraId, img, enabled]);
}
