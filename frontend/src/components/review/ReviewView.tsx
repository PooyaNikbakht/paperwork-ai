"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { IconArrowLeft, IconCheck, IconChevronLeft, IconChevronRight, IconRefresh, IconUndo } from "@/components/icons";
import { Button, DemoBadge, ErrorNote, Spinner, StatusPill, cx } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { TYPE_LABEL, plural } from "@/lib/format";
import type { DocType, DocumentDetail, Value } from "@/lib/types";
import { useBatch } from "@/lib/useBatch";
import { ChecksPanel } from "./ChecksPanel";
import { DocumentPreview } from "./DocumentPreview";
import {
  ExpensePanel,
  FieldsPanel,
  type LineDraft,
  LineItemsEditor,
  type TaxDraft,
  TaxesEditor,
  moneyStr,
  num,
  qtyStr,
  str,
} from "./editors";
import { type Selection, domId, flaggedPaths, pathLabel, sourceFor } from "./selection";

interface Draft {
  fields: Record<string, string>;
  lines: LineDraft[];
  taxes: TaxDraft[];
  category: string;
  job: string;
}

function draftFrom(doc: DocumentDetail): Draft {
  const ex = doc.extraction;
  return {
    fields: Object.fromEntries((ex?.fields ?? []).map((f) => [f.key, str(f.value, f.type)])),
    lines: (ex?.line_items ?? []).map((l) => ({
      description: l.description,
      quantity: qtyStr(l.quantity),
      unit_price: moneyStr(l.unit_price),
      amount: moneyStr(l.amount),
      confidence: l.confidence,
      source: l.source,
      edited: l.edited,
      category: l.category ?? "",
      category_reason: l.category_reason,
    })),
    category: ex?.category ?? "",
    job: ex?.job ?? "",
    taxes: (ex?.taxes ?? []).map((t) => ({
      kind: t.kind,
      rate: t.rate === null ? "" : String(t.rate),
      amount: moneyStr(t.amount),
      confidence: t.confidence,
      source: t.source,
      edited: t.edited,
    })),
  };
}

