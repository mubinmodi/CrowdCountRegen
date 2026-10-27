import { useQuery } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";
import { useSearchParams } from "react-router";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { PageHeader } from "../components/Shell";
import { cx, ErrorNote, Panel, Readout, Segmented } from "../components/ui";
import { api, type Analytics, type AnalyticsBucket } from "../lib/api";
import { chartAxis, chartTooltip, colors, fmt } from "../lib/theme";

const RANGES = [
  { value: "1h", hours: 1, label: "1H" },
  { value: "24h", hours: 24, label: "24H" },
  { value: "7d", hours: 24 * 7, label: "7D" },
  { value: "30d", hours: 24 * 30, label: "30D" },
] as const;
type RangeKey = (typeof RANGES)[number]["value"];

type ChartRow = Partial<AnalyticsBucket> & { t: number };

/** One row per bucket across the whole range; buckets without data (camera off) stay empty. */
function fillRange(a: Analytics): ChartRow[] {
  const byStart = new Map(a.buckets.map((b) => [Date.parse(b.start), b]));
  const step = a.bucket_minutes * 60_000;
  const rows: ChartRow[] = [];
  for (let t = Date.parse(a.range_start); t <= Date.parse(a.range_end); t += step) {
    rows.push({ ...byStart.get(t), t });
  }
  return rows;
}

/** Average occupancy by local hour of day, from buckets of an hour or less. */
function hourProfile(a: Analytics) {
  if (a.bucket_minutes > 60) return null;
  const sums = Array.from({ length: 24 }, () => ({ total: 0, n: 0 }));
  for (const b of a.buckets) {
    const slot = sums[new Date(b.start).getHours()]!;
    slot.total += b.avg_occupancy;
    slot.n += 1;
  }
  return sums.map((s, hour) => ({ hour, avg: s.n ? s.total / s.n : null }));
}

