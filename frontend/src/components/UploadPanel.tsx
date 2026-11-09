"use client";

import { useRouter } from "next/navigation";
import { useId, useRef, useState } from "react";
import { useConfig } from "@/components/ConfigProvider";
import {
  IconCamera,
  IconFile,
  IconImage,
  IconPlus,
  IconReceipt,
  IconSpark,
  IconTrash,
  IconUpload,
  IconX,
} from "@/components/icons";
import { Button, ErrorNote, Spinner, cx } from "@/components/ui";
import { api, ApiError, uploadFiles } from "@/lib/api";
import { DISCLAIMER } from "@/lib/categories";
import { fileSize, plural } from "@/lib/format";
import type { BatchMode, FieldSpec, FieldType } from "@/lib/types";

export type Kind = "invoices" | "receipts";

const KINDS: { id: Kind; label: string; hint: string; icon: typeof IconFile }[] = [
  { id: "invoices", label: "Invoices", hint: "Bills, scans and forms", icon: IconFile },
  { id: "receipts", label: "Receipts", hint: "Job receipts from your phone", icon: IconReceipt },
];

const MODES: { id: BatchMode; label: string; hint: string }[] = [
  { id: "auto", label: "Auto-detect", hint: "Invoices and forms, sorted for you." },
  { id: "invoice", label: "Invoices", hint: "Supplier bills with line items and GST/HST/PST." },
  { id: "custom", label: "Custom fields", hint: "Define the fields; the AI fills them in." },
];

const TYPES: { id: FieldType; label: string }[] = [
  { id: "text", label: "Text" },
  { id: "number", label: "Number" },
  { id: "money", label: "Money" },
  { id: "date", label: "Date" },
  { id: "email", label: "Email" },
];

const ACCEPT = ".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg";
const OK_TYPES = ["application/pdf", "image/png", "image/jpeg"];

interface DraftField {
  id: number;
  label: string;
  type: FieldType;
  description: string;
  required: boolean;
}

const EXAMPLE_FIELDS: Omit<DraftField, "id">[] = [
  { label: "Customer name", type: "text", description: "The person placing the order.", required: true },
  { label: "Phone", type: "text", description: "Contact phone number.", required: true },
  { label: "Event date", type: "date", description: "The date the order is needed.", required: true },
  { label: "Guests", type: "number", description: "Number of guests.", required: false },
  { label: "Order details", type: "text", description: "What they're ordering, in one line.", required: true },
];

function keyFor(label: string): string {
  const k = label.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
  return /^[a-z]/.test(k) ? k : `field_${k}`.slice(0, 40);
}

