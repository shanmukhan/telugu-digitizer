import type {
  ApiErrorDetail,
  BlockEditResult,
  BlockRole,
  BookOCRRunSummary,
  BookSummary,
  BookUploadResult,
  CorrectionMemoryRecord,
  ExportCreatePayload,
  ExportRecord,
  HostCapabilities,
  ManualBlockCreateResult,
  OCRRunCreateResult,
  OCRRunStatus,
  PageReviewPayload,
  PageSummary,
} from "../types/api";

export class ApiClientError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message);
    this.status = status;
    this.code = detail.code;
    this.details = detail.details;
  }
}

export function resolveAppUrl(path: string): string {
  if (!path || /^(https?:|blob:|data:)/i.test(path)) {
    return path;
  }
  return path.startsWith("/") ? path.slice(1) : path;
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(resolveAppUrl(url), init);
  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = null;
    }
  }
  if (!response.ok) {
    const errObj =
      parsed && typeof parsed === "object" && "error" in parsed
        ? (parsed as { error: ApiErrorDetail }).error
        : { code: "HTTP_ERROR", message: text || response.statusText, details: {} };
    throw new ApiClientError(response.status, errObj);
  }
  return parsed as T;
}

export async function getHostCapabilities(): Promise<HostCapabilities> {
  return requestJson<HostCapabilities>("/api/v1/capabilities");
}

export async function listBooks(): Promise<BookSummary[]> {
  const data = await requestJson<{ items: BookSummary[] }>("/api/v1/books");
  return data.items;
}

export async function uploadBook(formData: FormData): Promise<BookUploadResult> {
  return requestJson<BookUploadResult>("/api/v1/books", {
    method: "POST",
    body: formData,
  });
}

export async function deleteBook(bookId: string): Promise<void> {
  await requestJson<void>(`/api/v1/books/${bookId}`, { method: "DELETE" });
}

export async function listBookPages(bookId: string): Promise<PageSummary[]> {
  const data = await requestJson<{ items: PageSummary[] }>(`/api/v1/books/${bookId}/pages`);
  return data.items;
}

export async function listBookOcrRuns(bookId: string): Promise<BookOCRRunSummary[]> {
  const data = await requestJson<{ items: BookOCRRunSummary[] }>(`/api/v1/books/${bookId}/ocr-runs`);
  return data.items;
}

