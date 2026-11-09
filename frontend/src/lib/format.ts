import type { DocStatus, DocType } from "@/lib/types";

export function money(value: number | null | undefined, currency?: string | null): string {
  if (value === null || value === undefined) return "";
  const n = value.toLocaleString("en-CA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency ? `${n} ${currency}` : n;
}

export function dateLabel(iso: string | null | undefined): string {
  if (!iso) return "";
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return d.toLocaleDateString("en-CA", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
}

export function percent(x: number): string {
  return `${Math.round(x * 100)}%`;
}

export function fileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export const STATUS_LABEL: Record<DocStatus, string> = {
  queued: "Queued",
  extracting: "Reading",
  needs_review: "Needs review",
  ready: "Checks passed",
  approved: "Approved",
  failed: "Failed",
};

export const TYPE_LABEL: Record<DocType, string> = {
  invoice: "Invoice",
  receipt: "Receipt",
  custom: "Form",
};

export function timeAgo(epochSeconds: number): string {
  const s = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(epochSeconds * 1000).toLocaleDateString("en-CA");
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`;
}
