import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { BookCalibrationStatus, BookSummary, CorrectionMemoryRecord } from "../types/api";
import { CalibrationSetupPanel } from "./CalibrationSetupPanel";
import { CorrectionMemoryPanel } from "./CorrectionMemoryPanel";
import { OcrProgressStrip } from "./OcrStatusBar";
import { SwitchBookDialog } from "./SwitchBookDialog";
import { TopNavBar } from "./TopNavBar";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    listCorrectionsWithMeta: vi.fn(),
    updateCorrectionStatus: vi.fn(),
    updateCorrectionEntry: vi.fn(),
    deleteCorrectionEntry: vi.fn(),
  };
});

import * as apiClient from "../api/client";

function makeBook(overrides: Partial<BookSummary> = {}): BookSummary {
  return {
    book_id: "book-1",
    title: "ఆముక్తమాల్యద",
    author: "శ్రీకృష్ణదేవరాయలు",
    publisher: null,
    publication_year: null,
    language_code: "te",
    orthography_profile: "classical_literary",
    original_filename: "amuktamalyada.pdf",
    source_sha256: "abc123",
    page_count: 250,
    rights_status: "unknown",
    training_consent: false,
    processing_state: "uploaded",
    approved_pages_count: 0,
    created_at: "2026-11-28T00:00:00Z",
    updated_at: "2026-11-28T00:00:00Z",
    scanned_pages_count: 250,
    digital_text_pages_count: 0,
    mixed_pages_count: 0,
    ...overrides,
  };
}

describe("OCR Calibration Settings with PDF Starting Page", () => {
  it("supports selecting PDF starting page and calibration count independently with preview and validation", async () => {
    const onStartCalibration = vi.fn().mockResolvedValue(undefined);
    render(
      <CalibrationSetupPanel
        book={makeBook({ page_count: 250 })}
        onStartCalibration={onStartCalibration}
      />,
    );

    expect(screen.getByText("OCR Calibration Settings")).toBeInTheDocument();
    expect(screen.getByText("Total PDF pages: 250")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Select the PDF page where the actual book text begins. This may differ from the printed page number.",
      ),
    ).toBeInTheDocument();

    const startInput = screen.getByLabelText("PDF Starting Page") as HTMLInputElement;
    fireEvent.change(startInput, { target: { value: "12" } });
    fireEvent.blur(startInput);

    // Click calibration count preset "8"
    fireEvent.click(screen.getByRole("button", { name: "8" }));

    expect(screen.getByText(/Pages selected for calibration: PDF 12–19 \(8 pages\)/i)).toBeInTheDocument();
    expect(screen.getByText(/Remaining after calibration: PDF 20–250 \(231 pages\)/i)).toBeInTheDocument();
    expect(screen.getByText(/PDF pages 1–11 untouched/i)).toBeInTheDocument();

    // Preview image points to PDF page 12 (resolveAppUrl uses subpath-safe relative URL)
    const previewImg = screen.getByAltText(/Preview of PDF page 12/i) as HTMLImageElement;
    expect(previewImg.getAttribute("src")).toContain("api/v1/books/book-1/pages/12/image");

    fireEvent.click(screen.getByRole("button", { name: /Start Calibration OCR \(PDF Pages 12–19\)/i }));
    await waitFor(() => {
      expect(onStartCalibration).toHaveBeenCalledWith({
        startPage: 12,
        calibrationPageCount: 8,
        endPage: 250,
      });
    });

    // Validation: starting page exceeding book page count shows accessible error
    fireEvent.change(startInput, { target: { value: "300" } });
    fireEvent.blur(startInput);
    expect(startInput).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("alert")).toHaveTextContent(/between 1 and 250/i);
  });

  it("shows Apply Calibration & Process Remaining banner during calibration review", async () => {
    const onProcessRemaining = vi.fn().mockResolvedValue(undefined);
    const calibration: BookCalibrationStatus = {
      book_id: "book-1",
      page_count: 250,
      processing_state: "calibration_review",
      calibration_start_page: 12,
      calibration_page_count: 8,
      calibration_range_end: 19,
      book_end_page: 250,
      skipped_front_pages_count: 11,
      remaining_start_page: 20,
      remaining_end_page: 250,
      remaining_pages_count: 231,
      calibration_pages_ocred: 8,
      calibration_pages_approved: 8,
      calibration_completed_at: null,
      learned_word_rules_count: 14,
      learned_char_patterns: [{ from_seq: "బ", to_seq: "భ", occurrences: 3, examples: ["బాగం → భాగం"] }],
      conflicting_rules_count: 0,
      auto_applied_blocks_count: 0,
    };

    render(
      <OcrProgressStrip
        book={makeBook({ calibration_start_page: 12, calibration_page_count: 8 })}
        runs={[
          {
            ocr_run_id: "run-1",
            engine: "paddleocr",
            model_id: "PP-OCRv5",
            status: "completed",
            progress_current: 8,
            progress_total: 8,
            config: { start_page: 12, end_page: 19, run_phase: "calibration" },
            created_at: "2026-11-28T00:00:00Z",
            completed_at: "2026-11-28T00:05:00Z",
          },
        ]}
        pages={[]}
        calibration={calibration}
        activeView="review"
        onQuickStartSample={vi.fn()}
        onQuickStartFull={vi.fn()}
        onProcessRemainingWithCalibration={onProcessRemaining}
        onResumeRun={vi.fn()}
        onGoToExport={vi.fn()}
        onGoToReview={vi.fn()}
      />,
    );

    expect(screen.getByText(/Calibration PDF 12–19/i)).toBeInTheDocument();
    expect(screen.getByText(/14 learned word correction/i)).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /Apply Calibration & Process Remaining \(PDF 20–250\)/i }),
    );
    expect(onProcessRemaining).toHaveBeenCalledWith(false);
  });
});

