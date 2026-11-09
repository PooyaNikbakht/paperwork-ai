"use client";

import { IconPlus, IconTrash, IconUndo } from "@/components/icons";
import { ConfidenceBadge, cx } from "@/components/ui";
import { CATEGORIES, DISCLAIMER } from "@/lib/categories";
import { money } from "@/lib/format";
import type { ExtractedField, Source, TaxKind, Value } from "@/lib/types";
import { SourceButton } from "./SourceButton";
import { type Flag, type Selection, domId, rowFlag } from "./selection";

// ---- Draft state: strings while editing, converted on save ----

export interface LineDraft {
  description: string;
  quantity: string;
  unit_price: string;
  amount: string;
  confidence: number;
  source: Source | null;
  edited: boolean;
  category: string;
  category_reason: string;
}

export interface TaxDraft {
  kind: TaxKind;
  rate: string;
  amount: string;
  confidence: number;
  source: Source | null;
  edited: boolean;
}

export const TAX_KINDS: TaxKind[] = ["GST", "HST", "PST", "QST", "VAT", "Sales tax", "Other"];

export function str(v: Value | undefined, type?: ExtractedField["type"]): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "number") return type === "money" ? v.toFixed(2) : String(v);
  return v;
}

export function moneyStr(v: number | null): string {
  return v === null ? "" : v.toFixed(2);
}

export function qtyStr(v: number | null): string {
  return v === null ? "" : String(v);
}

