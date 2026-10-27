/** Hex values mirroring the @theme tokens in index.css, for SVG/canvas consumers (charts). */
export const colors = {
  bg: "#05070a",
  panel: "#0a0e13",
  line: "#19212b",
  lineStrong: "#283340",
  ink: "#dfe6ee",
  dim: "#8b97a6",
  mute: "#56616f",
  signal: "#3ee08f",
  warn: "#f5b83d",
  alert: "#ff4d5e",
  info: "#4cc3ff",
  zone: "#ff8a3d",
  hazard: "#ffc400",
} as const;

export const chartAxis = {
  stroke: colors.mute,
  fontSize: 10.5,
  fontFamily: "JetBrains Mono Variable, ui-monospace, monospace",
  tickLine: false,
  axisLine: false,
} as const;

export const chartTooltip = {
  contentStyle: {
    background: colors.panel,
    border: `1px solid ${colors.lineStrong}`,
    borderRadius: 4,
    fontSize: 12,
    fontFamily: "JetBrains Mono Variable, ui-monospace, monospace",
  },
  labelStyle: { color: colors.dim, marginBottom: 4 },
  itemStyle: { padding: 0 },
} as const;

export const fmt = new Intl.NumberFormat();
