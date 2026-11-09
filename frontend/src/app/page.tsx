import { IconCheck, IconDownload, IconEye, IconShield, IconTable, IconUpload } from "@/components/icons";
import { UploadPanel } from "@/components/UploadPanel";
import { CheckIcon } from "@/components/ui";
import type { CheckStatus } from "@/lib/types";

const CHECKS: { label: string; what: string; example: string; status: CheckStatus }[] = [
  {
    label: "Line items add up",
    what: "Every line amount, added up, must equal the subtotal.",
    example: "Line items add up to 524.00, but the subtotal is 564.00, a difference of 40.00.",
    status: "fail",
  },
  {
    label: "Totals add up",
    what: "Subtotal plus each tax (and any tip) must equal the total.",
    example: "Subtotal 225.00 and taxes 29.25 come to 254.25, but the total says 264.25.",
    status: "fail",
  },
  {
    label: "Line math",
    what: "Quantity times unit price must match each line's amount.",
    example: "Line 3: 4 × 320.00 = 1,280.00, but the amount says 1,230.00.",
    status: "fail",
  },
  {
    label: "Duplicates",
    what: "Same vendor and invoice number as another document, so you don't pay twice.",
    example: "Invoice NP-24817 from Northpeak already appears earlier in this batch.",
    status: "fail",
  },
  {
    label: "Tax rates",
    what: "GST, HST, PST and QST amounts match Canadian rates for the subtotal.",
    example: "HST is 13% in Ontario and 15% in the Atlantic provinces; this says 12%.",
    status: "warn",
  },
  {
    label: "Currency",
    what: "One currency, used consistently. Catches USD invoices booked as CAD.",
    example: "The currency is set to USD, but the document also mentions CAD.",
    status: "fail",
  },
  {
    label: "Dates",
    what: "Dates are real, in order, and not years away.",
    example: "The due date is before the invoice date.",
    status: "fail",
  },
  {
    label: "Source found on the page",
    what: "Every value's quoted source must exist on the page, so nothing is invented.",
    example: "Couldn't find the quoted text for Total on the page.",
    status: "warn",
  },
];

const STEPS = [
  { icon: IconUpload, title: "Drop the pile", text: "PDFs, scans and phone photos, as many as you have." },
  {
    icon: IconEye,
    title: "AI reads each one",
    text: "Claude or OpenAI pulls out every field, with the exact text it read it from.",
  },
  { icon: IconShield, title: "Checks run", text: "The math, taxes, dates, currency and duplicates are verified." },
  { icon: IconTable, title: "Review and export", text: "Fix what's flagged, approve, and download a clean sheet." },
];

export default async function Home({ searchParams }: { searchParams: Promise<{ mode?: string }> }) {
  const { mode } = await searchParams;
  return (
    <div className="mx-auto w-full max-w-7xl px-4 sm:px-6">
      <section className="grid gap-10 py-10 sm:py-14 lg:grid-cols-[1.05fr_1fr] lg:gap-14 lg:py-20">
        <div className="max-w-xl lg:pt-6">
          <p className="font-mono text-xs uppercase tracking-[0.14em] text-accent">Paperwork automation</p>
          <h1 className="mt-4 text-4xl font-semibold leading-[1.08] tracking-tight sm:text-5xl">
            Stop typing invoices into spreadsheets.
          </h1>
          <p className="mt-5 text-lg leading-relaxed text-muted">
            Drop in supplier invoices, receipts and forms. Get back clean rows you can trust, because every value
            shows where it came from and every document is checked before you approve it.
          </p>
          <ul className="mt-7 space-y-3 text-[15px]">
            {[
              "Reads PDFs, scanned pages and phone photos",
              "Click any value to see it highlighted on the page",
              "Flags math errors, wrong taxes, duplicates and misreads",
              "Receipts mode for trades: suggested expense categories, ready for your bookkeeper",
              "Exports to Excel, CSV, Google Sheets or JSON",
            ].map((t) => (
              <li key={t} className="flex gap-3">
                <span className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
                  <IconCheck size={13} />
                </span>
                {t}
              </li>
            ))}
          </ul>
        </div>
        <UploadPanel initialKind={mode === "receipts" ? "receipts" : "invoices"} />
      </section>

      <section id="checks" aria-labelledby="checks-title" className="scroll-mt-6 border-t border-line py-14">
        <div className="max-w-2xl">
          <p className="font-mono text-xs uppercase tracking-[0.14em] text-accent">Trust, but verify</p>
          <h2 id="checks-title" className="mt-3 text-3xl font-semibold tracking-tight">
            AI reads fast. These checks make sure it read right.
          </h2>
          <p className="mt-4 leading-relaxed text-muted">
            Models misread blurry scans, and suppliers make mistakes too. Every document goes through the same checks a
            careful bookkeeper would do by hand. Anything that fails is held for review with a plain explanation, and
            documents that pass can be approved in one click.
          </p>
        </div>
        <ul className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {CHECKS.map((c) => (
            <li key={c.label} className="flex flex-col rounded-lg border border-line p-4">
              <p className="flex items-center gap-2 font-medium">
                <CheckIcon status="pass" size={17} />
                {c.label}
              </p>
              <p className="mt-2 text-sm leading-relaxed text-muted">{c.what}</p>
              <div
                className={`mt-4 flex gap-2 rounded-md border px-2.5 py-2 text-xs leading-relaxed ${
                  c.status === "fail" ? "border-danger/30 bg-danger-soft" : "border-amber/30 bg-amber-soft"
                }`}
              >
                <CheckIcon status={c.status} size={14} />
                <span className="text-ink">{c.example}</span>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="how-title" className="border-t border-line py-14">
        <h2 id="how-title" className="text-2xl font-semibold tracking-tight">
          How it works
        </h2>
        <ol className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => (
            <li key={s.title}>
              <div className="flex items-center gap-3">
                <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line text-accent">
                  <s.icon size={18} />
                </span>
                <span className="font-mono text-xs text-muted">0{i + 1}</span>
              </div>
              <p className="mt-4 font-medium">{s.title}</p>
              <p className="mt-1.5 text-sm leading-relaxed text-muted">{s.text}</p>
            </li>
          ))}
        </ol>
        <div className="mt-12 flex flex-col gap-4 rounded-lg border border-line bg-surface p-5 sm:flex-row sm:items-center sm:justify-between">
          <p className="flex items-center gap-3 text-sm">
            <IconDownload size={18} className="shrink-0 text-accent" />
            Exports go where you already work.
          </p>
          <ul className="flex flex-wrap gap-2 font-mono text-xs">
            {["Excel .xlsx", "CSV", "Google Sheets", "JSON"].map((x) => (
              <li key={x} className="rounded-md border border-line bg-background px-2.5 py-1">
                {x}
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
