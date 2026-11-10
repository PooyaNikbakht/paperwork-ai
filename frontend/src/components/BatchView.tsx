"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useConfig } from "@/components/ConfigProvider";
import { ExportMenu } from "@/components/ExportMenu";
import { IconCheck, IconChevronRight, IconFile, IconImage, IconPlus, IconTrash } from "@/components/icons";
import { Button, CheckIcon, DemoBadge, ErrorNote, Spinner, StatusPill, cx } from "@/components/ui";
import { api, ApiError, uploadFiles } from "@/lib/api";
import { DISCLAIMER } from "@/lib/categories";
import { TYPE_LABEL, dateLabel, money, plural, timeAgo } from "@/lib/format";
import type { CategoryRow, DocSummary } from "@/lib/types";
import { useBatch } from "@/lib/useBatch";

type Filter = "all" | "review" | "ready" | "approved" | "other";

const FILTERS: { id: Filter; label: string; match: (d: DocSummary) => boolean }[] = [
  { id: "all", label: "All", match: () => true },
  { id: "review", label: "Needs review", match: (d) => d.status === "needs_review" },
  { id: "ready", label: "Checks passed", match: (d) => d.status === "ready" },
  { id: "approved", label: "Approved", match: (d) => d.status === "approved" },
  {
    id: "other",
    label: "In progress or failed",
    match: (d) => d.status === "queued" || d.status === "extracting" || d.status === "failed",
  },
];

function isBusy(d: DocSummary) {
  return d.status === "queued" || d.status === "extracting";
}

function totalsByCurrency(docs: DocSummary[]): { currency: string; total: number; count: number }[] {
  const map = new Map<string, { total: number; count: number }>();
  for (const d of docs) {
    if (d.total === null || d.doc_type === "custom") continue;
    const key = d.currency ?? "?";
    const cur = map.get(key) ?? { total: 0, count: 0 };
    map.set(key, { total: cur.total + d.total, count: cur.count + 1 });
  }
  return [...map.entries()]
    .map(([currency, v]) => ({ currency, ...v }))
    .sort((a, b) => b.total - a.total);
}