/** `initialKind` comes from the page, so /?mode=receipts opens on the Receipts tab. */
export function UploadPanel({ initialKind = "invoices" }: { initialKind?: Kind }) {
  const router = useRouter();
  const config = useConfig();
  const inputRef = useRef<HTMLInputElement>(null);
  const cameraRef = useRef<HTMLInputElement>(null);
  const ids = useRef(1);
  const headingId = useId();
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [kind, setKind] = useState<Kind>(initialKind);
  const [mode, setMode] = useState<BatchMode>("auto");
  const [fields, setFields] = useState<DraftField[]>([]);
  const [busy, setBusy] = useState<"upload" | "sample" | null>(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const receipts = kind === "receipts";
  const batchMode: BatchMode = receipts ? "receipt" : mode;

  const limits = config?.limits;
  const maxBytes = (limits?.max_upload_mb ?? 20) * 1024 * 1024;
  const maxFiles = limits?.max_files_per_batch ?? 50;

  function addFiles(list: FileList | File[]) {
    const incoming = Array.from(list);
    const skipped: string[] = [];
    const ok = incoming.filter((f) => {
      const typeOk = OK_TYPES.includes(f.type) || /\.(pdf|png|jpe?g)$/i.test(f.name);
      if (!typeOk) skipped.push(`${f.name} isn't a PDF, PNG or JPEG`);
      else if (f.size > maxBytes) skipped.push(`${f.name} is over ${limits?.max_upload_mb ?? 20} MB`);
      return typeOk && f.size <= maxBytes;
    });
    setFiles((prev) => {
      const merged = [...prev];
      for (const f of ok) {
        if (!merged.some((m) => m.name === f.name && m.size === f.size)) merged.push(f);
      }
      if (merged.length > maxFiles) skipped.push(`a batch holds up to ${maxFiles} files`);
      return merged.slice(0, maxFiles);
    });
    setNotice(skipped.length ? `Skipped: ${skipped.join("; ")}.` : null);
    setError(null);
  }

  function addField(seed?: Omit<DraftField, "id">) {
    setFields((f) => [
      ...f,
      { id: ids.current++, label: "", type: "text", description: "", required: false, ...seed },
    ]);
  }

  function customSpecs(): FieldSpec[] | null {
    const named = fields.filter((f) => f.label.trim());
    const keys = named.map((f) => keyFor(f.label));
    if (new Set(keys).size !== keys.length) {
      setError("Each custom field needs a different name.");
      return null;
    }
    return named.map((f, i) => ({
      key: keys[i],
      label: f.label.trim().slice(0, 60),
      type: f.type,
      description: f.description.trim().slice(0, 300),
      required: f.required,
    }));
  }

  async function start() {
    setError(null);
    let specs: FieldSpec[] | undefined;
    if (batchMode === "custom") {
      const s = customSpecs();
      if (!s) return;
      if (!s.length) {
        setError("Add at least one field to extract.");
        return;
      }
      specs = s;
    }
    setBusy("upload");
    setProgress(0);
    try {
      const batch = await api.createBatch(batchMode, specs);
      await uploadFiles(batch.id, files, setProgress);
      router.push(`/batches/${batch.id}`);
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(null);
    }
  }

  async function trySamples() {
    setError(null);
    setBusy("sample");
    try {
      const batch = await (receipts ? api.sampleReceipts() : api.sampleBatch());
      router.push(`/batches/${batch.id}`);
    } catch (e) {
      setError((e as ApiError).message);
      setBusy(null);
    }
  }

  const privacy =
    config?.public_demo || config?.demo_mode
      ? `Demo only. Don't upload sensitive documents.${
          config?.limits.data_ttl_seconds ? " Files are deleted within an hour." : ""
        }`
      : "Files are stored on this server until you delete the batch.";

  return (
    <section aria-labelledby={headingId} className="rounded-lg border border-line bg-background">
      <div className="border-b border-line px-5 py-4">
        <h2 id={headingId} className="text-base font-semibold">
          {receipts ? "Snap your job receipts" : "Start a batch"}
        </h2>
        <p className="mt-0.5 text-sm text-muted">
          PDF, PNG or JPEG. Up to {limits?.max_files_per_batch ?? 50} files, {limits?.max_upload_mb ?? 20} MB and{" "}
          {limits?.max_pages ?? 30} pages each.
        </p>
      </div>

      <div className="space-y-5 p-5">
        <fieldset>
          <legend className="sr-only">What are you uploading?</legend>
          <div className="grid grid-cols-2 gap-1 rounded-lg border border-line bg-surface p-1">
            {KINDS.map((k) => (
              <label
                key={k.id}
                className={cx(
                  "flex min-h-14 cursor-pointer items-center gap-3 rounded-md px-3 py-2 transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent",
                  kind === k.id ? "bg-background font-medium ring-1 ring-inset ring-accent" : "text-muted hover:text-ink",
                )}
              >
                <input
                  type="radio"
                  name="kind"
                  value={k.id}
                  checked={kind === k.id}
                  onChange={() => {
                    setKind(k.id);
                    setError(null);
                  }}
                  className="sr-only"
                />
                <k.icon size={20} className={kind === k.id ? "text-accent" : undefined} />
                <span className="min-w-0">
                  <span className="block text-sm leading-tight">{k.label}</span>
                  <span className="block truncate text-xs font-normal leading-snug text-muted">{k.hint}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>

        {receipts && (
          <p className="rounded-lg border border-line bg-surface px-3 py-2.5 text-sm leading-relaxed">
            Reads the vendor, date, items, tax and total, checks the math, and suggests an expense category for each
            one. <span className="text-muted">{DISCLAIMER}</span>
          </p>
        )}

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            addFiles(e.dataTransfer.files);
          }}
          className={cx(
            "flex flex-col items-center justify-center rounded-lg border border-dashed px-4 py-8 text-center transition-colors",
            dragging ? "border-accent bg-accent-soft" : "border-line-strong bg-surface",
          )}
        >
          <span className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-lg border border-line bg-background text-accent">
            <IconUpload size={20} />
          </span>
          <p className="text-sm font-medium">
            {receipts ? "Drop receipt photos here" : "Drop invoices, receipts or forms here"}
          </p>
          <p className="mt-1 text-sm text-muted">
            {receipts ? "Crumpled and slightly crooked is fine." : "Scans and phone photos work too."}
          </p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {receipts && (
              <Button variant="primary" onClick={() => cameraRef.current?.click()}>
                <IconCamera size={16} /> Take a photo
              </Button>
            )}
            <Button size={receipts ? "md" : "sm"} onClick={() => inputRef.current?.click()}>
              Choose files
            </Button>
          </div>
          <input
            ref={cameraRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="sr-only"
            tabIndex={-1}
            aria-label="Take a photo of a receipt"
            onChange={(e) => {
              if (e.target.files) addFiles(e.target.files);
              e.target.value = "";
            }}
          />
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={ACCEPT}
            className="sr-only"
            tabIndex={-1}
            aria-label="Choose files to upload"
            onChange={(e) => {
              if (e.target.files) addFiles(e.target.files);
              e.target.value = "";
            }}
          />
        </div>

        {notice && <p className="text-sm text-amber">{notice}</p>}

        {files.length > 0 && (
          <ul className="max-h-48 divide-y divide-line overflow-y-auto rounded-lg border border-line" aria-label="Selected files">
            {files.map((f, i) => (
              <li key={`${f.name}-${f.size}`} className="flex items-center gap-3 px-3 py-2 text-sm">
                {f.type === "application/pdf" || /\.pdf$/i.test(f.name) ? (
                  <IconFile size={16} className="shrink-0 text-muted" />
                ) : (
                  <IconImage size={16} className="shrink-0 text-muted" />
                )}
                <span className="min-w-0 flex-1 truncate">{f.name}</span>
                <span className="shrink-0 font-mono text-xs text-muted">{fileSize(f.size)}</span>
                <button
                  type="button"
                  onClick={() => setFiles((all) => all.filter((_, j) => j !== i))}
                  className="rounded p-1 text-muted hover:bg-surface hover:text-ink"
                  aria-label={`Remove ${f.name}`}
                >
                  <IconX size={14} />
                </button>
              </li>
            ))}
          </ul>
        )}

        {!receipts && (
          <fieldset>
            <legend className="mb-2 text-sm font-medium">What&apos;s in the batch?</legend>
            <div className="grid gap-2 sm:grid-cols-3">
              {MODES.map((m) => (
                <label
                  key={m.id}
                  className={cx(
                    "cursor-pointer rounded-lg border px-3 py-2.5 text-sm transition-colors has-[:focus-visible]:outline has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-accent",
                    mode === m.id ? "border-accent bg-accent-soft" : "border-line hover:bg-surface",
                  )}
                >
                  <input
                    type="radio"
                    name="mode"
                    value={m.id}
                    checked={mode === m.id}
                    onChange={() => {
                      setMode(m.id);
                      if (m.id === "custom" && fields.length === 0) addField();
                    }}
                    className="sr-only"
                  />
                  <span className="block font-medium">{m.label}</span>
                  <span className="mt-0.5 block text-xs leading-snug text-muted">{m.hint}</span>
                </label>
              ))}
            </div>
          </fieldset>
        )}

        {!receipts && mode === "custom" && (
          <div className="space-y-3 rounded-lg border border-line bg-surface p-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-sm font-medium">Fields to extract</p>
              <button
                type="button"
                className="text-xs font-medium text-accent hover:underline"
                onClick={() => setFields(EXAMPLE_FIELDS.map((f) => ({ ...f, id: ids.current++ })))}
              >
                Use an order form example
              </button>
            </div>
            {fields.map((f, i) => (
              <div key={f.id} className="grid grid-cols-[1fr_6.5rem_auto] gap-2 rounded-lg border border-line bg-background p-2.5">
                <label className="sr-only" htmlFor={`f-label-${f.id}`}>
                  Field {i + 1} name
                </label>
                <input
                  id={`f-label-${f.id}`}
                  value={f.label}
                  placeholder="Field name, e.g. PO number"
                  maxLength={60}
                  onChange={(e) => setFields((all) => all.map((x) => (x.id === f.id ? { ...x, label: e.target.value } : x)))}
                  className="h-9 min-w-0 rounded-md border border-line bg-background px-2.5 text-sm"
                />
                <label className="sr-only" htmlFor={`f-type-${f.id}`}>
                  Field {i + 1} type
                </label>
                <select
                  id={`f-type-${f.id}`}
                  value={f.type}
                  onChange={(e) =>
                    setFields((all) => all.map((x) => (x.id === f.id ? { ...x, type: e.target.value as FieldType } : x)))
                  }
                  className="h-9 rounded-md border border-line bg-background px-2 text-sm"
                >
                  {TYPES.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => setFields((all) => all.filter((x) => x.id !== f.id))}
                  className="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted hover:bg-surface hover:text-danger"
                  aria-label={`Remove field ${f.label || i + 1}`}
                >
                  <IconTrash size={16} />
                </button>
                <label className="sr-only" htmlFor={`f-desc-${f.id}`}>
                  Field {i + 1} description
                </label>
                <input
                  id={`f-desc-${f.id}`}
                  value={f.description}
                  placeholder="Hint for the AI (optional)"
                  maxLength={300}
                  onChange={(e) =>
                    setFields((all) => all.map((x) => (x.id === f.id ? { ...x, description: e.target.value } : x)))
                  }
                  className="col-span-2 h-9 min-w-0 rounded-md border border-line bg-background px-2.5 text-sm"
                />
                <label className="flex items-center gap-1.5 text-xs text-muted">
                  <input
                    type="checkbox"
                    checked={f.required}
                    onChange={(e) =>
                      setFields((all) => all.map((x) => (x.id === f.id ? { ...x, required: e.target.checked } : x)))
                    }
                    className="accent-[var(--accent)]"
                  />
                  Required
                </label>
              </div>
            ))}
            <Button size="sm" onClick={() => addField()} disabled={fields.length >= 25}>
              <IconPlus size={15} /> Add field
            </Button>
          </div>
        )}

        {error && <ErrorNote>{error}</ErrorNote>}

        <div className="flex flex-col gap-2 sm:flex-row">
          <Button variant="primary" className="sm:flex-1" disabled={!files.length || busy !== null} onClick={start}>
            {busy === "upload" ? (
              <>
                <Spinner /> Uploading {Math.round(progress * 100)}%
              </>
            ) : files.length ? (
              `Read ${plural(files.length, receipts ? "receipt" : "document")}`
            ) : (
              `Read ${receipts ? "receipts" : "documents"}`
            )}
          </Button>
          <Button className="sm:flex-1" disabled={busy !== null} onClick={trySamples}>
            {busy === "sample" ? <Spinner /> : <IconSpark size={16} />}
            {receipts ? "Try 3 sample receipts" : "Try 12 sample documents"}
          </Button>
        </div>
        <p className="text-xs leading-relaxed text-muted">{privacy}</p>
      </div>
    </section>
  );
}
