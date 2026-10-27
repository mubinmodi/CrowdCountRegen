export type Point = [number, number];

export interface User {
  id: number;
  email: string;
  name: string;
}

export type SourceKind = "stream" | "snapshot" | "browser" | "webcam" | "file";

/** occupancy: alert above a people limit. danger_zone: alert when anyone (above the limit, default 0) is inside. */
export type CameraMode = "occupancy" | "danger_zone";

export interface SourceOptions {
  rtsp_transport?: "tcp" | "udp" | "auto";
  snapshot_interval_ms?: number;
  insecure_tls?: boolean;
  width?: number;
}

export interface Camera {
  id: number;
  name: string;
  kind: SourceKind;
  source: string; // never contains credentials
  username: string | null;
  has_password: boolean;
  options: SourceOptions | null;
  zone: Point[] | null;
  threshold: number | null;
  mode: CameraMode;
  description: string | null;
  scenario: string | null; // demo scenario key: can be reset, not removed or re-sourced
  publish_token: string | null; // browser cameras only
  created_at: string;
}

/** Source fields for create/patch/probe. Omit `password` to keep the stored one; null clears it. */
export interface SourceInput {
  kind?: SourceKind;
  source?: string;
  username?: string | null;
  password?: string | null;
  options?: SourceOptions | null;
}

export type CameraInput = SourceInput & Partial<Pick<Camera, "name" | "zone" | "threshold" | "mode" | "description">>;

export type CameraState = "starting" | "connecting" | "running" | "waiting" | "error" | "stopped";

export interface StreamInfo {
  width: number | null;
  height: number | null;
  fps: number | null;
  codec: string | null;
  live: boolean;
}

export interface CameraStatus {
  camera_id: number;
  state: CameraState;
  error: string | null;
  error_code: string | null;
  hint: string | null;
  occupancy: number;
  unique_entries: number;
  fps: number;
  stream: StreamInfo | null;
  reconnects: number;
  publisher_connected: boolean | null;
  alert_limit: number | null; // most people allowed in the zone; null = no alert
  over_limit: boolean; // running and above alert_limit (decided server-side)
}

export interface Incident {
  id: number;
  camera_id: number;
  started_at: string;
  ended_at: string | null; // null while still in progress
  peak: number;
  limit: number;
  has_snapshot: boolean;
}

export interface AppConfig {
  demo_mode: boolean;
  detector: string;
  video_idle_timeout_s: number | null; // pause live video after this long without input
}

export interface ProbeResult {
  ok: boolean;
  error_code: string | null;
  message: string | null;
  hint: string | null;
  stream: StreamInfo | null;
  first_frame_ms: number | null;
  preview: string | null;
}

export interface OnvifDevice {
  xaddr: string;
  host: string;
  name: string | null;
  hardware: string | null;
}

export interface OnvifProfile {
  token: string;
  name: string | null;
  encoding: string | null;
  width: number | null;
  height: number | null;
  uri: string | null;
}

export interface OnvifStreams {
  manufacturer: string | null;
  model: string | null;
  profiles: OnvifProfile[];
}

export interface AnalyticsBucket {
  start: string;
  avg_occupancy: number;
  peak_occupancy: number;
  entries: number;
}

export interface Analytics {
  camera_id: number | null;
  range_start: string;
  range_end: string;
  bucket_minutes: number;
  buckets: AnalyticsBucket[];
  summary: {
    peak_occupancy: number;
    peak_at: string | null;
    avg_occupancy: number;
    total_entries: number;
  };
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

function errorMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: [{loc, msg}, ...]
    if (Array.isArray(detail) && detail[0]?.msg) {
      return detail.map((d: { loc?: unknown[]; msg: string }) => {
        const field = d.loc?.at(-1);
        return typeof field === "string" ? `${field}: ${d.msg}` : d.msg;
      }).join("; ");
    }
  }
  return fallback;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, errorMessage(data, res.statusText));
  return data as T;
}

export const api = {
  config: () => request<AppConfig>("GET", "/api/config"),
  me: () => request<User>("GET", "/api/auth/me"),
  login: (email: string, password: string) =>
    request<User>("POST", "/api/auth/login", { email, password }),
  signup: (name: string, email: string, password: string) =>
    request<User>("POST", "/api/auth/signup", { name, email, password }),
  logout: () => request<void>("POST", "/api/auth/logout"),

  cameras: () => request<Camera[]>("GET", "/api/cameras"),
  camera: (id: number) => request<Camera>("GET", `/api/cameras/${id}`),
  createCamera: (input: CameraInput) => request<Camera>("POST", "/api/cameras", input),
  updateCamera: (id: number, input: Partial<CameraInput>) =>
    request<Camera>("PATCH", `/api/cameras/${id}`, input),
  deleteCamera: (id: number) => request<void>("DELETE", `/api/cameras/${id}`),
  probe: (input: SourceInput & { camera_id?: number }) =>
    request<ProbeResult>("POST", "/api/cameras/probe", input),
  rotatePublishToken: (id: number) => request<Camera>("POST", `/api/cameras/${id}/publish-token`),

  onvifDiscover: () => request<OnvifDevice[]>("POST", "/api/onvif/discover"),
  onvifStreams: (xaddr: string, username: string, password: string) =>
    request<OnvifStreams>("POST", "/api/onvif/streams", { xaddr, username, password }),

  incidents: (params: { cameraId?: number; limit?: number } = {}) => {
    const q = new URLSearchParams({ limit: String(params.limit ?? 100) });
    if (params.cameraId !== undefined) q.set("camera_id", String(params.cameraId));
    return request<Incident[]>("GET", `/api/incidents?${q}`);
  },
  resetDemo: () => request<Camera[]>("POST", "/api/demo/reset"),

  analytics: (params: { cameraId?: number; hours: number }) => {
    const q = new URLSearchParams({ hours: String(params.hours) });
    if (params.cameraId !== undefined) q.set("camera_id", String(params.cameraId));
    return request<Analytics>("GET", `/api/analytics?${q}`);
  },
};

/** `small` is a 480 px stream for grid tiles; the full stream is for enlarged views. */
export const streamUrl = (id: number, size: "full" | "small" = "full") =>
  `/api/cameras/${id}/stream.mjpg${size === "small" ? "?size=small" : ""}`;
export const snapshotUrl = (id: number) => `/api/cameras/${id}/snapshot.jpg`;
export const incidentSnapshotUrl = (id: number) => `/api/incidents/${id}/snapshot.jpg`;
