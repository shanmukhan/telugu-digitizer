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

export function formatCorrectionScope(scope: string): string {
  switch (scope) {
    case "book_only":
      return "This Book";
    case "global_suggestion":
      return "Global";
    default:
      return scope.replace(/_/g, " ");
  }
}

export function formatCorrectionType(cType: string | null | undefined): string {
  if (!cType) return "";
  switch (cType) {
    case "glyph_confusion":
      return "Glyph Confusion";
    case "vowel_sign":
      return "Vowel Sign (గుణింతం)";
    case "conjunct_or_virama":
      return "Conjunct / Virama";
    case "word_boundary":
      return "Word Boundary";
    case "punctuation":
      return "Punctuation";
    case "numeral":
      return "Numeral";
    case "ocr_substitution":
      return "OCR Substitution";
    default:
      return cType.replace(/_/g, " ");
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

export interface BookOcrCoverage {
  totalPages: number;
  totalScanned: number;
  coveredPagesCount: number;
  remainingPagesCount: number;
  hasAnyOcr: boolean;
  isFullyCovered: boolean;
  isPartialCoverage: boolean;
  coveredRangeLabel: string | null;
  nextStartPage: number;
  nextEndPage: number;
  isPageCovered: (pageNumber: number) => boolean;
}

/**
 * Computes exact page-range OCR coverage across all completed/partial runs for a book.
 * Distinguishes sample runs (e.g., Pages 1–5 of 406) from full-book completion so the UI
 * can surface direct "Continue Remaining Pages (6–406)" prompts instead of "OCR Ready".
 */
export function computeBookOcrCoverage(
  book: BookSummary,
  runs: BookOCRRunSummary[],
): BookOcrCoverage {
  const totalPages = Math.max(0, book.page_count);
  const totalScanned = Math.max(0, book.scanned_pages_count + book.mixed_pages_count);

  if (totalPages === 0 || totalScanned === 0) {
    return {
      totalPages,
      totalScanned,
      coveredPagesCount: totalPages,
      remainingPagesCount: 0,
      hasAnyOcr: true,
      isFullyCovered: true,
      isPartialCoverage: false,
      coveredRangeLabel: totalPages > 0 ? `1–${totalPages}` : null,
      nextStartPage: 1,
      nextEndPage: Math.max(1, totalPages),
      isPageCovered: () => true,
    };
  }

  const intervals: Array<[number, number]> = [];
  for (const run of runs) {
    if (run.status !== "completed" && run.status !== "partial") continue;
    const progress = run.progress_current ?? 0;
    if (run.status === "partial" && progress <= 0) continue;

    const cfg = run.config ?? {};
    const cfgStart = typeof cfg.start_page === "number" ? Math.max(1, Math.floor(cfg.start_page)) : null;
    const cfgEnd =
      typeof cfg.end_page === "number" ? Math.min(totalPages, Math.floor(cfg.end_page)) : null;

    if (cfgStart !== null && cfgEnd !== null && cfgEnd >= cfgStart) {
      if (run.status === "completed") {
        intervals.push([cfgStart, cfgEnd]);
      } else {
        const partialEnd = Math.min(cfgEnd, cfgStart + Math.max(0, progress - 1));
        if (partialEnd >= cfgStart) {
          intervals.push([cfgStart, partialEnd]);
        }
      }
    } else if (run.status === "completed") {
      const total = run.progress_total ?? 0;
      if (total === 0 || total >= totalScanned || progress >= totalScanned) {
        intervals.push([1, totalPages]);
      } else if (progress > 0) {
        intervals.push([1, Math.min(totalPages, progress)]);
      } else {
        intervals.push([1, totalPages]);
      }
    } else if (progress > 0) {
      intervals.push([1, Math.min(totalPages, progress)]);
    }
  }

  if (intervals.length === 0) {
    return {
      totalPages,
      totalScanned,
      coveredPagesCount: 0,
      remainingPagesCount: totalScanned,
      hasAnyOcr: false,
      isFullyCovered: false,
      isPartialCoverage: false,
      coveredRangeLabel: null,
      nextStartPage: 1,
      nextEndPage: totalPages,
      isPageCovered: () => false,
    };
  }

  intervals.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged: Array<[number, number]> = [];
  for (const [s, e] of intervals) {
    const last = merged[merged.length - 1];
    if (last && s <= last[1] + 1) {
      last[1] = Math.max(last[1], e);
    } else {
      merged.push([s, e]);
    }
  }

  let coveredPagesCount = 0;
  for (const [s, e] of merged) {
    coveredPagesCount += e - s + 1;
  }
  coveredPagesCount = Math.min(totalPages, coveredPagesCount);

  // Locate first uncovered page (e.g., 6 after Pages 1–5)
  let nextStartPage = 1;
  for (const [s, e] of merged) {
    if (nextStartPage < s) {
      break;
    }
    if (nextStartPage >= s && nextStartPage <= e) {
      nextStartPage = e + 1;
    }
  }

  const isFullyCovered = nextStartPage > totalPages || coveredPagesCount >= totalPages;
  const remainingPagesCount = isFullyCovered ? 0 : Math.max(1, totalPages - coveredPagesCount);
  const clampedStart = isFullyCovered ? 1 : Math.min(totalPages, nextStartPage);
  const coveredRangeLabel = merged
    .map(([s, e]) => (s === e ? `${s}` : `${s}–${e}`))
    .join(", ");

  return {
    totalPages,
    totalScanned,
    coveredPagesCount,
    remainingPagesCount,
    hasAnyOcr: true,
    isFullyCovered,
    isPartialCoverage: !isFullyCovered,
    coveredRangeLabel,
    nextStartPage: clampedStart,
    nextEndPage: totalPages,
    isPageCovered: (pageNumber: number) =>
      merged.some(([s, e]) => pageNumber >= s && pageNumber <= e),
  };
}