function IssueSummary({ d }: { d: DocSummary }) {
  if (d.status === "failed") return <span className="text-sm text-danger">{d.error ?? "Couldn't read"}</span>;
  if (isBusy(d)) return <span className="text-sm text-muted">{d.status === "queued" ? "Waiting" : "Reading..."}</span>;
  if (d.issues.fail) {
    return (
      <span className="flex min-w-0 items-center gap-1.5 text-sm">
        <CheckIcon status="fail" size={16} />
        <span className="truncate">
          <span className="font-medium text-danger">{d.top_issue?.label}</span>
          {d.issues.fail + d.issues.warn > 1 && (
            <span className="text-muted"> +{d.issues.fail + d.issues.warn - 1}</span>
          )}
        </span>
      </span>
    );
  }
  if (d.issues.warn) {
    return (
      <span className="flex min-w-0 items-center gap-1.5 text-sm">
        <CheckIcon status="warn" size={16} />
        <span className="truncate">
          <span className="font-medium text-amber">{d.top_issue?.label}</span>
          {d.issues.warn > 1 && <span className="text-muted"> +{d.issues.warn - 1}</span>}
        </span>
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 text-sm text-muted">
      <CheckIcon status="pass" size={16} /> All passed
    </span>
  );
}

function CategoryChip({ category }: { category: string | null }) {
  if (!category) return <span className="text-muted">-</span>;
  return (
    <span className="inline-flex max-w-full items-center truncate rounded-md border border-line bg-surface px-2 py-0.5 text-xs font-medium">
      {category}
    </span>
  );
}

/** Spend per suggested category, as the same numbers the Excel summary sheet carries. */
function CategorySummary({ rows }: { rows: CategoryRow[] }) {
  const total = rows.find((r) => r.category === "All categories");
  const items = rows.filter((r) => r !== total);
  const max = Math.max(...items.map((r) => r.total), 0.01);
  return (
    <section aria-labelledby="by-category" className="mt-6 rounded-lg border border-line">
      <div className="flex flex-col gap-1 border-b border-line px-4 py-3 sm:flex-row sm:items-baseline sm:justify-between">
        <h2 id="by-category" className="font-semibold">
          By suggested category
        </h2>
        <p className="text-xs text-muted">{DISCLAIMER}</p>
      </div>
      <ul className="divide-y divide-line">
        {items.map((r) => (
          <li key={r.category} className="px-4 py-2.5">
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="min-w-0 font-medium">{r.category}</span>
              <span className="shrink-0 font-medium tabular">{money(r.total)}</span>
            </div>
            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
              <div className="h-full rounded-full bg-accent" style={{ width: `${(r.total / max) * 100}%` }} />
            </div>
            <p className="mt-1 text-xs text-muted tabular">
              {plural(r.receipts, "receipt")} · {plural(r.line_items, "line")} · {money(r.amount_before_tax)} before tax
              + {money(r.tax)} tax
            </p>
          </li>
        ))}
      </ul>
      {total && (
        <p className="flex items-baseline justify-between border-t border-line px-4 py-2.5 text-sm font-semibold">
          <span>All categories</span>
          <span className="tabular">{money(total.total)}</span>
        </p>
      )}
    </section>
  );
}

function DocIcon({ d }: { d: DocSummary }) {
  const Icon = d.media_type === "application/pdf" ? IconFile : IconImage;
  return (
    <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-line bg-surface text-muted">
      <Icon size={17} />
    </span>
  );
}

export function BatchView({ id }: { id: string }) {
  const router = useRouter();
  const config = useConfig();
  const { batch, setBatch, error, gone } = useBatch(id);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<"approve" | "upload" | "delete" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const addRef = useRef<HTMLInputElement>(null);

  const docs = useMemo(() => batch?.documents ?? [], [batch]);
  const receipts = batch?.mode === "receipt" || docs.some((d) => d.category !== null);
  // The sample note follows the batch mode: the invoice sample also holds two receipts with categories.
  const receiptSample = batch?.mode === "receipt";
  const [categoryRows, setCategoryRows] = useState<CategoryRow[]>([]);
  const signature = docs.map((d) => `${d.id}:${d.updated_at}`).join("|");
  useEffect(() => {
    if (!receipts || !signature) return;
    let cancelled = false;
    api
      .categories(id)
      .then((r) => !cancelled && setCategoryRows(r.rows))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [id, receipts, signature]);
  const filtered = useMemo(() => {
    const f = FILTERS.find((x) => x.id === filter)!;
    const q = query.trim().toLowerCase();
    return docs.filter(
      (d) =>
        f.match(d) &&
        (!q || [d.filename, d.party, d.number, d.category, d.job].some((v) => v && String(v).toLowerCase().includes(q))),
    );
  }, [docs, filter, query]);

  const counts = useMemo(() => {
    const c = { review: 0, ready: 0, approved: 0, busy: 0, failed: 0 };
    for (const d of filtered) {
      if (d.status === "needs_review") c.review++;
      else if (d.status === "ready") c.ready++;
      else if (d.status === "approved") c.approved++;
      else if (d.status === "failed") c.failed++;
      else c.busy++;
    }
    return c;
  }, [filtered]);

  const totals = useMemo(() => totalsByCurrency(filtered), [filtered]);
  const read = docs.filter((d) => !isBusy(d)).length;
  const readyAll = docs.filter((d) => d.status === "ready").length;
  const approvedAll = docs.filter((d) => d.status === "approved").length;
  const readAll = docs.filter((d) => d.status !== "failed" && !isBusy(d)).length;
  const demo = docs.some((d) => d.demo) || config?.demo_mode;

  async function approveReady() {
    setBusy("approve");
    setActionError(null);
    try {
      setBatch(await api.approveReady(id));
    } catch (e) {
      setActionError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function addFiles(files: FileList) {
    setBusy("upload");
    setActionError(null);
    try {
      setBatch(await uploadFiles(id, Array.from(files), () => {}));
    } catch (e) {
      setActionError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function deleteBatch() {
    if (!window.confirm("Delete this batch and all its files? This can't be undone.")) return;
    setBusy("delete");
    try {
      await api.deleteBatch(id);
      router.push("/");
    } catch (e) {
      setActionError((e as ApiError).message);
      setBusy(null);
    }
  }

  if (gone) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-16 text-center sm:px-6">
        <h1 className="text-2xl font-semibold">This batch is gone</h1>
        <p className="mt-3 text-muted">It may have expired. Demo batches are deleted after an hour.</p>
        <Link href="/" className="mt-6 inline-block font-medium text-accent hover:underline">
          Start a new batch
        </Link>
      </div>
    );
  }

  if (!batch) {
    return (
      <div className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-6">
        {error ? (
          <ErrorNote>{error.message}</ErrorNote>
        ) : (
          <div className="flex items-center gap-3 text-muted" role="status">
            <Spinner /> Loading batch...
          </div>
        )}
      </div>
    );
  }

  const progress = docs.length ? read / docs.length : 0;

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 sm:py-10">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <nav aria-label="Breadcrumb" className="text-sm text-muted">
            <Link href="/" className="hover:text-ink">
              Home
            </Link>{" "}
            / Batch
          </nav>
          <h1 className="mt-2 flex flex-wrap items-center gap-3 text-2xl font-semibold tracking-tight sm:text-3xl">
            {batch.is_sample ? "Sample batch" : "Your batch"}
            {demo && <DemoBadge />}
          </h1>
          <p className="mt-1.5 text-sm text-muted">
            {plural(docs.length, "document")} · started {timeAgo(batch.created_at)}
            {batch.mode !== "auto" && ` · ${batch.mode === "custom" ? "custom fields" : `${batch.mode}s`}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" onClick={approveReady} disabled={!readyAll || busy !== null}>
            {busy === "approve" ? <Spinner /> : <IconCheck size={16} />}
            Approve {readyAll || ""} that passed
          </Button>
          <ExportMenu batchId={id} approved={approvedAll} total={readAll} receipts={receipts} />
          <Button onClick={() => addRef.current?.click()} disabled={busy !== null || batch.is_sample}>
            {busy === "upload" ? <Spinner /> : <IconPlus size={16} />}
            Add files
          </Button>
          <input
            ref={addRef}
            type="file"
            multiple
            accept=".pdf,.png,.jpg,.jpeg"
            className="sr-only"
            tabIndex={-1}
            aria-label="Add files to this batch"
            onChange={(e) => {
              if (e.target.files?.length) void addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <Button variant="ghost" onClick={deleteBatch} disabled={busy !== null} aria-label="Delete batch" title="Delete batch">
            <IconTrash size={16} />
          </Button>
        </div>
      </div>

      {batch.is_sample && receiptSample && (
        <div className="mt-6 rounded-lg border border-line bg-surface px-4 py-3 text-sm leading-relaxed">
          <p>
            <span className="font-medium">Three job receipts, photographed on a phone.</span>{" "}
            <span className="text-muted">
              Lumber and hardware, a fuel stop and an equipment rental. One slip has a printed tax amount that
              doesn&apos;t add up, so the math check flags it. Open any receipt to change its suggested category.
            </span>
          </p>
        </div>
      )}
      {batch.is_sample && !receiptSample && (
        <div className="mt-6 rounded-lg border border-line bg-surface px-4 py-3 text-sm leading-relaxed">
          <p>
            <span className="font-medium">A month of paperwork for a fictional bakery.</span>{" "}
            <span className="text-muted">
              Five of these twelve documents have a problem: two supplier math errors, a duplicate, a currency
              mix-up, and a misread on a crooked scan. Open one to see what the checks found and where.
            </span>
          </p>
        </div>
      )}

      {actionError && (
        <div className="mt-4">
          <ErrorNote>{actionError}</ErrorNote>
        </div>
      )}

      <div className="mt-6" aria-live="polite">
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted">
            {read < docs.length ? (
              <span className="inline-flex items-center gap-2">
                <Spinner size={14} /> Reading documents: {read} of {docs.length} done
              </span>
            ) : (
              `All ${plural(docs.length, "document")} read`
            )}
          </span>
          <span className="font-mono text-xs text-muted tabular">{Math.round(progress * 100)}%</span>
        </div>
        <div
          className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-2"
          role="progressbar"
          aria-label="Documents read"
          aria-valuemin={0}
          aria-valuemax={docs.length}
          aria-valuenow={read}
        >
          <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${progress * 100}%` }} />
        </div>
      </div>

      <dl className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
        {[
          { label: filter === "all" && !query ? "Documents" : "Shown", value: filtered.length, tone: "" },
          { label: "Needs review", value: counts.review, tone: counts.review ? "text-amber" : "" },
          { label: "Checks passed", value: counts.ready, tone: counts.ready ? "text-accent" : "" },
          { label: "Approved", value: counts.approved, tone: "" },
        ].map((k) => (
          <div key={k.label} className="rounded-lg border border-line px-4 py-3">
            <dt className="text-xs text-muted">{k.label}</dt>
            <dd className={cx("mt-1 text-2xl font-semibold tabular", k.tone)}>{k.value}</dd>
          </div>
        ))}
        <div className="col-span-2 rounded-lg border border-line px-4 py-3 lg:col-span-1">
          <dt className="text-xs text-muted">Total value</dt>
          <dd className="mt-1 space-y-0.5">
            {totals.length === 0 && <span className="text-2xl font-semibold text-muted">-</span>}
            {totals.slice(0, 2).map((t) => (
              <span key={t.currency} className="block text-lg font-semibold leading-tight tabular">
                {money(t.total)} <span className="text-xs font-medium text-muted">{t.currency}</span>
              </span>
            ))}
          </dd>
        </div>
      </dl>

      {receipts && categoryRows.length > 0 && <CategorySummary rows={categoryRows} />}

      <div className="mt-8 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div role="tablist" aria-label="Filter documents" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
          {FILTERS.map((f) => {
            const n = docs.filter(f.match).length;
            return (
              <button
                key={f.id}
                role="tab"
                aria-selected={filter === f.id}
                onClick={() => setFilter(f.id)}
                className={cx(
                  "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-sm",
                  filter === f.id ? "border-ink bg-ink text-background" : "border-line text-muted hover:text-ink",
                )}
              >
                {f.label}
                <span className="font-mono text-xs opacity-80 tabular">{n}</span>
              </button>
            );
          })}
        </div>
        <label className="relative md:w-64">
          <span className="sr-only">Search documents</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={receipts ? "Search vendor, category, job or file" : "Search vendor, number or file"}
            className="h-9 w-full rounded-lg border border-line bg-background px-3 text-sm"
          />
        </label>
      </div>

      {filtered.length === 0 ? (
        <div className="mt-4 rounded-lg border border-dashed border-line-strong px-4 py-12 text-center text-sm text-muted">
          {docs.length === 0 ? "No documents yet. Add some files to get started." : "Nothing matches this filter."}
        </div>
      ) : (
        <>
          {/* Desktop table */}
          <div className="mt-4 hidden overflow-hidden rounded-lg border border-line md:block">
            <table className="w-full table-fixed text-left text-sm">
              <thead className="bg-surface text-xs text-muted">
                <tr>
                  <th scope="col" className={cx("px-4 py-2.5 font-medium", receipts ? "w-[24%]" : "w-[30%]")}>Document</th>
                  <th scope="col" className={cx("px-3 py-2.5 font-medium", receipts ? "w-[15%]" : "w-[19%]")}>From</th>
                  <th scope="col" className={cx("px-3 py-2.5 font-medium", receipts ? "w-[10%]" : "w-[11%]")}>Date</th>
                  {receipts && <th scope="col" className="w-[15%] px-3 py-2.5 font-medium">Suggested category</th>}
                  <th scope="col" className={cx("px-3 py-2.5 text-right font-medium", receipts ? "w-[10%]" : "w-[12%]")}>Total</th>
                  <th scope="col" className={cx("px-3 py-2.5 font-medium", receipts ? "w-[14%]" : "w-[16%]")}>Checks</th>
                  <th scope="col" className={cx("px-3 py-2.5 font-medium", receipts ? "w-[12%]" : "w-[12%]")}>Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {filtered.map((d) => {
                  const href = `/batches/${id}/documents/${d.id}`;
                  return (
                    <tr
                      key={d.id}
                      className="cursor-pointer hover:bg-surface"
                      onClick={() => !isBusy(d) && router.push(href)}
                    >
                      <td className="px-4 py-3">
                        <div className="flex min-w-0 items-center gap-3">
                          <DocIcon d={d} />
                          <div className="min-w-0">
                            {isBusy(d) ? (
                              <span className="block truncate font-medium">{d.filename}</span>
                            ) : (
                              <Link
                                href={href}
                                className="block truncate font-medium hover:underline"
                                onClick={(e) => e.stopPropagation()}
                              >
                                {d.filename}
                              </Link>
                            )}
                            <span className="text-xs text-muted">
                              {d.doc_type ? TYPE_LABEL[d.doc_type] : "Detecting type"}
                              {d.number && <span className="font-mono"> · {d.number}</span>}
                              {d.job && <span> · Job: {d.job}</span>}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className="truncate px-3 py-3">{d.party ?? <span className="text-muted">-</span>}</td>
                      <td className="px-3 py-3 text-muted tabular">{dateLabel(d.date)}</td>
                      {receipts && (
                        <td className="px-3 py-3">
                          <CategoryChip category={d.category} />
                        </td>
                      )}
                      <td className="px-3 py-3 text-right font-medium tabular">
                        {d.total !== null ? money(d.total) : <span className="text-muted">-</span>}
                        {d.total !== null && d.currency && (
                          <span className="ml-1 text-xs font-normal text-muted">{d.currency}</span>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        <IssueSummary d={d} />
                      </td>
                      <td className="px-3 py-3">
                        <StatusPill status={d.status} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <ul className="mt-4 space-y-2 md:hidden">
            {filtered.map((d) => {
              const inner = (
                <>
                  <div className="flex items-start gap-3">
                    <DocIcon d={d} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{d.party ?? d.filename}</p>
                      <p className="truncate text-xs text-muted">
                        {d.doc_type ? TYPE_LABEL[d.doc_type] : "Detecting"}
                        {d.date && ` · ${dateLabel(d.date)}`}
                        {d.party && ` · ${d.filename}`}
                      </p>
                    </div>
                    <div className="text-right">
                      {d.total !== null && (
                        <p className="font-medium tabular">
                          {money(d.total)} <span className="text-xs font-normal text-muted">{d.currency}</span>
                        </p>
                      )}
                    </div>
                  </div>
                  {receipts && d.category && (
                    <p className="mt-2.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                      <CategoryChip category={d.category} />
                      {d.job && <span>Job: {d.job}</span>}
                    </p>
                  )}
                  <div className="mt-3 flex items-center justify-between gap-3">
                    <IssueSummary d={d} />
                    <span className="flex items-center gap-1">
                      <StatusPill status={d.status} />
                      {!isBusy(d) && <IconChevronRight size={16} className="text-muted" />}
                    </span>
                  </div>
                </>
              );
              return (
                <li key={d.id}>
                  {isBusy(d) ? (
                    <div className="rounded-lg border border-line p-3">{inner}</div>
                  ) : (
                    <Link href={`/batches/${id}/documents/${d.id}`} className="block rounded-lg border border-line p-3 hover:bg-surface">
                      {inner}
                    </Link>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