export function num(s: string): number | null {
  const t = s.replace(/[$,\s]/g, "");
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

const FLAG_BORDER: Record<Flag, string> = {
  fail: "border-l-danger bg-danger-soft/50",
  warn: "border-l-amber bg-amber-soft/50",
};

const inputBase =
  "h-9 w-full min-w-0 rounded-md border border-line bg-background px-2.5 text-sm tabular placeholder:text-muted/60 focus:border-accent";

// ---- Header fields ----

export function FieldsPanel({
  fields,
  draft,
  onChange,
  flags,
  selection,
  onSelect,
  readOnly,
}: {
  fields: ExtractedField[];
  draft: Record<string, string>;
  onChange: (key: string, value: string) => void;
  flags: Map<string, Flag>;
  selection: Selection | null;
  onSelect: (path: string) => void;
  readOnly: boolean;
}) {
  return (
    <section aria-labelledby="fields-heading" className="rounded-lg border border-line">
      <h2 id="fields-heading" className="border-b border-line px-4 py-3 font-semibold">
        Fields
      </h2>
      <div className="divide-y divide-line">
        {fields.map((f) => {
          const value = draft[f.key] ?? "";
          const changed = value !== str(f.original, f.type);
          const flag = flags.get(f.key);
          const inputId = `input-${f.key}`;
          const isDate = f.type === "date" && (value === "" || /^\d{4}-\d{2}-\d{2}$/.test(value));
          return (
            <div
              key={f.key}
              id={domId(f.key)}
              className={cx(
                "grid scroll-mt-24 grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1.5 border-l-2 px-4 py-2.5 sm:grid-cols-[9.5rem_1fr_auto]",
                flag ? FLAG_BORDER[flag] : "border-l-transparent",
              )}
            >
              <label htmlFor={inputId} className="col-span-2 text-sm text-muted sm:col-span-1">
                {f.label}
                {f.required && <span className="text-danger"> *</span>}
                {(f.value !== null || changed) && (
                  <span className="ml-2 inline-flex align-middle sm:hidden">
                    <ConfidenceBadge value={f.confidence} edited={changed || f.edited} />
                  </span>
                )}
              </label>
              <div className="flex min-w-0 items-center gap-2">
                <input
                  id={inputId}
                  type={isDate ? "date" : f.type === "email" ? "email" : "text"}
                  inputMode={f.type === "money" || f.type === "number" ? "decimal" : undefined}
                  value={value}
                  readOnly={readOnly}
                  onChange={(e) => onChange(f.key, f.type === "currency" ? e.target.value.toUpperCase() : e.target.value)}
                  onFocus={() => onSelect(f.key)}
                  placeholder={f.value === null ? "Not found" : ""}
                  maxLength={f.type === "currency" ? 3 : 500}
                  className={cx(inputBase, f.type === "money" && "text-right", readOnly && "bg-surface")}
                />
                <span className="hidden w-14 shrink-0 sm:inline-flex">
                  {f.value !== null || changed ? <ConfidenceBadge value={f.confidence} edited={changed || f.edited} /> : null}
                </span>
              </div>
              <div className="flex items-center gap-1">
                {changed && !readOnly && (
                  <button
                    type="button"
                    onClick={() => onChange(f.key, str(f.original, f.type))}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted hover:bg-surface hover:text-ink"
                    aria-label={`Undo change to ${f.label}`}
                    title={`Back to what the AI read: ${str(f.original, f.type) || "empty"}`}
                  >
                    <IconUndo size={15} />
                  </button>
                )}
                <SourceButton
                  source={f.source}
                  label={f.label}
                  active={selection?.path === f.key}
                  onClick={() => onSelect(f.key)}
                />
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---- Expense category and job (receipts) ----

function CategorySelect({
  id,
  value,
  onChange,
  readOnly,
  label,
}: {
  id: string;
  value: string;
  onChange: (value: string) => void;
  readOnly: boolean;
  label: string;
}) {
  return (
    <select
      id={id}
      aria-label={label}
      value={value}
      disabled={readOnly}
      onChange={(e) => onChange(e.target.value)}
      className={cx(inputBase, "px-2", readOnly && "bg-surface")}
    >
      {!CATEGORIES.some((c) => c === value) && <option value={value}>{value || "Choose a category"}</option>}
      {CATEGORIES.map((c) => (
        <option key={c} value={c}>
          {c}
        </option>
      ))}
    </select>
  );
}

export function ExpensePanel({
  category,
  reason,
  suggested,
  job,
  onCategory,
  onJob,
  readOnly,
}: {
  category: string;
  reason: string;
  suggested: string | null;
  job: string;
  onCategory: (value: string) => void;
  onJob: (value: string) => void;
  readOnly: boolean;
}) {
  const changed = suggested !== null && category !== suggested;
  return (
    <section aria-labelledby="expense-heading" className="rounded-lg border border-line">
      <div className="border-b border-line px-4 py-3">
        <h2 id="expense-heading" className="font-semibold">
          Expense category
        </h2>
        <p className="mt-0.5 text-xs leading-snug text-muted">{DISCLAIMER}</p>
      </div>
      <div className="space-y-3 px-4 py-3">
        <div>
          <label htmlFor="expense-category" className="mb-1 block text-sm text-muted">
            Suggested category for this receipt
          </label>
          <CategorySelect
            id="expense-category"
            label="Suggested category for this receipt"
            value={category}
            onChange={onCategory}
            readOnly={readOnly}
          />
          <p className="mt-1.5 flex flex-wrap items-center gap-x-2 text-xs text-muted">
            {reason && !changed && <span>{reason}</span>}
            {changed && <span>Changed from {suggested}. Save to keep it.</span>}
            {changed && !readOnly && suggested && (
              <button
                type="button"
                onClick={() => onCategory(suggested)}
                className="inline-flex items-center gap-1 font-medium text-accent hover:underline"
              >
                <IconUndo size={13} /> Undo
              </button>
            )}
          </p>
        </div>
        <div>
          <label htmlFor="expense-job" className="mb-1 block text-sm text-muted">
            Job or project <span className="text-xs">(optional)</span>
          </label>
          <input
            id="expense-job"
            value={job}
            readOnly={readOnly}
            maxLength={80}
            placeholder="e.g. Maple St deck"
            onChange={(e) => onJob(e.target.value)}
            className={cx(inputBase, readOnly && "bg-surface")}
          />
        </div>
      </div>
    </section>
  );
}

// ---- Line items ----

export function LineItemsEditor({
  lines,
  onChange,
  flags,
  selection,
  onSelect,
  subtotal,
  currency,
  readOnly,
  categories = false,
}: {
  lines: LineDraft[];
  onChange: (lines: LineDraft[]) => void;
  flags: Map<string, Flag>;
  selection: Selection | null;
  onSelect: (path: string) => void;
  subtotal: number | null;
  currency: string;
  readOnly: boolean;
  /** Show a suggested category per line (receipts). */
  categories?: boolean;
}) {
  const update = (i: number, patch: Partial<LineDraft>) =>
    onChange(lines.map((l, j) => (j === i ? { ...l, ...patch, edited: true } : l)));
  const sum = lines.reduce((acc, l) => acc + (num(l.amount) ?? 0), 0);
  const diff = subtotal === null ? null : Math.round((subtotal - sum) * 100) / 100;

  return (
    <section aria-labelledby="lines-heading" className="rounded-lg border border-line">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h2 id="lines-heading" className="font-semibold">
          Line items <span className="font-mono text-xs font-normal text-muted">{lines.length}</span>
        </h2>
      </div>
      <div className="hidden grid-cols-[minmax(0,1fr)_4rem_6rem_6.5rem_7.25rem] gap-2 border-b border-line bg-surface px-4 py-2 text-xs text-muted md:grid">
        <span>Description</span>
        <span className="text-right">Qty</span>
        <span className="text-right">Unit price</span>
        <span className="text-right">Amount</span>
        <span />
      </div>
      <ul className="divide-y divide-line">
        {lines.map((l, i) => {
          const path = `line_items.${i}`;
          const flag = rowFlag(flags, path);
          const q = num(l.quantity);
          const p = num(l.unit_price);
          const a = num(l.amount);
          const expected = q !== null && p !== null ? Math.round(q * p * 100) / 100 : null;
          const mathOff = expected !== null && a !== null && Math.abs(expected - a) > 0.015;
          return (
            <li
              key={i}
              id={domId(path)}
              className={cx(
                "scroll-mt-24 border-l-2 px-4 py-2.5",
                flag ? FLAG_BORDER[flag] : "border-l-transparent",
              )}
            >
              <div className="grid grid-cols-3 gap-2 md:grid-cols-[minmax(0,1fr)_4rem_6rem_6.5rem_7.25rem]">
                <label className="col-span-3 md:col-span-1">
                  <span className="sr-only">Line {i + 1} description</span>
                  <input
                    value={l.description}
                    readOnly={readOnly}
                    onChange={(e) => update(i, { description: e.target.value })}
                    onFocus={() => onSelect(path)}
                    className={cx(inputBase, readOnly && "bg-surface")}
                  />
                </label>
                {(
                  [
                    ["quantity", "Qty", l.quantity],
                    ["unit_price", "Unit price", l.unit_price],
                    ["amount", "Amount", l.amount],
                  ] as const
                ).map(([key, label, val]) => (
                  <label key={key} className="min-w-0">
                    <span className="mb-1 block text-[11px] text-muted md:sr-only">
                      {label}
                      <span className="sr-only"> for line {i + 1}</span>
                    </span>
                    <input
                      value={val}
                      inputMode="decimal"
                      readOnly={readOnly}
                      onChange={(e) => update(i, { [key]: e.target.value })}
                      onFocus={() => onSelect(path)}
                      className={cx(
                        inputBase,
                        "text-right",
                        key === "amount" && mathOff && "border-danger text-danger",
                        readOnly && "bg-surface",
                      )}
                    />
                  </label>
                ))}
                <div className="col-span-3 flex items-center justify-end gap-1 md:col-span-1">
                  <SourceButton
                    source={l.source}
                    label={`line ${i + 1}`}
                    active={selection?.path.startsWith(path) ?? false}
                    onClick={() => onSelect(path)}
                  />
                  {!readOnly && (
                    <button
                      type="button"
                      onClick={() => onChange(lines.filter((_, j) => j !== i))}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted hover:bg-surface hover:text-danger"
                      aria-label={`Remove line ${i + 1}`}
                    >
                      <IconTrash size={15} />
                    </button>
                  )}
                </div>
              </div>
              {categories && (
                <div className="mt-2 grid grid-cols-[minmax(0,13rem)_1fr] items-center gap-x-3 gap-y-1 max-sm:grid-cols-1">
                  <CategorySelect
                    id={`line-${i}-category`}
                    label={`Suggested category for line ${i + 1}`}
                    value={l.category}
                    onChange={(value) => update(i, { category: value, category_reason: "Set by you." })}
                    readOnly={readOnly}
                  />
                  <p className="text-xs leading-snug text-muted">{l.category_reason}</p>
                </div>
              )}
              {(mathOff || (!l.edited && l.confidence < 0.7)) && (
                <p className="mt-1.5 flex flex-wrap gap-x-3 text-xs">
                  {mathOff && (
                    <span className="text-danger">
                      {l.quantity} × {money(p)} = {money(expected)}
                    </span>
                  )}
                  {!l.edited && l.confidence < 0.7 && (
                    <span className="text-amber">AI confidence {Math.round(l.confidence * 100)}%</span>
                  )}
                </p>
              )}
            </li>
          );
        })}
      </ul>
      <div className="flex flex-col gap-3 border-t border-line px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        {!readOnly ? (
          <button
            type="button"
            onClick={() =>
              onChange([
                ...lines,
                {
                  description: "",
                  quantity: "1",
                  unit_price: "",
                  amount: "",
                  confidence: 1,
                  source: null,
                  edited: true,
                  category: categories ? "Other" : "",
                  category_reason: categories ? "Set by you." : "",
                },
              ])
            }
            className="inline-flex items-center gap-1.5 self-start text-sm font-medium text-accent hover:underline"
          >
            <IconPlus size={15} /> Add line
          </button>
        ) : (
          <span />
        )}
        <p className="text-sm tabular" aria-live="polite">
          <span className="text-muted">Lines add up to </span>
          <span className="font-medium">{money(sum)}</span>
          {diff !== null &&
            (Math.abs(diff) <= 0.015 ? (
              <span className="text-accent"> = subtotal</span>
            ) : (
              <span className="text-danger">
                {" "}
                · subtotal {money(subtotal)} {currency} · off by {money(Math.abs(diff))}
              </span>
            ))}
        </p>
      </div>
    </section>
  );
}

// ---- Taxes ----

export function TaxesEditor({
  taxes,
  onChange,
  flags,
  selection,
  onSelect,
  readOnly,
}: {
  taxes: TaxDraft[];
  onChange: (taxes: TaxDraft[]) => void;
  flags: Map<string, Flag>;
  selection: Selection | null;
  onSelect: (path: string) => void;
  readOnly: boolean;
}) {
  const update = (i: number, patch: Partial<TaxDraft>) =>
    onChange(taxes.map((t, j) => (j === i ? { ...t, ...patch, edited: true } : t)));
  return (
    <section aria-labelledby="taxes-heading" className="rounded-lg border border-line">
      <h2 id="taxes-heading" className="border-b border-line px-4 py-3 font-semibold">
        Taxes
      </h2>
      {taxes.length === 0 && <p className="px-4 py-3 text-sm text-muted">No taxes on this document.</p>}
      <ul className="divide-y divide-line">
        {taxes.map((t, i) => {
          const path = `taxes.${i}`;
          const flag = rowFlag(flags, path);
          return (
            <li
              key={i}
              id={domId(path)}
              className={cx(
                "grid scroll-mt-24 grid-cols-[6.5rem_1fr_1fr] items-end gap-2 border-l-2 px-4 py-2.5 sm:grid-cols-[7.5rem_6rem_1fr_auto]",
                flag ? FLAG_BORDER[flag] : "border-l-transparent",
              )}
            >
              <label className="min-w-0">
                <span className="mb-1 block text-[11px] text-muted">Kind</span>
                <select
                  value={t.kind}
                  disabled={readOnly}
                  onChange={(e) => update(i, { kind: e.target.value as TaxKind })}
                  className={cx(inputBase, "px-2")}
                >
                  {TAX_KINDS.map((k) => (
                    <option key={k}>{k}</option>
                  ))}
                </select>
              </label>
              <label className="min-w-0">
                <span className="mb-1 block text-[11px] text-muted">Rate %</span>
                <input
                  value={t.rate}
                  inputMode="decimal"
                  readOnly={readOnly}
                  onChange={(e) => update(i, { rate: e.target.value })}
                  onFocus={() => onSelect(path)}
                  className={cx(inputBase, "text-right")}
                />
              </label>
              <label className="min-w-0">
                <span className="mb-1 block text-[11px] text-muted">Amount</span>
                <input
                  value={t.amount}
                  inputMode="decimal"
                  readOnly={readOnly}
                  onChange={(e) => update(i, { amount: e.target.value })}
                  onFocus={() => onSelect(path)}
                  className={cx(inputBase, "text-right")}
                />
              </label>
              <div className="col-span-3 flex justify-end gap-1 sm:col-span-1">
                <SourceButton
                  source={t.source}
                  label={t.kind}
                  active={selection?.path.startsWith(path) ?? false}
                  onClick={() => onSelect(path)}
                />
                {!readOnly && (
                  <button
                    type="button"
                    onClick={() => onChange(taxes.filter((_, j) => j !== i))}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md text-muted hover:bg-surface hover:text-danger"
                    aria-label={`Remove ${t.kind}`}
                  >
                    <IconTrash size={15} />
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {!readOnly && (
        <div className="border-t border-line px-4 py-3">
          <button
            type="button"
            onClick={() =>
              onChange([...taxes, { kind: "GST", rate: "5", amount: "", confidence: 1, source: null, edited: true }])
            }
            className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"
          >
            <IconPlus size={15} /> Add tax
          </button>
        </div>
      )}
    </section>
  );
}
