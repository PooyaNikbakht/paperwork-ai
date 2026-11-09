"use client";

import { IconChevronDown } from "@/components/icons";
import { CheckIcon, cx } from "@/components/ui";
import { plural } from "@/lib/format";
import type { Check, Extraction } from "@/lib/types";
import { pathLabel } from "./selection";

export function ChecksPanel({
  checks,
  extraction,
  onSelect,
  stale,
}: {
  checks: Check[];
  extraction: Extraction | null;
  onSelect: (path: string) => void;
  stale: boolean;
}) {
  const problems = checks.filter((c) => c.status === "fail" || c.status === "warn");
  problems.sort((a, b) => (a.status === b.status ? 0 : a.status === "fail" ? -1 : 1));
  const passed = checks.filter((c) => c.status === "pass");
  const skipped = checks.filter((c) => c.status === "skip");
  const fails = problems.filter((c) => c.status === "fail").length;
  const warns = problems.length - fails;

  return (
    <section aria-labelledby="checks-heading" className="rounded-lg border border-line">
      <div
        className={cx(
          "flex items-center justify-between gap-3 rounded-t-lg border-b px-4 py-3",
          fails ? "border-danger/30 bg-danger-soft" : warns ? "border-amber/30 bg-amber-soft" : "border-accent/30 bg-accent-soft",
        )}
      >
        <h2 id="checks-heading" className="flex items-center gap-2 font-semibold">
          <CheckIcon status={fails ? "fail" : warns ? "warn" : "pass"} />
          {fails
            ? `${plural(fails, "check")} failed`
            : warns
              ? `${plural(warns, "thing")} to look at`
              : "All checks passed"}
        </h2>
        <span className="text-xs text-muted">
          {passed.length} of {passed.length + problems.length} passed
        </span>
      </div>
      {stale && (
        <p className="border-b border-line px-4 py-2 text-xs text-amber">
          You have unsaved edits. Save to re-run the checks.
        </p>
      )}
      {problems.length > 0 && (
        <ul className="divide-y divide-line">
          {problems.map((c) => (
            <li key={c.id} className="px-4 py-3">
              <p className="flex items-center gap-2 text-sm font-medium">
                <CheckIcon status={c.status} size={16} />
                {c.label}
              </p>
              <p className="mt-1 pl-6 text-sm leading-relaxed text-ink/90">{c.message}</p>
              {c.fields.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5 pl-6">
                  {[...new Set(c.fields)].slice(0, 6).map((p) => (
                    <button
                      key={p}
                      onClick={() => onSelect(p)}
                      className="rounded-md border border-line px-2 py-0.5 text-xs text-muted hover:border-line-strong hover:text-ink"
                    >
                      {pathLabel(p, extraction)}
                    </button>
                  ))}
                  {c.fields.length > 6 && <span className="px-1 text-xs text-muted">+{c.fields.length - 6}</span>}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      <details className="group border-t border-line first:border-t-0">
        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-2.5 text-sm text-muted hover:text-ink">
          <span>
            {passed.length} passed{skipped.length ? `, ${skipped.length} not applicable` : ""}
          </span>
          <IconChevronDown size={16} className="transition-transform group-open:rotate-180" />
        </summary>
        <ul className="space-y-2.5 px-4 pb-4">
          {[...passed, ...skipped].map((c) => (
            <li key={c.id} className="flex gap-2 text-sm">
              <CheckIcon status={c.status} size={16} />
              <span>
                <span className="font-medium">{c.label}.</span> <span className="text-muted">{c.message}</span>
              </span>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
