import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  CommitmentBar,
  OverviewPanel,
  WelcomeHero,
  deriveWorkflowSteps,
} from "./StudioChrome";
import type { BookOCRRunSummary, BookSummary, PageSummary } from "../types/api";

const BOOK: BookSummary = {
  book_id: "b1",
  title: "యువ సంపుటి",
  author: null,
  publisher: null,
  publication_year: null,
  language_code: "te",
  orthography_profile: "unspecified",
  original_filename: "book.pdf",
  source_sha256: "abc",
  page_count: 4,
  rights_status: "unknown",
  training_consent: false,
  created_at: "2026-11-24T00:00:00Z",
  updated_at: "2026-11-24T00:00:00Z",
  scanned_pages_count: 4,
  digital_text_pages_count: 0,
  mixed_pages_count: 0,
};

function pageList(statuses: PageSummary["review_status"][]): PageSummary[] {
  return statuses.map((review_status, i) => ({
    page_id: `p${i + 1}`,
    page_number: i + 1,
    page_kind: "scanned_image",
    width_px: 1000,
    height_px: 1500,
    render_dpi: 300,
    extracted_text_char_count: 0,
    image_coverage_ratio: 1,
    review_status,
    has_image: true,
  }));
}

const COMPLETED_RUN: BookOCRRunSummary = {
  ocr_run_id: "r1",
  engine: "tesseract",
  model_id: "tesseract-5-tel-best",
  status: "completed",
  progress_current: 4,
  progress_total: 4,
  config: {},
  created_at: "2026-11-24T00:00:00Z",
  completed_at: "2026-11-24T00:00:05Z",
};

describe("CommitmentBar", () => {
  it("states the core product commitments", () => {
    render(<CommitmentBar />);
    expect(screen.getByRole("note", { name: "Core commitments" })).toBeInTheDocument();
    expect(screen.getByText(/Raw OCR output is never overwritten/)).toBeInTheDocument();
    expect(screen.getByText(/No silent Telugu auto-correction/)).toBeInTheDocument();
    expect(screen.getByText(/Runs 100% on this machine/)).toBeInTheDocument();
    expect(screen.getByText(/Source PDF stored read-only/)).toBeInTheDocument();
    const lahariLink = screen.getByRole("link", { name: /lahari\.org/ });
    expect(lahariLink).toHaveAttribute("href", "https://lahari.org");
  });
});

describe("deriveWorkflowSteps", () => {
  it("marks OCR as the current step before any run exists", () => {
    const steps = deriveWorkflowSteps(BOOK, [], pageList(["not_started", "not_started", "not_started", "not_started"]), "review");
    expect(steps.find((s) => s.key === "import")?.state).toBe("done");
    const ocr = steps.find((s) => s.key === "ocr");
    expect(ocr?.state).toBe("active");
    expect(ocr?.current).toBe(true);
    expect(steps.find((s) => s.key === "export")?.enabled).toBe(false);
  });

  it("moves to Review once OCR completes and completes it when all pages are approved", () => {
    const partial = deriveWorkflowSteps(BOOK, [COMPLETED_RUN], pageList(["approved", "not_started", "not_started", "not_started"]), "review");
    expect(partial.find((s) => s.key === "ocr")?.state).toBe("done");
    expect(partial.find((s) => s.key === "review")?.current).toBe(true);
    expect(partial.find((s) => s.key === "review")?.detail).toBe("1/4 pages approved");
    expect(partial.find((s) => s.key === "export")?.enabled).toBe(true);

    const all = deriveWorkflowSteps(BOOK, [COMPLETED_RUN], pageList(["approved", "approved", "approved", "approved"]), "review");
    expect(all.find((s) => s.key === "review")?.state).toBe("done");
    expect(all.find((s) => s.key === "export")?.current).toBe(true);
  });

  it("flags partial OCR runs with a warning state", () => {
    const steps = deriveWorkflowSteps(
      BOOK,
      [{ ...COMPLETED_RUN, status: "partial" }],
      pageList(["not_started", "not_started", "not_started", "not_started"]),
      "review",
    );
    expect(steps.find((s) => s.key === "ocr")?.state).toBe("warn");
  });
});

describe("OverviewPanel", () => {
  it("renders stepper, stat cards, and navigates to Export from a ready step", () => {
    const onExport = vi.fn();
    render(
      <OverviewPanel
        book={BOOK}
        pages={pageList(["approved", "approved", "not_started", "needs_attention"])}
        runs={[COMPLETED_RUN]}
        review={null}
        activeView="review"
        onGoToReview={vi.fn()}
        onGoToExport={onExport}
      />,
    );

    expect(screen.getByRole("list", { name: "Digitization workflow" })).toBeInTheDocument();
    expect(screen.getByText("50%")).toBeInTheDocument();
    expect(screen.getByText(/2\/4 approved · 1 need attention/)).toBeInTheDocument();
    expect(screen.getByText("Tesseract 5 Telugu")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar", { name: "Pages approved" }) as HTMLProgressElement;
    expect(bar.value).toBe(2);
    expect(bar.max).toBe(4);

    fireEvent.click(screen.getByRole("button", { name: /Export/ }));
    expect(onExport).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /Hide stats/ }));
    expect(screen.queryByRole("list", { name: "Book overview" })).not.toBeInTheDocument();
  });
});

describe("WelcomeHero", () => {
  it("presents commitments as feature cards and triggers import CTA", () => {
    const onImport = vi.fn();
    render(<WelcomeHero onImportClick={onImport} />);
    expect(screen.getByRole("heading", { level: 3, name: "Raw output preserved" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Local-first & private" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "How it works" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Import your first PDF" }));
    expect(onImport).toHaveBeenCalledTimes(1);
  });
});
