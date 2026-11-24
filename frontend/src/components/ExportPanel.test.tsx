import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ExportPanel } from "./ExportPanel";
import type { BookSummary } from "../types/api";
import * as client from "../api/client";

const SAMPLE_BOOK: BookSummary = {
  book_id: "00000000-0000-0000-0000-000000000001",
  title: "తెలుగు పుస్తకం",
  author: "Author",
  publisher: null,
  publication_year: null,
  language_code: "te",
  orthography_profile: "unspecified",
  original_filename: "book.pdf",
  source_sha256: "abc",
  page_count: 2,
  rights_status: "unknown",
  training_consent: false,
  created_at: "2026-11-24T00:00:00Z",
  updated_at: "2026-11-24T00:00:00Z",
  scanned_pages_count: 2,
  digital_text_pages_count: 0,
  mixed_pages_count: 0,
};

describe("ExportPanel", () => {
  it("blocks export and shows guidance when no completed OCR run exists for a scanned book", async () => {
    vi.spyOn(client, "listBookExports").mockResolvedValue([]);
    const onStatusBanner = vi.fn();
    const onGoToReview = vi.fn();
    try {
      render(
        <ExportPanel
          book={SAMPLE_BOOK}
          runs={[]}
          onStatusBanner={onStatusBanner}
          onGoToReview={onGoToReview}
        />,
      );

      expect(await screen.findByText(/No completed OCR run exists for this book yet/i)).toBeTruthy();
      expect(screen.getByRole("button", { name: "Generate & Download Export" })).toBeDisabled();

      fireEvent.click(screen.getByRole("button", { name: "Go to Page Review & Run OCR" }));
      expect(onGoToReview).toHaveBeenCalledTimes(1);
    } finally {
      vi.restoreAllMocks();
    }
  });

  it("submits DOCX export options and displays validated download links", async () => {
    vi.spyOn(client, "listBookExports").mockResolvedValue([]);
    const createSpy = vi.spyOn(client, "createBookExport").mockResolvedValue({
      export_id: "exp-1",
      book_id: SAMPLE_BOOK.book_id,
      transcript_version_id: null,
      format: "docx",
      layout_mode: "page_preserving",
      text_version: "human_approved",
      font_family: "Noto Serif Telugu",
      filename: "book_page-preserving.docx",
      status: "completed",
      is_fully_reviewed: true,
      validation: { passed: true },
      download_url: "/api/v1/exports/exp-1/download",
      manifest_url: "/api/v1/exports/exp-1/manifest",
      created_at: "2026-11-24T00:00:00Z",
    });

    const onStatusBanner = vi.fn();
    render(
      <ExportPanel
        book={SAMPLE_BOOK}
        runs={[
          {
            ocr_run_id: "run-1",
            engine: "tesseract_tel_best",
            model_id: "tesseract-5-tel-best",
            status: "completed",
            config: {},
            created_at: "2026-11-24T00:00:00Z",
            completed_at: "2026-11-24T00:01:00Z",
          },
        ]}
        onStatusBanner={onStatusBanner}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Generate & Download Export" }));

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledTimes(1);
      expect(onStatusBanner).toHaveBeenCalledWith(
        "success",
        "Export ready: book_page-preserving.docx",
      );
    });
  });
});
