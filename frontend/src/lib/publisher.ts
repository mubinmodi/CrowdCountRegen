/**
 * Streams a <video> element's frames to /api/publish/{token} as JPEGs over a WebSocket.
 * Plain TypeScript (no React) so the send loop and reconnects have no render coupling.
 */

export type PublisherPhase = "live" | "reconnecting" | "taken_over" | "invalid";

export interface PublisherSettings {
  maxWidth: number;
  fps: number;
}

export interface PublisherEvents {
  onPhase: (phase: PublisherPhase) => void;
  onHello: (cameraName: string) => void;
  onStatus: (status: unknown) => void;
  onStats: (stats: { fps: number; kbps: number }) => void;
}

const JPEG_QUALITY = 0.7;
const MAX_BUFFERED = 512 * 1024; // skip frames rather than queue them on a slow uplink

export class Publisher {
  private socket: WebSocket | null = null;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private retry: ReturnType<typeof setTimeout> | undefined;
  private canvas = document.createElement("canvas");
  private running = false;
  private attempt = 0;
  private counters = { frames: 0, bytes: 0, since: 0 };

  constructor(
    private token: string,
    private video: HTMLVideoElement,
    private settings: () => PublisherSettings,
    private events: PublisherEvents,
  ) {}

  start(): void {
    this.running = true;
    this.counters = { frames: 0, bytes: 0, since: performance.now() };
    this.connect();
    this.tick();
  }

  stop(): void {
    this.running = false;
    clearTimeout(this.timer);
    clearTimeout(this.retry);
    const ws = this.socket;
    this.socket = null;
    ws?.close();
  }

  private connect(): void {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/publish/${this.token}`);
    this.socket = ws;
    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "hello") {
        this.attempt = 0;
        this.events.onHello(msg.camera);
        this.events.onPhase("live");
      } else if (msg.type === "status") {
        this.events.onStatus(msg);
      }
    };
    ws.onclose = (e) => {
      if (this.socket !== ws || !this.running) return; // we closed it ourselves
      if (e.code === 4404 || e.code === 4409) {
        this.stop();
        this.events.onPhase(e.code === 4404 ? "invalid" : "taken_over");
        return;
      }
      this.events.onPhase("reconnecting");
      this.retry = setTimeout(() => this.running && this.connect(), Math.min(10_000, 500 * 2 ** this.attempt++));
    };
  }

  private tick = (): void => {
    if (!this.running) return;
    const { maxWidth, fps } = this.settings();
    const ws = this.socket;
    const v = this.video;
    if (ws?.readyState === WebSocket.OPEN && v.videoWidth && ws.bufferedAmount < MAX_BUFFERED) {
      const width = Math.min(maxWidth, v.videoWidth);
      this.canvas.width = width;
      this.canvas.height = Math.round((v.videoHeight / v.videoWidth) * width);
      this.canvas.getContext("2d")!.drawImage(v, 0, 0, this.canvas.width, this.canvas.height);
      this.canvas.toBlob(
        (blob) => {
          if (blob && this.socket?.readyState === WebSocket.OPEN) {
            this.socket.send(blob);
            this.counters.frames += 1;
            this.counters.bytes += blob.size;
          }
        },
        "image/jpeg",
        JPEG_QUALITY,
      );
    }
    const elapsed = (performance.now() - this.counters.since) / 1000;
    if (elapsed >= 1) {
      this.events.onStats({
        fps: this.counters.frames / elapsed,
        kbps: (this.counters.bytes * 8) / 1000 / elapsed,
      });
      this.counters = { frames: 0, bytes: 0, since: performance.now() };
    }
    this.timer = setTimeout(this.tick, 1000 / fps);
  };
}
