import { Area, AreaChart, ResponsiveContainer, Tooltip, YAxis } from "recharts";
import type { LivePoint } from "../lib/live";
import { chartTooltip, colors } from "../lib/theme";

/** Small live trend of one series from the rolling WebSocket history. */
export function Sparkline({
  data,
  dataKey,
  color = colors.signal,
  height = 56,
}: {
  data: LivePoint[];
  dataKey: string;
  color?: string;
  height?: number;
}) {
  const id = `spark-${dataKey}`;
  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 0, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <YAxis hide allowDecimals={false} domain={[0, (max: number) => Math.max(4, Math.ceil(max * 1.2))]} />
          <Tooltip
            {...chartTooltip}
            cursor={{ stroke: colors.lineStrong }}
            labelFormatter={(_, payload) => {
              const t = payload?.[0]?.payload?.t;
              return t ? new Date(t).toLocaleTimeString([], { hour12: false }) : "";
            }}
            formatter={(v) => [v, "people"]}
          />
          <Area
            type="monotone"
            dataKey={dataKey}
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#${id})`}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