function tick(ms: number, hours: number) {
  const d = new Date(ms);
  if (hours <= 24) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

const stamp = (v: unknown) => new Date(Number(v)).toLocaleString([], { hour12: false });

export function AnalyticsPage() {
  const [params, setParams] = useSearchParams();
  const range = RANGES.find((r) => r.value === params.get("range")) ?? RANGES[1];
  const cameraId = params.get("camera") ? Number(params.get("camera")) : undefined;
  const update = (key: string, value: string | undefined) =>
    setParams(
      (p) => {
        if (value === undefined) p.delete(key);
        else p.set(key, value);
        return p;
      },
      { replace: true },
    );

  const cameras = useQuery({ queryKey: ["cameras"], queryFn: api.cameras });
  const data = useQuery({
    queryKey: ["analytics", cameraId, range.hours],
    queryFn: () => api.analytics({ cameraId, hours: range.hours }),
    refetchInterval: 60_000,
    placeholderData: (prev) => prev,
  });

  const a = data.data;
  const rows = a ? fillRange(a) : [];
  const hasData = (a?.buckets.length ?? 0) > 0;
  const coverage = a && rows.length ? Math.round((a.buckets.length / rows.length) * 100) : 0;
  const profile = a ? hourProfile(a) : null;
  const profileMax = Math.max(1, ...(profile ?? []).map((p) => p.avg ?? 0));
  const bucketLabel = a
    ? `${a.bucket_minutes >= 60 ? `${a.bucket_minutes / 60}H` : `${a.bucket_minutes}M`} BUCKETS`
    : "";

  return (
    <>
      <PageHeader title="Analytics" description="Recorded once a minute while cameras run.">
        <div className="relative">
          <select aria-label="Camera" className="field h-8 appearance-none pr-8 font-mono text-[12px]"
            value={cameraId ?? ""} onChange={(e) => update("camera", e.target.value || undefined)}>
            <option value="">ALL CAMERAS</option>
            {cameras.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <ChevronDown size={14} className="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 text-mute" />
        </div>
        <Segmented<RangeKey> label="Time range" value={range.value} onChange={(v) => update("range", v)}
          options={RANGES.map((r) => ({ value: r.value, label: r.label }))} />
      </PageHeader>

      <ErrorNote error={data.error} />

      <Panel className="overflow-hidden" bodyClassName="grid grid-cols-2 gap-px bg-line lg:grid-cols-4">
        <div className="bg-panel p-4">
          <Readout label="Peak occupancy" value={a ? a.summary.peak_occupancy : "—"} tone="signal"
            sub={a?.summary.peak_at ? stamp(Date.parse(a.summary.peak_at)) : "no data yet"} />
        </div>
        <div className="bg-panel p-4">
          <Readout label="Avg occupancy" value={a ? a.summary.avg_occupancy.toFixed(1) : "—"} sub="people in zone / min" />
        </div>
        <div className="bg-panel p-4">
          <Readout label="Unique visitors" value={a ? fmt.format(a.summary.total_entries) : "—"} sub="tracked zone entries" />
        </div>
        <div className="bg-panel p-4">
          <Readout label="Coverage" value={a ? `${coverage}%` : "—"} sub="of buckets have data" />
        </div>
      </Panel>

      {data.isSuccess && !hasData ? (
        <div className="panel mt-4 flex flex-col items-center justify-center gap-2 bg-grid px-6 py-16 text-center">
          <p className="font-mono text-[12px] tracking-[0.14em] text-mute">NO SAMPLES IN THIS WINDOW</p>
          <p className="max-w-sm text-sm text-dim">
            Counts are written once a minute while a camera is running. Try a longer range.
          </p>
        </div>
      ) : (
        <div className={cx("mt-4 grid gap-4 xl:grid-cols-2", data.isPlaceholderData && "opacity-70")}>
          <Panel title="Occupancy" className="xl:col-span-2"
            actions={<Legend items={[["Peak", colors.zone], ["Average", colors.signal]]} />}>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
                  <defs>
                    <linearGradient id="avgFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={colors.signal} stopOpacity={0.3} />
                      <stop offset="100%" stopColor={colors.signal} stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={colors.line} vertical={false} />
                  <XAxis dataKey="t" {...chartAxis} tickFormatter={(v) => tick(v, range.hours)} minTickGap={40} />
                  <YAxis {...chartAxis} allowDecimals={false} />
                  <Tooltip {...chartTooltip} labelFormatter={stamp} cursor={{ stroke: colors.lineStrong }} />
                  <Area type="monotone" dataKey="avg_occupancy" name="Average" stroke={colors.signal} strokeWidth={1.5}
                    fill="url(#avgFill)" dot={{ r: 2, fill: colors.signal, strokeWidth: 0 }} isAnimationActive={false} />
                  <Line type="stepAfter" dataKey="peak_occupancy" name="Peak" stroke={colors.zone} strokeWidth={1.25}
                    strokeDasharray="3 3" dot={{ r: 2, fill: colors.zone, strokeWidth: 0 }} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-1 text-right font-mono text-[10px] tracking-wider text-mute">{bucketLabel}</div>
          </Panel>

          <Panel title="Entries" actions={<span className="font-mono text-[10px] tracking-wider text-mute">{bucketLabel}</span>}>
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
                  <CartesianGrid stroke={colors.line} vertical={false} />
                  <XAxis dataKey="t" {...chartAxis} tickFormatter={(v) => tick(v, range.hours)} minTickGap={40} />
                  <YAxis {...chartAxis} allowDecimals={false} />
                  <Tooltip {...chartTooltip} labelFormatter={stamp} cursor={{ fill: colors.line }} />
                  <Bar dataKey="entries" name="Entries" fill={colors.info} radius={[2, 2, 0, 0]} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Panel>

          <Panel title="Busiest hours" actions={<span className="font-mono text-[10px] tracking-wider text-mute">AVG BY HOUR</span>}>
            {profile ? (
              <div>
                <div className="grid h-48 items-end gap-[3px]" style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }}>
                  {profile.map((p) => (
                    <div key={p.hour} className="group relative h-full">
                      <div
                        className={cx("absolute inset-x-0 bottom-0 rounded-t-[2px]", p.avg === null && "h-px bg-line-strong")}
                        style={p.avg === null ? undefined : {
                          height: `${Math.max(2, (p.avg / profileMax) * 100)}%`,
                          background: colors.signal,
                          opacity: 0.25 + 0.75 * (p.avg / profileMax),
                        }}
                      />
                      <div className="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1 hidden -translate-x-1/2 rounded border border-line-strong bg-panel px-1.5 py-0.5 font-mono text-[10.5px] whitespace-nowrap group-hover:block">
                        {String(p.hour).padStart(2, "0")}:00 · {p.avg === null ? "no data" : p.avg.toFixed(1)}
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-2 flex justify-between font-mono text-[10px] text-mute">
                  {[0, 6, 12, 18, 23].map((h) => <span key={h}>{String(h).padStart(2, "0")}</span>)}
                </div>
              </div>
            ) : (
              <p className="flex h-48 items-center justify-center text-center font-mono text-[11px] tracking-wider text-mute">
                SELECT 7D OR LESS FOR HOURLY DETAIL
              </p>
            )}
          </Panel>
        </div>
      )}
    </>
  );
}

function Legend({ items }: { items: [string, string][] }) {
  return (
    <span className="flex gap-3 font-mono text-[10.5px] text-dim">
      {items.map(([label, color]) => (
        <span key={label} className="flex items-center gap-1.5">
          <span className="h-0.5 w-3" style={{ background: color }} />
          {label.toUpperCase()}
        </span>
      ))}
    </span>
  );
}
