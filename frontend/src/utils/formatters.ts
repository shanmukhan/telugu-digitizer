import type { BookOCRRunSummary, BookSummary, OCRRunStatus } from "../types/api";

export function formatEngineLabel(engine: string | null | undefined): string {
  switch ((engine ?? "").toLowerCase()) {
    case "paddleocr":
    case "paddle_ppocrv5_te":
      return "PaddleOCR PP-OCRv5";
    case "tesseract":
    case "tesseract_tel_best":
      return "Tesseract 5 Telugu";
    default:
      return engine || "OCR Engine";
  }
}

export function formatPageKind(kind: string): string {
  switch (kind) {
    case "scanned_image":
      return "Scanned";
    case "digital_text":
      return "Digital Text";
    case "mixed":
      return "Mixed";
    default:
      return kind.replace(/_/g, " ");
  }
}

export function formatReviewStatus(status: string): string {
  switch (status) {
    case "not_started":
      return "Pending Review";
    case "in_review":
      return "In Review";
    case "approved":
      return "Approved";
    case "needs_attention":
      return "Needs Attention";
    default:
      return status.replace(/_/g, " ");
  }
}

export function formatLayoutMode(mode: string): string {
  switch (mode) {
    case "page_preserving":
      return "Page-Preserving";
    case "editable_flow":
      return "Editable Flow";
    case "raw_ocr":
      return "Raw OCR";
    case "human_approved":
      return "Human-Reviewed";
    default:
      return mode.replace(/_/g, " ");
  }
}

export function formatDuration(totalSeconds: number): string {
  const secs = Math.max(0, Math.floor(totalSeconds));
  if (secs < 60) {
    return `${secs}s`;
  }
  const mins = Math.floor(secs / 60);
  const remSecs = secs % 60;
  if (mins < 60) {
    return `${mins}m ${String(remSecs).padStart(2, "0")}s`;
  }
  const hours = Math.floor(mins / 60);
  const remMins = mins % 60;
  return `${hours}h ${String(remMins).padStart(2, "0")}m`;
}

export interface RunTelemetry {
  ocrRunId: string;
  engineLabel: string;
  status: string;
  completed: number;
  total: number;
  pending: number;
  percent: number;
  elapsedSec: number | null;
  secPerPage: number | null;
  etaSec: number | null;
  pageRangeLabel: string | null;
}

function parseRangeLabel(config: Record<string, unknown> | undefined): string | null {
  if (!config) return null;
  const start = config.start_page;
  const end = config.end_page;
  if (typeof start === "number" && typeof end === "number") {
    return start === end ? `Page ${start}` : `Pages ${start}–${end}`;
  }
  return null;
}

export function buildRunTelemetry(
  run: BookOCRRunSummary | OCRRunStatus,
  book: BookSummary | null,
  nowMs: number,
): RunTelemetry {
  const cfg = run.config ?? {};
  const fallbackTotal =
    typeof cfg.start_page === "number" && typeof cfg.end_page === "number"
      ? Math.max(0, cfg.end_page - cfg.start_page + 1)
      : (book?.scanned_pages_count ?? 0) + (book?.mixed_pages_count ?? 0);

  const rawTotal = run.progress_total ?? 0;
  const total = rawTotal > 0 ? rawTotal : fallbackTotal;
  const completed = Math.min(Math.max(0, run.progress_current ?? 0), total || Number.MAX_SAFE_INTEGER);
  const pending = Math.max(0, total - completed);
  const percent = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;

  let elapsedSec: number | null = null;
  if (run.started_at) {
    const startMs = Date.parse(run.started_at);
    const endMs = run.completed_at ? Date.parse(run.completed_at) : nowMs;
    if (!Number.isNaN(startMs) && !Number.isNaN(endMs)) {
      elapsedSec = Math.max(0, Math.floor((endMs - startMs) / 1000));
    }
  }

  let secPerPage: number | null = null;
  let etaSec: number | null = null;
  if (completed > 0 && elapsedSec !== null && elapsedSec > 0) {
    secPerPage = elapsedSec / completed;
    if (pending > 0 && (run.status === "running" || run.status === "queued")) {
      etaSec = Math.round(secPerPage * pending);
    }
  }

  return {
    ocrRunId: run.ocr_run_id,
    engineLabel: formatEngineLabel(run.engine),
    status: run.status,
    completed,
    total,
    pending,
    percent,
    elapsedSec,
    secPerPage,
    etaSec,
    pageRangeLabel: parseRangeLabel(cfg),
  };
}
