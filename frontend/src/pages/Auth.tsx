import { useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router";
import { BrandMark } from "../components/Shell";
import { Brackets, ErrorNote, Field } from "../components/ui";
import { useAuthActions, useCurrentUser } from "../lib/auth";
import { colors } from "../lib/theme";

const FEATURES = [
  ["DETECT", "YOLO26 or RF-DETR, on any RTSP, HTTP, webcam or file source"],
  ["TRACK", "ByteTrack IDs, so each visitor is counted once"],
  ["ZONE", "Count only inside the polygon you draw"],
  ["ALERT", "Flag a camera the moment it passes its limit"],
] as const;

/** Decorative monitor: a stylised scene with a zone and tracked figures. Not real data. */
function Illustration() {
  const people = [[18, 70], [30, 58], [44, 76], [58, 62], [70, 80], [82, 55], [52, 46], [88, 30], [12, 34]] as const;
  // Same rule as the backend: a person counts when their feet are inside the zone.
  const inZone = (x: number, y: number) => y > 40 && x > 10 + (92 - y) * 0.23 && x < 92 - (92 - y) * 0.23;
  const count = people.filter(([x, y]) => inZone(x, y)).length;
  return (
    <div className="relative aspect-video overflow-hidden rounded border border-line-strong bg-bg bg-grid" aria-hidden>
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
        <polygon points="22,40 80,38 92,92 10,92" fill="rgb(255 138 61 / 0.12)" stroke={colors.zone} strokeWidth="0.4" vectorEffect="non-scaling-stroke" />
      </svg>
      {people.map(([x, y], i) => {
        const inside = inZone(x, y);
        return (
          <div key={i} className="absolute -translate-x-1/2 -translate-y-full border"
            style={{ left: `${x}%`, top: `${y}%`, width: "5%", height: "18%", borderColor: inside ? colors.signal : colors.mute }} />
        );
      })}
      <div className="absolute top-2.5 left-3 flex items-center gap-2 font-mono text-[10px] tracking-[0.14em] text-ink">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-signal" /> CAM-01 · LOBBY
      </div>
      <div className="absolute right-3 bottom-2.5 font-mono text-[10px] tracking-[0.14em] text-dim">IN ZONE {String(count).padStart(2, "0")}</div>
      <Brackets />
    </div>
  );
}

function AuthShell({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <div className="grid min-h-dvh bg-bg lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden flex-col gap-10 overflow-hidden border-r border-line bg-panel bg-grid p-10 lg:flex">
        <div className="flex items-center gap-3">
          <BrandMark className="h-7 w-7 text-signal" />
          <div className="font-mono text-[13px] font-semibold tracking-[0.1em]">CROWDCOUNT</div>
        </div>
        <div className="my-auto max-w-lg">
          <h2 className="text-[28px] leading-tight font-semibold tracking-tight">
            How many people are in the room, right now?
          </h2>
          <div className="mt-6"><Illustration /></div>
          <dl className="mt-6 space-y-2.5">
            {FEATURES.map(([k, v]) => (
              <div key={k} className="flex gap-4 text-sm">
                <dt className="w-14 shrink-0 font-mono text-[11px] leading-5 tracking-[0.14em] text-signal">{k}</dt>
                <dd className="text-dim">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      </aside>

      <main className="flex items-center justify-center px-5 py-10">
        <div className="w-full max-w-[360px]">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <BrandMark className="h-6 w-6 text-signal" />
            <span className="font-mono text-[13px] font-semibold tracking-[0.1em]">CROWDCOUNT</span>
          </div>
          <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
          <p className="mt-1 text-sm text-dim">{subtitle}</p>
          <div className="mt-7">{children}</div>
        </div>
      </main>
    </div>
  );
}

export function LoginPage() {
  const { data: user } = useCurrentUser();
  const { login } = useAuthActions();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  if (user) return <Navigate to={from} replace />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate({ email, password }, { onSuccess: () => navigate(from, { replace: true }) });
  };

  return (
    <AuthShell title="Sign in" subtitle="Access your camera wall and analytics.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email" htmlFor="email">
          <input id="email" className="field" type="email" autoComplete="email" required autoFocus
            value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label="Password" htmlFor="password">
          <input id="password" className="field" type="password" autoComplete="current-password" required
            value={password} onChange={(e) => setPassword(e.target.value)} />
        </Field>
        <ErrorNote error={login.error} />
        <button className="btn-primary h-9 w-full" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
      <p className="mt-6 text-sm text-dim">
        New here? <Link to="/signup" className="text-signal hover:underline">Create an account</Link>
      </p>
    </AuthShell>
  );
}

export function SignupPage() {
  const { data: user } = useCurrentUser();
  const { signup } = useAuthActions();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", email: "", password: "" });

  if (user) return <Navigate to="/" replace />;

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    signup.mutate(form, { onSuccess: () => navigate("/cameras/new", { replace: true }) });
  };

  return (
    <AuthShell title="Create account" subtitle="Then connect your first camera.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Name" htmlFor="name">
          <input id="name" className="field" autoComplete="name" required autoFocus value={form.name} onChange={set("name")} />
        </Field>
        <Field label="Email" htmlFor="email">
          <input id="email" className="field" type="email" autoComplete="email" required value={form.email} onChange={set("email")} />
        </Field>
        <Field label="Password" htmlFor="password" hint="At least 8 characters.">
          <input id="password" className="field" type="password" autoComplete="new-password" required minLength={8}
            value={form.password} onChange={set("password")} />
        </Field>
        <ErrorNote error={signup.error} />
        <button className="btn-primary h-9 w-full" disabled={signup.isPending}>
          {signup.isPending ? "Creating account…" : "Create account"}
        </button>
      </form>
      <p className="mt-6 text-sm text-dim">
        Already registered? <Link to="/login" className="text-signal hover:underline">Sign in</Link>
      </p>
    </AuthShell>
  );
}
