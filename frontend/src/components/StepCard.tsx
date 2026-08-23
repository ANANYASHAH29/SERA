import type { ReactNode } from "react";

export function StepCard({
  step,
  title,
  done,
  disabled,
  children,
}: {
  step: number;
  title: string;
  done?: boolean;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={`rounded-lg border p-4 ${
        disabled
          ? "border-slate-800 bg-slate-900/40 opacity-50"
          : done
            ? "border-emerald-700/60 bg-emerald-950/20"
            : "border-slate-700 bg-slate-900/60"
      }`}
    >
      <div className="mb-3 flex items-center gap-2">
        <span
          className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
            done ? "bg-emerald-600 text-white" : "bg-slate-700 text-slate-200"
          }`}
        >
          {done ? "✓" : step}
        </span>
        <h3 className="text-sm font-semibold tracking-wide text-slate-100">{title}</h3>
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
}: {
  children: ReactNode;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  variant?: "primary" | "secondary";
}) {
  const base =
    "rounded-md px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40";
  const styles =
    variant === "primary"
      ? "bg-indigo-600 text-white hover:bg-indigo-500"
      : "bg-slate-700 text-slate-100 hover:bg-slate-600";
  return (
    <button className={`${base} ${styles}`} onClick={onClick} disabled={disabled || loading}>
      {loading ? "Running…" : children}
    </button>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="mt-2 rounded-md border border-red-800 bg-red-950/40 px-3 py-2 text-xs text-red-300">
      {message}
    </div>
  );
}