function sameJson(a: unknown, b: unknown) {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function ReviewView({ batchId, docId }: { batchId: string; docId: string }) {
  const router = useRouter();
  const { batch } = useBatch(batchId);
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState<Draft | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [busy, setBusy] = useState<"save" | "approve" | "reopen" | "reextract" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [showPreview, setShowPreview] = useState(true);
  const dialogRef = useRef<HTMLDialogElement>(null);

  const load = useCallback(
    (d: DocumentDetail) => {
      setDoc(d);
      const fresh = draftFrom(d);
      setDraft(fresh);
      setSaved(fresh);
    },
    [setDoc],
  );

  useEffect(() => {
    let cancelled = false;
    api
      .document(docId)
      .then((d) => !cancelled && load(d))
      .catch((e: ApiError) => !cancelled && setLoadError(e.message));
    return () => {
      cancelled = true;
    };
  }, [docId, load]);

  // Pick up background changes (re-extraction finishing, duplicates re-checked) when not editing.
  const summary = batch?.documents.find((d) => d.id === docId);
  const dirty = draft !== null && saved !== null && !sameJson(draft, saved);
  useEffect(() => {
    if (!summary || !doc || dirty || busy) return;
    if (summary.updated_at > doc.updated_at + 0.001 || summary.status !== doc.status) {
      api.document(docId).then(load).catch(() => {});
    }
  }, [summary, doc, dirty, busy, docId, load]);

  const docs = batch?.documents ?? [];
  const index = docs.findIndex((d) => d.id === docId);
  const prev = index > 0 ? docs[index - 1] : null;
  const next = index >= 0 && index < docs.length - 1 ? docs[index + 1] : null;
  const nextToReview =
    docs.slice(index + 1).find((d) => d.status === "needs_review" || d.status === "ready") ??
    docs.slice(0, Math.max(0, index)).find((d) => d.status === "needs_review" || d.status === "ready");

  const go = useCallback(
    (target: { id: string } | null | undefined) => {
      if (target) router.push(`/batches/${batchId}/documents/${target.id}`);
    },
    [router, batchId],
  );

  const ex = doc?.extraction ?? null;
  const flags = useMemo(() => flaggedPaths(doc?.checks ?? []), [doc]);
  const readOnly = doc?.status === "approved" || !ex;

  const select = useCallback(
    (path: string) => {
      setSelection({ path, label: pathLabel(path, ex), source: sourceFor(path, ex) });
    },
    [ex],
  );

  const jumpTo = (path: string) => {
    select(path);
    const row = /^(line_items|taxes)\.\d+/.exec(path)?.[0] ?? path;
    const el = document.getElementById(domId(row));
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.querySelector<HTMLInputElement>("input, select")?.focus({ preventScroll: true });
  };

  function buildPatch() {
    if (!draft || !saved || !ex) return null;
    const fields: Record<string, Value> = {};
    for (const f of ex.fields) {
      if (draft.fields[f.key] !== saved.fields[f.key]) fields[f.key] = draft.fields[f.key] || null;
    }
    const patch: Parameters<typeof api.editDocument>[1] = {};
    if (Object.keys(fields).length) patch.fields = fields;
    if (ex.doc_type === "receipt") {
      if (draft.category !== saved.category) patch.category = draft.category;
      if (draft.job !== saved.job) patch.job = draft.job.trim() || null;
    }
    if (!sameJson(draft.lines, saved.lines)) {
      patch.line_items = draft.lines.map((l) => ({
        description: l.description,
        quantity: num(l.quantity),
        unit_price: num(l.unit_price),
        amount: num(l.amount),
        confidence: l.confidence,
        source: l.source,
        edited: l.edited,
        category: l.category || null,
        category_reason: l.category_reason,
      }));
    }
    if (!sameJson(draft.taxes, saved.taxes)) {
      patch.taxes = draft.taxes.map((t) => ({
        kind: t.kind,
        rate: num(t.rate),
        amount: num(t.amount),
        confidence: t.confidence,
        source: t.source,
        edited: t.edited,
      }));
    }
    return patch;
  }

  async function save(): Promise<DocumentDetail | null> {
    const patch = buildPatch();
    if (!patch || !doc) return doc;
    if (!Object.keys(patch).length) return doc;
    setBusy("save");
    setError(null);
    try {
      const updated = await api.editDocument(doc.id, patch);
      load(updated);
      const fails = updated.checks.filter((c) => c.status === "fail").length;
      setAnnounce(fails ? `Saved. ${plural(fails, "check")} still failing.` : "Saved. Checks re-run.");
      return updated;
    } catch (e) {
      setError((e as ApiError).message);
      return null;
    } finally {
      setBusy(null);
    }
  }

  async function approve(acknowledge = false) {
    let current = doc;
    if (dirty) current = await save();
    if (!current) return;
    const fails = current.checks.filter((c) => c.status === "fail").length;
    if (fails && !acknowledge) {
      setConfirmOpen(true);
      return;
    }
    setBusy("approve");
    setError(null);
    try {
      const updated = await api.approve(current.id, acknowledge);
      load(updated);
      setConfirmOpen(false);
      setAnnounce("Approved.");
      if (nextToReview) go(nextToReview);
      else router.push(`/batches/${batchId}`);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function reopen() {
    if (!doc) return;
    setBusy("reopen");
    try {
      load(await api.reopen(doc.id));
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  async function reextract(type: DocType) {
    if (!doc) return;
    setBusy("reextract");
    try {
      load(await api.reextract(doc.id, type));
      setSelection(null);
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  }

  // Native dialog for "approve anyway".
  useEffect(() => {
    const d = dialogRef.current;
    if (!d) return;
    if (confirmOpen && !d.open) d.showModal();
    if (!confirmOpen && d.open) d.close();
  }, [confirmOpen]);

  // Keyboard: Ctrl/Cmd+S saves; [ and ] move between documents when not typing.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (dirty) void save();
        return;
      }
      const target = e.target as HTMLElement;
      if (["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName)) return;
      if (e.key === "]" && next && !dirty) go(next);
      if (e.key === "[" && prev && !dirty) go(prev);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // Warn before leaving with unsaved edits.
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  if (loadError) {
    return (
      <div className="mx-auto w-full max-w-3xl px-4 py-12 sm:px-6">
        <ErrorNote>{loadError}</ErrorNote>
        <Link href={`/batches/${batchId}`} className="mt-4 inline-block text-sm font-medium text-accent hover:underline">
          Back to the batch
        </Link>
      </div>
    );
  }

  if (!doc || !draft) {
    return (
      <div className="mx-auto flex w-full max-w-7xl items-center gap-3 px-4 py-12 text-muted sm:px-6" role="status">
        <Spinner /> Loading document...
      </div>
    );
  }

  const busyReading = doc.status === "queued" || doc.status === "extracting";
  const fails = doc.checks.filter((c) => c.status === "fail").length;
  const warns = doc.checks.filter((c) => c.status === "warn").length;
  const subtotal = num(draft.fields.subtotal ?? "");
  const currency = draft.fields.currency ?? "";

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-28 pt-5 sm:px-6">
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>

      {/* Title row */}
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="min-w-0">
          <Link
            href={`/batches/${batchId}`}
            className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink"
          >
            <IconArrowLeft size={15} /> {batch?.is_sample ? "Sample batch" : "Batch"}
          </Link>
          <h1 className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5 text-xl font-semibold tracking-tight">
            <span className="min-w-0 truncate">{doc.filename}</span>
            <StatusPill status={doc.status} />
            {doc.demo && <DemoBadge />}
          </h1>
          <p className="mt-1 text-sm text-muted">
            {doc.doc_type ? TYPE_LABEL[doc.doc_type] : "Document"} · {plural(doc.page_count, "page")}
            {doc.provider && doc.provider !== "mock" && doc.model && <span className="font-mono"> · {doc.model}</span>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-muted tabular">
            {index >= 0 ? `${index + 1} of ${docs.length}` : ""}
          </span>
          <Button size="sm" onClick={() => go(prev)} disabled={!prev} aria-label="Previous document" title="Previous ( [ )">
            <IconChevronLeft size={16} />
          </Button>
          <Button size="sm" onClick={() => go(next)} disabled={!next} aria-label="Next document" title="Next ( ] )">
            <IconChevronRight size={16} />
          </Button>
        </div>
      </div>

      {doc.demo && (
        <div className="mt-4 rounded-lg border border-amber/30 bg-amber-soft px-4 py-2.5 text-sm leading-relaxed">
          <span className="font-medium">Demo mode.</span>{" "}
          <span className="text-ink/80">
            {doc.demo_reason ??
              "No AI provider is configured, so values come from the sample's answer key, including the kind of misread a model makes on a poor scan. With an API key, Claude reads the file itself."}
          </span>
        </div>
      )}

      {error && (
        <div className="mt-4">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      {doc.status === "failed" && (
        <div className="mt-4">
          <ErrorNote>{doc.error ?? "This document couldn't be read."}</ErrorNote>
        </div>
      )}

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1.08fr)_minmax(0,1fr)] lg:gap-6">
        {/* Preview: stacked above the fields on phones, sticky on desktop */}
        <div className="lg:sticky lg:top-4 lg:self-start">
          <button
            type="button"
            onClick={() => setShowPreview((s) => !s)}
            className="mb-2 text-sm font-medium text-accent lg:hidden"
            aria-expanded={showPreview}
          >
            {showPreview ? "Hide page" : "Show page"}
          </button>
          <div
            className={cx(
              "h-[58vh] min-h-[320px] lg:h-[calc(100vh-7rem)]",
              !showPreview && "hidden lg:block",
            )}
          >
            {doc.pages.length > 0 ? (
              <DocumentPreview
                pages={doc.pages}
                selection={selection}
                hasTextLayer={doc.has_text_layer}
                filename={doc.filename}
              />
            ) : (
              <div className="flex h-full items-center justify-center rounded-lg border border-line bg-surface text-sm text-muted">
                {busyReading ? <Spinner /> : "No preview"}
              </div>
            )}
          </div>
        </div>

        <div className="min-w-0 space-y-5">
          {busyReading ? (
            <div className="flex items-center gap-3 rounded-lg border border-line px-4 py-6 text-sm text-muted" role="status">
              <Spinner /> Reading this document...
            </div>
          ) : ex ? (
            <>
              <ChecksPanel checks={doc.checks} extraction={ex} onSelect={jumpTo} stale={dirty} />
              <FieldsPanel
                fields={ex.fields}
                draft={draft.fields}
                onChange={(key, value) => setDraft((d) => d && { ...d, fields: { ...d.fields, [key]: value } })}
                flags={flags}
                selection={selection}
                onSelect={select}
                readOnly={readOnly}
              />
              {ex.doc_type === "receipt" && (
                <ExpensePanel
                  category={draft.category}
                  reason={ex.category_reason}
                  suggested={ex.category}
                  job={draft.job}
                  onCategory={(category) => setDraft((d) => d && { ...d, category })}
                  onJob={(job) => setDraft((d) => d && { ...d, job })}
                  readOnly={readOnly}
                />
              )}
              {ex.has_lines && (
                <>
                  <LineItemsEditor
                    categories={ex.doc_type === "receipt"}
                    lines={draft.lines}
                    onChange={(lines) => setDraft((d) => d && { ...d, lines })}
                    flags={flags}
                    selection={selection}
                    onSelect={select}
                    subtotal={subtotal}
                    currency={currency}
                    readOnly={readOnly}
                  />
                  <TaxesEditor
                    taxes={draft.taxes}
                    onChange={(taxes) => setDraft((d) => d && { ...d, taxes })}
                    flags={flags}
                    selection={selection}
                    onSelect={select}
                    readOnly={readOnly}
                  />
                </>
              )}
            </>
          ) : null}

          {!busyReading && (
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line px-4 py-3 text-sm">
              <span className="text-muted">Wrong type?</span>
              {(["invoice", "receipt", "custom"] as DocType[])
                .filter((t) => t !== doc.doc_type)
                .map((t) => (
                  <Button key={t} size="sm" variant="ghost" onClick={() => reextract(t)} disabled={busy !== null}>
                    <IconRefresh size={14} /> Read as {TYPE_LABEL[t].toLowerCase()}
                  </Button>
                ))}
            </div>
          )}
        </div>
      </div>

      {/* Action bar */}
      {!busyReading && ex && (
        <div className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-background">
          <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
            <p className="hidden text-sm text-muted sm:block">
              {doc.status === "approved"
                ? "Approved. Reopen to make changes."
                : dirty
                  ? "Unsaved changes. Saving re-runs every check."
                  : fails
                    ? `${plural(fails, "check")} failed. Fix the values or approve anyway.`
                    : warns
                      ? `${plural(warns, "warning")} to compare with the page before approving.`
                      : "Everything checks out."}
              <span className="ml-3 hidden font-mono text-xs lg:inline">[ ] to move · Ctrl+S to save</span>
            </p>
            <div className="flex w-full gap-2 sm:w-auto [&>button]:px-3 sm:[&>button]:px-4">
              {doc.status === "approved" ? (
                <Button className="flex-1 sm:flex-none" onClick={reopen} disabled={busy !== null}>
                  {busy === "reopen" ? <Spinner /> : <IconUndo size={16} />} Reopen
                </Button>
              ) : (
                <>
                  {dirty && (
                    <Button variant="ghost" onClick={() => saved && setDraft(saved)} disabled={busy !== null}>
                      Discard
                    </Button>
                  )}
                  <Button className="flex-1 sm:flex-none" onClick={() => void save()} disabled={!dirty || busy !== null}>
                    {busy === "save" && <Spinner />} Save and re-check
                  </Button>
                  <Button
                    variant="primary"
                    className="flex-1 sm:flex-none"
                    onClick={() => void approve()}
                    disabled={busy !== null || doc.status === "failed"}
                  >
                    {busy === "approve" ? <Spinner /> : <IconCheck size={16} />}
                    {nextToReview ? "Approve and next" : "Approve"}
                  </Button>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      <dialog
        ref={dialogRef}
        onClose={() => setConfirmOpen(false)}
        aria-labelledby="confirm-title"
        className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-lg border border-line-strong bg-background p-0 text-ink backdrop:bg-black/40"
      >
        <div className="p-5">
          <h2 id="confirm-title" className="font-semibold">
            Approve with {plural(fails, "failed check")}?
          </h2>
          <ul className="mt-3 space-y-2 text-sm">
            {doc.checks
              .filter((c) => c.status === "fail")
              .map((c) => (
                <li key={c.id} className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2">
                  <span className="font-medium">{c.label}:</span> {c.message}
                </li>
              ))}
          </ul>
          <p className="mt-3 text-sm text-muted">
            Sometimes the document itself is wrong and you still need it on file. The failed checks stay in the export.
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <Button onClick={() => setConfirmOpen(false)} autoFocus>
              Keep reviewing
            </Button>
            <Button variant="primary" onClick={() => void approve(true)} disabled={busy !== null}>
              {busy === "approve" && <Spinner />} Approve anyway
            </Button>
          </div>
        </div>
      </dialog>
    </div>
  );
}