describe("Improved Correction Memory UI", () => {
  it("displays scope badges, conflict warnings, reliability score, and supports editing", async () => {
    const mockRecords: CorrectionMemoryRecord[] = [
      {
        correction_id: "cm-1",
        language_code: "te",
        incorrect_text: "పబ్లీషన్",
        normalized_incorrect: "పబ్లీషన్",
        corrected_text: "పబ్లికేషన్స్",
        left_context: "మలయకూట",
        right_context: "హైదరాబాదు",
        correction_type: "ocr_substitution",
        unit_type: "word",
        scope: "book_only",
        book_id: "book-1",
        source_book_title: "ఆముక్తమాల్యద",
        source_ocr_block_id: "blk-1",
        source_page_number: 12,
        status: "active",
        approved_count: 3,
        rejected_count: 0,
        reliability_score: 0.86,
        has_conflict: true,
        conflict_count: 2,
        last_used_at: "2026-11-28T10:00:00Z",
        created_at: "2026-11-28T09:00:00Z",
        updated_at: "2026-11-28T10:00:00Z",
      },
    ];
    vi.mocked(apiClient.listCorrectionsWithMeta).mockResolvedValue({
      items: mockRecords,
      total_count: 1,
      global_count: 4,
      book_specific_count: 1,
      conflicts_count: 1,
    });
    vi.mocked(apiClient.updateCorrectionEntry).mockResolvedValue({
      ...mockRecords[0],
      corrected_text: "పబ్లికేషన్",
    });

    const onStatusBanner = vi.fn();
    render(<CorrectionMemoryPanel selectedBookId="book-1" onStatusBanner={onStatusBanner} />);

    await waitFor(() => {
      expect(screen.getByText("పబ్లీషన్")).toBeInTheDocument();
    });
    expect(screen.getByText("పబ్లికేషన్స్")).toBeInTheDocument();
    expect(screen.getByText(/Global: 4/i)).toBeInTheDocument();
    expect(screen.getByText(/Book-Specific: 1/i)).toBeInTheDocument();
    expect(screen.getByText(/⚠ Conflict \(2\)/i)).toBeInTheDocument();
    expect(screen.getByText(/86%/)).toBeInTheDocument();
    expect(screen.getByText(/p\.12/i)).toBeInTheDocument();

    // Open inline editor and save updated text
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const editInput = screen.getByDisplayValue("పబ్లికేషన్స్");
    fireEvent.change(editInput, { target: { value: "పబ్లికేషన్" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(apiClient.updateCorrectionEntry).toHaveBeenCalledWith(
        "cm-1",
        expect.objectContaining({ corrected_text: "పబ్లికేషన్" }),
      );
    });
  });
});

describe("Book Switching UX & Confirmation Dialog", () => {
  it("renders a visible Switch Book action in TopNavBar", () => {
    const onOpenSwitchBook = vi.fn();
    render(
      <TopNavBar
        books={[makeBook()]}
        selectedBook={makeBook()}
        runs={[]}
        activeView="review"
        keyboardOpen={false}
        onSelectBook={vi.fn()}
        onSelectView={vi.fn()}
        onOpenImport={vi.fn()}
        onOpenSwitchBook={onOpenSwitchBook}
        onOpenOcrDrawer={vi.fn()}
        onToggleKeyboard={vi.fn()}
        onOpenShortcuts={vi.fn()}
      />,
    );

    const switchBtn = screen.getByRole("button", { name: /Switch Book/i });
    expect(switchBtn).toBeInTheDocument();
    fireEvent.click(switchBtn);
    expect(onOpenSwitchBook).toHaveBeenCalledTimes(1);
  });

  it("warns about unfinished work, explains non-destructive pause, and saves drafts when requested", async () => {
    const onKeepWorking = vi.fn();
    const onConfirmSwitch = vi.fn().mockResolvedValue(undefined);
    const book1 = makeBook({ book_id: "book-1", title: "Book One", page_count: 100 });
    const book2 = makeBook({
      book_id: "book-2",
      title: "Book Two",
      page_count: 80,
      processing_state: "paused",
      approved_pages_count: 10,
    });

    render(
      <SwitchBookDialog
        open
        currentBook={book1}
        books={[book1, book2]}
        pendingTargetBookId="book-2"
        pendingOpenImport={false}
        dirtyBlockCount={3}
        isOcrRunning={true}
        approvedPagesCount={5}
        onKeepWorking={onKeepWorking}
        onConfirmSwitch={onConfirmSwitch}
      />,
    );

    expect(screen.getByText(/3 unsaved line edit\(s\) on the current page/i)).toBeInTheDocument();
    expect(screen.getByText(/an OCR run is currently processing/i)).toBeInTheDocument();
    expect(screen.getByText(/Your work will NOT be deleted/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Save Drafts & Switch Book/i }));
    await waitFor(() => {
      expect(onConfirmSwitch).toHaveBeenCalledWith({
        targetBookId: "book-2",
        openImport: false,
        saveCurrentPageDrafts: true,
      });
    });
  });
});