export async function startOcrRun(
  bookId: string,
  engines: string[],
  options?: {
    forceRerun?: boolean;
    pageRange?: { start: number; end: number } | null;
    renderDpi?: number;
    preprocessingProfile?: "none" | "deskew" | "contrast_clahe";
    tesseractPsm?: number;
    includeDigitalTextPages?: boolean;
  },
): Promise<OCRRunCreateResult> {
  const body: Record<string, unknown> = {
    engines,
    page_range: options?.pageRange ?? null,
    render_dpi: options?.renderDpi ?? 300,
    preprocessing_profile: options?.preprocessingProfile ?? "none",
    force_rerun: options?.forceRerun ?? false,
  };
  if (options?.tesseractPsm !== undefined) {
    body.tesseract_psm = options.tesseractPsm;
  }
  if (options?.includeDigitalTextPages !== undefined) {
    body.include_digital_text_pages = options.includeDigitalTextPages;
  }
  return requestJson<OCRRunCreateResult>(`/api/v1/books/${bookId}/ocr-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function getOcrRunStatus(runId: string): Promise<OCRRunStatus> {
  return requestJson<OCRRunStatus>(`/api/v1/ocr-runs/${runId}`);
}

export async function resumeOcrRun(runId: string): Promise<OCRRunStatus> {
  return requestJson<OCRRunStatus>(`/api/v1/ocr-runs/${runId}/resume`, { method: "POST" });
}

export async function cancelOcrRun(runId: string): Promise<OCRRunStatus> {
  return requestJson<OCRRunStatus>(`/api/v1/ocr-runs/${runId}/cancel`, { method: "POST" });
}

export async function getPageReview(
  bookId: string,
  pageNumber: number,
  primaryRunId?: string | null,
): Promise<PageReviewPayload> {
  const params = new URLSearchParams();
  if (primaryRunId) {
    params.set("primary_run_id", primaryRunId);
  }
  const qs = params.toString();
  const suffix = qs ? `?${qs}` : "";
  return requestJson<PageReviewPayload>(
    `/api/v1/books/${bookId}/pages/${pageNumber}/review${suffix}`,
  );
}

export async function submitBlockEdit(
  blockId: string,
  payload: {
    edited_text: string;
    action: "corrected" | "approved" | "reverted" | "ignored";
    block_role?: BlockRole;
    review_note?: string;
    add_to_correction_memory?: boolean;
    memory_scope?: "book_only" | "global_suggestion";
    correction_type?: string;
  },
): Promise<BlockEditResult> {
  return requestJson<BlockEditResult>(`/api/v1/ocr-blocks/${blockId}/edits`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function listCorrections(params?: {
  bookId?: string | null;
  statusFilter?: string;
  query?: string;
}): Promise<CorrectionMemoryRecord[]> {
  const qs = new URLSearchParams();
  if (params?.bookId) qs.set("book_id", params.bookId);
  if (params?.statusFilter && params.statusFilter !== "all") {
    qs.set("status_filter", params.statusFilter);
  }
  if (params?.query) qs.set("q", params.query);
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const data = await requestJson<{ items: CorrectionMemoryRecord[] }>(
    `/api/v1/corrections${suffix}`,
  );
  return data.items;
}

export async function approveCorrection(correctionId: string): Promise<CorrectionMemoryRecord> {
  return requestJson<CorrectionMemoryRecord>(`/api/v1/corrections/${correctionId}/approve`, {
    method: "POST",
  });
}

export async function rejectCorrection(
  correctionId: string,
  disable = false,
): Promise<CorrectionMemoryRecord> {
  return requestJson<CorrectionMemoryRecord>(`/api/v1/corrections/${correctionId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ disable }),
  });
}

export async function updateCorrectionStatus(
  correctionId: string,
  status: "active" | "disabled" | "superseded" | "rejected",
  scope?: "book_only" | "global_suggestion",
): Promise<CorrectionMemoryRecord> {
  return requestJson<CorrectionMemoryRecord>(`/api/v1/corrections/${correctionId}/status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(scope ? { status, scope } : { status }),
  });
}

export async function createManualPageBlock(
  bookId: string,
  pageNumber: number,
  payload: {
    text: string;
    block_role?: BlockRole;
    primary_run_id?: string | null;
    bbox?: number[] | null;
  },
): Promise<ManualBlockCreateResult> {
  return requestJson<ManualBlockCreateResult>(`/api/v1/books/${bookId}/pages/${pageNumber}/blocks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updatePageDigitalText(
  bookId: string,
  pageNumber: number,
  digitalTextContent: string,
): Promise<{ book_id: string; page_number: number; digital_text_content: string; review_status: string }> {
  return requestJson(`/api/v1/books/${bookId}/pages/${pageNumber}/digital-text`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ digital_text_content: digitalTextContent }),
  });
}

export async function createBookExport(
  bookId: string,
  payload: ExportCreatePayload,
): Promise<ExportRecord> {
  return requestJson<ExportRecord>(`/api/v1/books/${bookId}/exports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function listBookExports(bookId: string): Promise<ExportRecord[]> {
  const data = await requestJson<{ items: ExportRecord[] }>(`/api/v1/books/${bookId}/exports`);
  return data.items;
}

export async function updatePageReviewStatus(
  bookId: string,
  pageNumber: number,
  reviewStatus: "not_started" | "in_review" | "approved" | "needs_attention",
  primaryRunId?: string | null,
): Promise<{ book_id: string; page_number: number; review_status: string }> {
  return requestJson(`/api/v1/books/${bookId}/pages/${pageNumber}/review-status`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      review_status: reviewStatus,
      primary_run_id: primaryRunId || null,
    }),
  });
}
