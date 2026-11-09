import type { Check, Extraction, Source } from "@/lib/types";

/** What the preview should highlight: one field's source. */
export interface Selection {
  path: string;
  label: string;
  source: Source | null;
}

export type Flag = "fail" | "warn";

/** Field paths named by failing or warning checks, with the worst status for each. */
export function flaggedPaths(checks: Check[]): Map<string, Flag> {
  const out = new Map<string, Flag>();
  for (const c of checks) {
    if (c.status !== "fail" && c.status !== "warn") continue;
    for (const p of c.fields) {
      if (out.get(p) !== "fail") out.set(p, c.status);
    }
  }
  return out;
}

/** The flag for a whole line or tax row (any of its cells). */
export function rowFlag(flags: Map<string, Flag>, prefix: string): Flag | undefined {
  let worst: Flag | undefined;
  for (const [p, f] of flags) {
    if (p === prefix || p.startsWith(`${prefix}.`)) {
      if (f === "fail") return "fail";
      worst = "warn";
    }
  }
  return worst;
}

export function pathLabel(path: string, ex: Extraction | null): string {
  const m = /^(line_items|taxes)\.(\d+)(?:\.(\w+))?$/.exec(path);
  if (m) {
    const i = Number(m[2]);
    if (m[1] === "line_items") return `Line ${i + 1}${m[3] && m[3] !== "description" ? ` ${m[3].replace("_", " ")}` : ""}`;
    const kind = ex?.taxes[i]?.kind ?? "Tax";
    return m[3] === "rate" ? `${kind} rate` : kind;
  }
  return ex?.fields.find((f) => f.key === path)?.label ?? path;
}

export function sourceFor(path: string, ex: Extraction | null): Source | null {
  if (!ex) return null;
  const m = /^(line_items|taxes)\.(\d+)/.exec(path);
  if (m) {
    const row = m[1] === "line_items" ? ex.line_items[Number(m[2])] : ex.taxes[Number(m[2])];
    return row?.source ?? null;
  }
  return ex.fields.find((f) => f.key === path)?.source ?? null;
}

export function domId(path: string): string {
  return `field-${path.replace(/\./g, "-")}`;
}
