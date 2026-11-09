import type { ButtonHTMLAttributes, ReactNode } from "react";
import { IconCheckCircle, IconMinus, IconWarn, IconXCircle } from "@/components/icons";
import { STATUS_LABEL, percent } from "@/lib/format";
import type { CheckStatus, DocStatus } from "@/lib/types";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-accent-ink border-accent hover:opacity-90",
  secondary: "bg-background text-ink border-line-strong hover:bg-surface",
  ghost: "bg-transparent text-ink border-transparent hover:bg-surface",
  danger: "bg-background text-danger border-line-strong hover:bg-danger-soft",
};

export function Button({
  variant = "secondary",
  size = "md",
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <button
      type="button"
      className={cx(
        "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg border font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-sm",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    />
  );
}

const STATUS_STYLE: Record<DocStatus, string> = {
  queued: "bg-surface text-muted border-line",
  extracting: "bg-surface text-ink border-line",
  needs_review: "bg-amber-soft text-amber border-amber/40",
  ready: "bg-accent-soft text-accent border-accent/40",
  approved: "bg-accent text-accent-ink border-accent",
  failed: "bg-danger-soft text-danger border-danger/40",
};

export function StatusPill({ status }: { status: DocStatus }) {
  return (
    <span
      className={cx(
        "inline-flex h-6 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 text-xs font-medium",
        STATUS_STYLE[status],
      )}
    >
      {(status === "extracting" || status === "queued") && (
        <span
          className={cx(
            "h-1.5 w-1.5 rounded-full bg-current",
            status === "extracting" && "animate-pulse-soft",
          )}
        />
      )}
      {status === "approved" && <IconCheckCircle size={13} />}
      {STATUS_LABEL[status]}
    </span>
  );
}

export function confidenceLevel(c: number): "high" | "medium" | "low" {
  if (c >= 0.9) return "high";
  if (c >= 0.7) return "medium";
  return "low";
}

export function ConfidenceBadge({ value, edited }: { value: number; edited?: boolean }) {
  if (edited) {
    return (
      <span className="inline-flex h-5 items-center rounded border border-line px-1.5 font-mono text-[11px] text-muted">
        edited
      </span>
    );
  }
  const level = confidenceLevel(value);
  const style = {
    high: "border-line text-muted",
    medium: "border-amber/40 text-amber",
    low: "border-danger/40 bg-danger-soft text-danger",
  }[level];
  return (
    <span
      title={`AI confidence ${percent(value)}`}
      className={cx("inline-flex h-5 items-center rounded border px-1.5 font-mono text-[11px] tabular", style)}
    >
      <span className="sr-only">Confidence </span>
      {percent(value)}
    </span>
  );
}

export function CheckIcon({ status, size = 18 }: { status: CheckStatus; size?: number }) {
  if (status === "pass") return <IconCheckCircle size={size} className="shrink-0 text-accent" />;
  if (status === "fail") return <IconXCircle size={size} className="shrink-0 text-danger" />;
  if (status === "warn") return <IconWarn size={size} className="shrink-0 text-amber" />;
  return <IconMinus size={size} className="shrink-0 text-muted" />;
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("rounded-lg border border-line bg-background", className)}>{children}</div>;
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" className="animate-spin" aria-hidden="true">
      <circle cx="10" cy="10" r="7.5" fill="none" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
      <path d="M17.5 10a7.5 7.5 0 0 0-7.5-7.5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function DemoBadge({ title }: { title?: string }) {
  return (
    <span
      title={title ?? "Demo mode: extraction is simulated, no AI provider is called."}
      className="inline-flex h-6 items-center gap-1.5 rounded-full border border-amber/40 bg-amber-soft px-2.5 font-mono text-[11px] font-medium uppercase tracking-wide text-amber"
    >
      Demo mode
    </span>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="rounded-lg border border-danger/40 bg-danger-soft px-4 py-3 text-sm text-danger">
      {children}
    </div>
  );
}
