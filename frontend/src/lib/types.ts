// Mirrors the backend's response shapes (backend/app/api/serializers.py and app/models.py).

export type DocStatus = "queued" | "extracting" | "needs_review" | "ready" | "approved" | "failed";
export type DocType = "invoice" | "receipt" | "custom";
export type BatchMode = "auto" | "invoice" | "receipt" | "custom";
export type FieldType = "text" | "number" | "money" | "date" | "currency" | "email";
export type CheckStatus = "pass" | "warn" | "fail" | "skip";
export type TaxKind = "GST" | "HST" | "PST" | "QST" | "VAT" | "Sales tax" | "Other";
export type Value = string | number | null;

export interface FieldSpec {
  key: string;
  label: string;
  type: FieldType;
  required: boolean;
  description: string;
}

export interface Box {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface Source {
  page: number;
  quote: string;
  boxes: Box[];
  found: boolean | null;
}

export interface ExtractedField {
  key: string;
  label: string;
  type: FieldType;
  required: boolean;
  value: Value;
  confidence: number;
  source: Source | null;
  edited: boolean;
  original: Value;
}

export interface LineItem {
  description: string;
  quantity: number | null;
  unit_price: number | null;
  amount: number | null;
  confidence: number;
  source: Source | null;
  edited: boolean;
  category: string | null;
  category_reason: string;
}

export interface TaxLine {
  kind: TaxKind;
  rate: number | null;
  amount: number | null;
  confidence: number;
  source: Source | null;
  edited: boolean;
}

export interface Extraction {
  doc_type: DocType;
  has_lines: boolean;
  fields: ExtractedField[];
  line_items: LineItem[];
  taxes: TaxLine[];
  /** Receipts only: a suggested expense category, for a bookkeeper to review. */
  category: string | null;
  category_reason: string;
  category_edited: boolean;
  job: string | null;
}

export interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  message: string;
  fields: string[];
}

export interface DocSummary {
  id: string;
  batch_id: string;
  position: number;
  filename: string;
  media_type: string;
  size: number;
  status: DocStatus;
  doc_type: DocType | null;
  page_count: number;
  party: string | null;
  number: string | null;
  date: string | null;
  currency: string | null;
  total: number | null;
  category: string | null;
  job: string | null;
  issues: { fail: number; warn: number };
  top_issue: { label: string; message: string; status: CheckStatus } | null;
  provider: string | null;
  demo: boolean;
  error: string | null;
  approved_at: number | null;
  updated_at: number;
}

export interface PageInfo {
  number: number;
  width: number;
  height: number;
  url: string;
}

export interface DocumentDetail extends DocSummary {
  model: string | null;
  demo_reason: string | null;
  has_text_layer: boolean;
  pages: PageInfo[];
  extraction: Extraction | null;
  checks: Check[];
}

export interface Batch {
  id: string;
  created_at: number;
  mode: BatchMode;
  is_sample: boolean;
  custom_fields: FieldSpec[] | null;
  documents: DocSummary[];
}

export interface AppConfig {
  provider: "anthropic" | "openai" | "mock";
  model: string | null;
  demo_mode: boolean;
  public_demo: boolean;
  samples_use_demo_mode: boolean;
  limits: {
    max_upload_mb: number;
    max_pages: number;
    max_files_per_batch: number;
    data_ttl_seconds: number;
  };
}

export type ExportFormat = "xlsx" | "csv" | "csv-lines" | "csv-categories" | "sheets" | "json";

export interface CategoryRow {
  category: string;
  receipts: number;
  line_items: number;
  amount_before_tax: number;
  tax: number;
  total: number;
}
