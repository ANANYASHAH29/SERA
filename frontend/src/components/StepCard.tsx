import type { ReactNode } from "react";

export type Theme = "dark" | "light";

export function StepCard({
  step,
  title,
  done,
  disabled,
  children,
  theme = "dark",
}: {
  step: number;
  title: string;
  done?: boolean;
  disabled?: boolean;
  children: ReactNode;
  theme?: Theme;
}) {
  const light = theme === "light";
  const cardClass = light
    ? disabled
      ? "border-slate-200 bg-slate-50 opacity-60"
      : done
        ? "border-emerald-300 bg-emerald-50"
        : "border-slate-200 bg-white shadow-sm"
    : disabled
      ? "border-slate-800 bg-slate-900/40 opacity-50"
      : done
        ? "border-emerald-700/60 bg-emerald-950/20"
        : "border-slate-700 bg-slate-900/60";

  const badgeClass = light
    ? done
      ? "bg-emerald-600 text-white"
      : "bg-slate-200 text-slate-700"
    : done
      ? "bg-emerald-600 text-white"
      : "bg-slate-700 text-slate-200";

  const titleClass = light ? "text-slate-800" : "text-slate-100";

  return (
    <div className={`rounded-lg border p-4 ${cardClass}`}>
      <div className="mb-3 flex items-center gap-2">
        <span
          className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${badgeClass}`}
        >
          {done ? "✓" : step}
        </span>
        <h3 className={`text-sm font-semibold tracking-wide ${titleClass}`}>{title}</h3>
      </div>
      <div className={disabled ? "pointer-events-none" : ""}>{children}</div>
    </div>
  );
}

export function Button({
  children,
  onClick,
  disabled,
  loading,
  variant = "primary",
  theme = "dark",
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  variant?: "primary" | "secondary";
  theme?: Theme;
}) {
  const light = theme === "light";
  const base =
    "rounded-md px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40";
  const styles = light
    ? variant === "primary"
      ? "bg-indigo-600 text-white hover:bg-indigo-500"
      : "bg-slate-200 text-slate-700 hover:bg-slate-300"
    : variant === "primary"
      ? "bg-indigo-600 text-white hover:bg-indigo-500"
      : "bg-slate-700 text-slate-100 hover:bg-slate-600";
  return (
    <button className={`${base} ${styles}`} onClick={onClick} disabled={disabled || loading}>
      {loading ? "Running…" : children}
    </button>
  );
}

export function ErrorBanner({ message, theme = "dark" }: { message: string | null; theme?: Theme }) {
  if (!message) return null;
  const light = theme === "light";
  const cls = light
    ? "border-red-300 bg-red-50 text-red-700"
    : "border-red-800 bg-red-950/40 text-red-300";
  return <div className={`mt-2 rounded-md border px-3 py-2 text-xs ${cls}`}>{message}</div>;
}
