"use client";

import { useEffect, useId, useRef, useState } from "react";
import { IconChevronDown, IconDownload } from "@/components/icons";
import { Button, Spinner, cx } from "@/components/ui";
import { ApiError, downloadExport } from "@/lib/api";
import type { ExportFormat } from "@/lib/types";

const FORMATS: { id: ExportFormat; label: string; hint: string }[] = [
  { id: "xlsx", label: "Excel workbook", hint: "Documents, line items, taxes and checks as sheets" },
  { id: "csv-categories", label: "CSV, totals by category", hint: "One row per suggested category, receipts only" },
  { id: "csv", label: "CSV, one row per document", hint: "Totals and taxes per document" },
  { id: "csv-lines", label: "CSV, one row per line item", hint: "For costing and inventory" },
  { id: "sheets", label: "Google Sheets CSV", hint: "UTF-8, ISO dates, ready for File > Import" },
  { id: "json", label: "JSON", hint: "Everything, including sources and checks" },
];

export function ExportMenu({
  batchId,
  approved,
  total,
  receipts = false,
}: {
  batchId: string;
  approved: number;
  total: number;
  receipts?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<ExportFormat>("xlsx");
  const [scope, setScope] = useState<"approved" | "all">("approved");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function go() {
    setBusy(true);
    setError(null);
    try {
      await downloadExport(batchId, format, scope);
      setOpen(false);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(false);
    }
  }

  const count = scope === "approved" ? approved : total;

  return (
    <div ref={ref} className="relative">
      <Button onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls={panelId}>
        <IconDownload size={16} /> Export <IconChevronDown size={14} />
      </Button>
      {open && (
        <div
          id={panelId}
          className="absolute right-0 z-30 mt-2 w-[min(22rem,calc(100vw-2rem))] rounded-lg border border-line-strong bg-background p-3"
        >
          <fieldset>
            <legend className="px-1 pb-2 text-xs font-medium uppercase tracking-wide text-muted">Format</legend>
            <div className="space-y-1">
              {FORMATS.filter((f) => receipts || f.id !== "csv-categories").map((f) => (
                <label
                  key={f.id}
                  className={cx(
                    "flex cursor-pointer gap-3 rounded-md px-2 py-2 text-sm has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent",
                    format === f.id ? "bg-accent-soft" : "hover:bg-surface",
                  )}
                >
                  <input
                    type="radio"
                    name="export-format"
                    checked={format === f.id}
                    onChange={() => setFormat(f.id)}
                    className="mt-1 accent-[var(--accent)]"
                  />
                  <span>
                    <span className="block font-medium">{f.label}</span>
                    <span className="block text-xs text-muted">
                      {receipts && f.id === "xlsx" ? "Documents, line items, taxes, checks and a By category sheet" : f.hint}
                    </span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="mt-3 border-t border-line pt-3">
            <legend className="sr-only">Which documents</legend>
            <div className="grid grid-cols-2 gap-1 rounded-md border border-line p-0.5 text-sm">
              {(["approved", "all"] as const).map((s) => (
                <label
                  key={s}
                  className={cx(
                    "cursor-pointer rounded px-2 py-1.5 text-center has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent",
                    scope === s ? "bg-surface-2 font-medium" : "text-muted",
                  )}
                >
                  <input type="radio" name="export-scope" className="sr-only" checked={scope === s} onChange={() => setScope(s)} />
                  {s === "approved" ? `Approved (${approved})` : `All read (${total})`}
                </label>
              ))}
            </div>
          </fieldset>
          {error && <p className="mt-3 text-sm text-danger">{error}</p>}
          <Button variant="primary" className="mt-3 w-full" onClick={go} disabled={busy || count === 0}>
            {busy ? <Spinner /> : <IconDownload size={16} />}
            Download {count} {count === 1 ? "document" : "documents"}
          </Button>
          {scope === "approved" && approved === 0 && (
            <p className="mt-2 text-xs text-muted">Approve documents first, or switch to all.</p>
          )}
        </div>
      )}
    </div>
  );
}
