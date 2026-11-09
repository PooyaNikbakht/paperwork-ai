import { site } from "@/config/site";
import type {
  AppConfig,
  Batch,
  BatchMode,
  CategoryRow,
  DocType,
  DocumentDetail,
  ExportFormat,
  FieldSpec,
  LineItem,
  TaxLine,
  Value,
} from "@/lib/types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export function apiUrl(path: string): string {
  return `${site.apiUrl}${path}`;
}

async function parseError(res: Response): Promise<ApiError> {
  try {
    const body = await res.json();
    if (body?.error?.message) return new ApiError(res.status, body.error.code, body.error.message);
  } catch {
    // not JSON
  }
  return new ApiError(res.status, "http_error", `The server answered ${res.status}.`);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(apiUrl(path), {
      ...init,
      headers: init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : undefined,
    });
  } catch {
    throw new ApiError(0, "network", "Can't reach the server. Check your connection and try again.");
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  config: () => request<AppConfig>("/config"),
  createBatch: (mode: BatchMode, customFields?: FieldSpec[]) =>
    request<Batch>("/batches", {
      method: "POST",
      body: JSON.stringify({ mode, custom_fields: customFields?.length ? customFields : null }),
    }),
  sampleBatch: () => request<Batch>("/batches/sample", { method: "POST" }),
  sampleReceipts: () => request<Batch>("/batches/sample-receipts", { method: "POST" }),
  categories: (id: string) => request<{ rows: CategoryRow[] }>(`/batches/${id}/categories`),
  batch: (id: string) => request<Batch>(`/batches/${id}`),
  deleteBatch: (id: string) => request<void>(`/batches/${id}`, { method: "DELETE" }),
  approveReady: (id: string) => request<Batch>(`/batches/${id}/approve-ready`, { method: "POST" }),
  document: (id: string) => request<DocumentDetail>(`/documents/${id}`),
  editDocument: (
    id: string,
    patch: {
      fields?: Record<string, Value>;
      line_items?: LineItem[];
      taxes?: TaxLine[];
      category?: string;
      job?: string | null;
    },
  ) => request<DocumentDetail>(`/documents/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  approve: (id: string, acknowledge = false) =>
    request<DocumentDetail>(`/documents/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ acknowledge }),
    }),
  reopen: (id: string) => request<DocumentDetail>(`/documents/${id}/reopen`, { method: "POST" }),
  reextract: (id: string, docType?: DocType) =>
    request<DocumentDetail>(`/documents/${id}/reextract`, {
      method: "POST",
      body: JSON.stringify({ doc_type: docType ?? null }),
    }),
};

/** Upload files with progress (fetch can't report upload progress). */
export function uploadFiles(
  batchId: string,
  files: File[],
  onProgress: (fraction: number) => void,
): Promise<Batch> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const f of files) form.append("files", f, f.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", apiUrl(`/batches/${batchId}/documents`));
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        // ignore
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as Batch);
      else {
        const err = (body as { error?: { code: string; message: string } })?.error;
        reject(new ApiError(xhr.status, err?.code ?? "http_error", err?.message ?? "Upload failed."));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "Upload failed. Check your connection."));
    xhr.send(form);
  });
}

/** Download an export as a file, surfacing API errors instead of navigating to them. */
export async function downloadExport(
  batchId: string,
  format: ExportFormat,
  scope: "approved" | "all",
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(apiUrl(`/batches/${batchId}/export?format=${format}&scope=${scope}`));
  } catch {
    throw new ApiError(0, "network", "Can't reach the server.");
  }
  if (!res.ok) throw await parseError(res);
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? `paperwork.${format}`;
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
