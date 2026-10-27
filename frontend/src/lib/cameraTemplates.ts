/**
 * Stream URL patterns for common IP camera brands, so users don't have to look them up.
 * {host} {port} {channel} are filled from the form; `quality` picks the main or sub stream.
 * Paths are the vendors' documented defaults; firmware can differ, so "Test connection" is
 * always the final word.
 */

export type Quality = "main" | "sub";

export interface CameraTemplate {
  id: string;
  brand: string;
  kind: "stream" | "snapshot";
  port: number;
  build: (p: { host: string; port: number; channel: number; quality: Quality }) => string;
  note?: string;
  channels?: boolean; // whether the channel number matters (NVRs / multi-sensor)
}

const hostPort = (host: string, port: number, standard: number) =>
  port === standard ? host : `${host}:${port}`;

export const TEMPLATES: CameraTemplate[] = [
  {
    id: "hikvision",
    brand: "Hikvision / HiLook / Annke",
    kind: "stream",
    port: 554,
    channels: true,
    build: ({ host, port, channel, quality }) =>
      `rtsp://${hostPort(host, port, 554)}/Streaming/Channels/${channel}0${quality === "main" ? 1 : 2}`,
  },
  {
    id: "dahua",
    brand: "Dahua / Amcrest / Lorex",
    kind: "stream",
    port: 554,
    channels: true,
    build: ({ host, port, channel, quality }) =>
      `rtsp://${hostPort(host, port, 554)}/cam/realmonitor?channel=${channel}&subtype=${quality === "main" ? 0 : 1}`,
  },
  {
    id: "reolink",
    brand: "Reolink",
    kind: "stream",
    port: 554,
    channels: true,
    build: ({ host, port, channel, quality }) =>
      `rtsp://${hostPort(host, port, 554)}/h264Preview_${String(channel).padStart(2, "0")}_${quality}`,
    note: "Newer 4K models use h265Preview_01_main.",
  },
  {
    id: "axis",
    brand: "Axis",
    kind: "stream",
    port: 554,
    build: ({ host, port, quality }) =>
      `rtsp://${hostPort(host, port, 554)}/axis-media/media.amp${quality === "sub" ? "?resolution=640x360" : ""}`,
  },
  {
    id: "tapo",
    brand: "TP-Link Tapo / VIGI",
    kind: "stream",
    port: 554,
    build: ({ host, port, quality }) => `rtsp://${hostPort(host, port, 554)}/stream${quality === "main" ? 1 : 2}`,
    note: "Create a camera account in the Tapo app (Advanced settings → Camera account).",
  },
  {
    id: "unifi",
    brand: "UniFi Protect",
    kind: "stream",
    port: 7441,
    build: ({ host, port }) => `rtsps://${hostPort(host, port, 7441)}/<stream-id>?enableSrtp`,
    note: "Enable RTSP per camera in Protect and copy its stream id into the URL.",
  },
  {
    id: "hanwha",
    brand: "Hanwha / Wisenet",
    kind: "stream",
    port: 554,
    build: ({ host, port, quality }) =>
      `rtsp://${hostPort(host, port, 554)}/profile${quality === "main" ? 2 : 3}/media.smp`,
  },
  {
    id: "foscam",
    brand: "Foscam",
    kind: "stream",
    port: 88,
    build: ({ host, port, quality }) => `rtsp://${hostPort(host, port, 554)}/video${quality === "main" ? "Main" : "Sub"}`,
  },
  {
    id: "ipwebcam",
    brand: "IP Webcam (Android app)",
    kind: "stream",
    port: 8080,
    build: ({ host, port }) => `http://${host}:${port}/video`,
    note: "Or skip the app: use the Phone / browser source type instead.",
  },
  {
    id: "snapshot-cgi",
    brand: "Generic snapshot (CGI)",
    kind: "snapshot",
    port: 80,
    build: ({ host, port }) => `http://${hostPort(host, port, 80)}/cgi-bin/snapshot.cgi`,
  },
];
