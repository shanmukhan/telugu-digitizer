import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HeaderOcrStatusPill, OcrProgressStrip } from "./OcrStatusBar";
import type { BookOCRRunSummary, BookSummary, PageSummary } from "../types/api";

const SAMPLE_BOOK: BookSummary = {
  book_id: "00000000-0000-0000-0000-000000000001",
  title: "యువ సంపుటి",
  author: null,
  publisher: null,
  publication_year: null,
  language_code: "te",
  orthography_profile: "unspecified",
  original_filename: "book.pdf",
  source_sha256: "abc",
  page_count: 20,
  rights_status: "unknown",
  training_consent: false,
  created_at: "2026-11-24T00:00:00Z",
  updated_at: "2026-11-24T00:00:00Z",
  scanned_pages_count: 20,
  digital_text_pages_count: 0,
  mixed_pages_count: 0,
};

const SAMPLE_PAGES: PageSummary[] = [
  {
    page_id: "p1",
    page_number: 1,
    page_kind: "scanned_image",
    width_px: 1200,
    height_px: 1800,
    render_dpi: 300,
    extracted_text_char_count: 0,
    image_coverage_ratio: 1,
    review_status: "approved",
    has_image: true,
  },
];

describe("HeaderOcrStatusPill & OcrProgressStrip", () => {
  it("shows live progress bar, completed vs pending counts, ETA, and queued engines", () => {
    const startedIso = new Date(Date.now() - 50_000).toISOString();
    const runs: BookOCRRunSummary[] = [
      {
        ocr_run_id: "run-1",
        engine: "paddleocr",
        model_id: "PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec",
        status: "running",
        progress_current: 5,
        progress_total: 20,
        started_at: startedIso,
        config: { start_page: 1, end_page: 20 },
        created_at: startedIso,
        completed_at: null,
      },
      {
        ocr_run_id: "run-2",
        engine: "tesseract",
        model_id: "tesseract-5-tel-best",
        status: "queued",
        progress_current: 0,
        progress_total: 20,
        started_at: null,
        config: { start_page: 1, end_page: 20 },
        created_at: startedIso,
        completed_at: null,
      },
    ];

    render(
      <>
        <HeaderOcrStatusPill book={SAMPLE_BOOK} runs={runs} />
        <OcrProgressStrip
          book={SAMPLE_BOOK}
          runs={runs}
          pages={SAMPLE_PAGES}
          activeView="review"
          onQuickStartSample={vi.fn().mockResolvedValue(undefined)}
          onQuickStartFull={vi.fn().mockResolvedValue(undefined)}
          onResumeRun={vi.fn().mockResolvedValue(undefined)}
          onGoToExport={vi.fn()}
          onGoToReview={vi.fn()}
        />
      </>,
    );

    expect(screen.getByText(/OCR In Progress · 5\/20 \(25%\)/)).toBeInTheDocument();
    expect(screen.getByText("OCR In Progress")).toBeInTheDocument();
    const progressEl = screen.getByRole("progressbar") as HTMLProgressElement;
    expect(progressEl.max).toBe(20);
    expect(progressEl.value).toBe(5);
    expect(screen.getByText(/completed/)).toBeInTheDocument();
    expect(screen.getByText(/pending/)).toBeInTheDocument();
    expect(screen.getByText(/Est\. left/)).toBeInTheDocument();
    expect(screen.getByText(/Tesseract 5 Telugu/)).toBeInTheDocument();
  });

  it("shows quick OCR starter buttons when a scanned book has no runs", () => {
    const onSample = vi.fn().mockResolvedValue(undefined);
    const onFull = vi.fn().mockResolvedValue(undefined);

    render(
      <>
        <HeaderOcrStatusPill book={SAMPLE_BOOK} runs={[]} />
        <OcrProgressStrip
          book={SAMPLE_BOOK}
          runs={[]}
          pages={SAMPLE_PAGES}
          activeView="review"
          onQuickStartSample={onSample}
          onQuickStartFull={onFull}
          onResumeRun={vi.fn().mockResolvedValue(undefined)}
          onGoToExport={vi.fn()}
          onGoToReview={vi.fn()}
        />
      </>,
    );

    expect(screen.getByText("Needs OCR")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Test Pages 1–5" }));
    expect(onSample).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Run Full Book OCR" }));
    expect(onFull).toHaveBeenCalledTimes(1);
  });

  it("shows Ready state and direct export trigger when OCR is completed", () => {
    const onGoToExport = vi.fn();
    const runs: BookOCRRunSummary[] = [
      {
        ocr_run_id: "run-1",
        engine: "tesseract",
        model_id: "tesseract-5-tel-best",
        status: "completed",
        progress_current: 20,
        progress_total: 20,
        started_at: "2026-11-24T00:00:00Z",
        config: {},
        created_at: "2026-11-24T00:00:00Z",
        completed_at: "2026-11-24T00:00:10Z",
      },
    ];

    render(
      <>
        <HeaderOcrStatusPill book={SAMPLE_BOOK} runs={runs} />
        <OcrProgressStrip
          book={SAMPLE_BOOK}
          runs={runs}
          pages={SAMPLE_PAGES}
          activeView="review"
          onQuickStartSample={vi.fn().mockResolvedValue(undefined)}
          onQuickStartFull={vi.fn().mockResolvedValue(undefined)}
          onResumeRun={vi.fn().mockResolvedValue(undefined)}
          onGoToExport={onGoToExport}
          onGoToReview={vi.fn()}
        />
      </>,
    );

    expect(screen.getByText("OCR Ready")).toBeInTheDocument();
    expect(screen.getByText("✓ Ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Export DOCX / TXT" }));
    expect(onGoToExport).toHaveBeenCalledTimes(1);
  });

  it("surfaces a direct Continue Remaining Pages strip after a 1–5 page sample run even when hideWhenReady is true", () => {
    const onContinue = vi.fn().mockResolvedValue(undefined);
    const onOpenDrawer = vi.fn();
    const runs: BookOCRRunSummary[] = [
      {
        ocr_run_id: "run-sample",
        engine: "paddleocr",
        model_id: "PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec",
        status: "completed",
        progress_current: 5,
        progress_total: 5,
        started_at: "2026-11-24T00:00:00Z",
        config: { start_page: 1, end_page: 5 },
        created_at: "2026-11-24T00:00:00Z",
        completed_at: "2026-11-24T00:01:00Z",
      },
    ];

    render(
      <>
        <HeaderOcrStatusPill book={SAMPLE_BOOK} runs={runs} />
        <OcrProgressStrip
          book={SAMPLE_BOOK}
          runs={runs}
          pages={SAMPLE_PAGES}
          activeView="review"
          hideWhenReady
          onQuickStartSample={vi.fn().mockResolvedValue(undefined)}
          onQuickStartFull={vi.fn().mockResolvedValue(undefined)}
          onContinueRemaining={onContinue}
          onOpenOcrDrawer={onOpenDrawer}
          onResumeRun={vi.fn().mockResolvedValue(undefined)}
          onGoToExport={vi.fn()}
          onGoToReview={vi.fn()}
        />
      </>,
    );

    expect(screen.getByText(/OCR 5\/20 Pages · Continue/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Continue Remaining \(Pages 6–20\)/i }));
    expect(onContinue).toHaveBeenCalledWith(6, 20, false);

    fireEvent.click(screen.getByRole("button", { name: /Fast Draft \(6–20\)/i }));
    expect(onContinue).toHaveBeenCalledWith(6, 20, true);

    fireEvent.click(screen.getByRole("button", { name: /OCR Options/i }));
    expect(onOpenDrawer).toHaveBeenCalledTimes(1);
  });
});
