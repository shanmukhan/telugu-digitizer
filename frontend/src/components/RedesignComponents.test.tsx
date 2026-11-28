import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { PageRail } from "./PageRail";
import { ReviewEditorPanel } from "./ReviewEditorPanel";
import { SourcePageViewer } from "./SourcePageViewer";
import { TopNavBar } from "./TopNavBar";
import type { BookSummary, PageReviewPayload, PageSummary, ReviewBlock } from "../types/api";
import { diffComparatorWords, diffTeluguGraphemes } from "../utils/teluguDiff";

function makeBook(id: string, title: string, pages = 120): BookSummary {
  return {
    book_id: id,
    title,
    author: null,
    publisher: null,
    publication_year: null,
    language_code: "te",
    orthography_profile: "modern_standard",
    original_filename: `${id}.pdf`,
    source_sha256: "abc",
    page_count: pages,
    rights_status: "owned",
    training_consent: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    scanned_pages_count: pages,
    digital_text_pages_count: 0,
    mixed_pages_count: 0,
  };
}

function makeBlock(overrides: Partial<ReviewBlock> = {}): ReviewBlock {
  return {
    block_id: "blk-1",
    block_index: 0,
    reading_order: 0,
    block_type: "line",
    block_role: "paragraph",
    raw_text: "తెలుగు పస్తకం",
    normalized_text: "తెలుగు పస్తకం",
    current_text: "తెలుగు పస్తకం",
    is_edited: false,
    latest_action: null,
    confidence: 0.96,
    low_confidence_flag: false,
    disagreement_flag: false,
    short_or_empty_flag: false,
    comparator_text: null,
    polygon: [
      [10, 10],
      [200, 10],
      [200, 40],
      [10, 40],
    ],
    bbox: [10, 10, 200, 40],
    suggestions: [],
    edit_history: [],
    ...overrides,
  };
}

function makeReview(blocks: ReviewBlock[]): PageReviewPayload {
  return {
    book_id: "book-1",
    book_title: "తెలుగు కథలు",
    page_id: "page-1",
    page_number: 1,
    page_count: 10,
    page_kind: "scanned_image",
    width_px: 1000,
    height_px: 1400,
    render_dpi: 300,
    review_status: "in_review",
    digital_text_content: null,
    available_runs: [],
    primary_run_id: "run-1",
    primary_engine: "paddle_ppocrv5_te",
    primary_model_id: "PP-OCRv5",
    comparator_run_id: "run-2",
    comparator_engine: "tesseract_tel_best",
    blocks,
  };
}

describe("teluguDiff grapheme & word helpers", () => {
  it("highlights Telugu akshara-level changes without splitting vowel signs", () => {
    const ops = diffTeluguGraphemes("తెలుగు పస్తకం", "తెలుగు పుస్తకం");
    const removed = ops.filter((o) => o.kind === "del").map((o) => o.text).join("");
    const added = ops.filter((o) => o.kind === "ins").map((o) => o.text).join("");
    expect(removed).toBe("ప");
    expect(added).toBe("పు");
  });

  it("identifies differing comparator words for 1-click insertion", () => {
    const tokens = diffComparatorWords("తెలుగు పస్తకం మంచిది", "తెలుగు పుస్తకం మంచిది");
    const differing = tokens.filter((t) => t.changed).map((t) => t.word);
    expect(differing).toEqual(["పుస్తకం"]);
  });
});

describe("PageRail virtualization", () => {
  it("virtualizes a 500-page book instead of rendering 500 buttons", () => {
    const pages: PageSummary[] = Array.from({ length: 500 }, (_, i) => ({
      page_id: `p-${i + 1}`,
      page_number: i + 1,
      page_kind: "scanned_image",
      width_px: 1000,
      height_px: 1400,
      render_dpi: 300,
      extracted_text_char_count: 0,
      image_coverage_ratio: 0.9,
      review_status: i < 10 ? "approved" : "not_started",
      has_image: true,
    }));

    const onSelectPage = vi.fn();
    render(
      <PageRail
        open
        pages={pages}
        selectedPageNumber={1}
        pageFilter="all"
        onChangeFilter={vi.fn()}
        onSelectPage={onSelectPage}
        onClose={vi.fn()}
      />,
    );

    const renderedPageButtons = screen
      .getAllByRole("button")
      .filter((btn) => btn.classList.contains("page-rail-row"));
    expect(renderedPageButtons.length).toBeGreaterThan(0);
    expect(renderedPageButtons.length).toBeLessThan(40);

    fireEvent.click(renderedPageButtons[1]);
    expect(onSelectPage).toHaveBeenCalledWith(2);
  });
});

describe("TopNavBar navigation & book switcher", () => {
  it("switches books from the menu and supports arrow-key navigation across view tabs", () => {
    const bookA = makeBook("b1", "అమరావతి కథలు", 80);
    const bookB = makeBook("b2", "వేమన పద్యాలు", 45);
    const onSelectBook = vi.fn();
    const onSelectView = vi.fn();

    render(
      <TopNavBar
        books={[bookA, bookB]}
        selectedBook={bookA}
        runs={[]}
        activeView="review"
        keyboardOpen={false}
        onSelectBook={onSelectBook}
        onSelectView={onSelectView}
        onOpenImport={vi.fn()}
        onOpenOcrDrawer={vi.fn()}
        onToggleKeyboard={vi.fn()}
        onOpenShortcuts={vi.fn()}
      />,
    );

    // Open book switcher menu and choose Book B
    fireEvent.click(screen.getByRole("button", { name: /అమరావతి కథలు/i }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /వేమన పద్యాలు/i }));
    expect(onSelectBook).toHaveBeenCalledWith("b2");

    // ArrowRight on Proofread tab moves to Dictionary
    const tablist = screen.getByRole("tablist", { name: "Workspace views" });
    fireEvent.keyDown(tablist, { key: "ArrowRight" });
    expect(onSelectView).toHaveBeenCalledWith("dictionary");
  });
});

describe("Two-Density ReviewEditorPanel & draft-safe Flag Page", () => {
  it("renders unselected clean lines in compact rows and expands the selected line with grapheme diff", () => {
    const b1 = makeBlock({ block_id: "blk-1", block_index: 0, raw_text: "తెలుగు పస్తకం", current_text: "తెలుగు పుస్తకం" });
    const b2 = makeBlock({ block_id: "blk-2", block_index: 1, raw_text: "రెండవ వరుస", current_text: "రెండవ వరుస" });

    const { container } = render(
      <ReviewEditorPanel
        review={makeReview([b1, b2])}
        selectedBlockId="blk-1"
        busyBlockId={null}
        onSelectBlock={vi.fn()}
        onSelectPrimaryRun={vi.fn()}
        onSaveEdit={vi.fn().mockResolvedValue(undefined)}
        onAcceptSuggestion={vi.fn().mockResolvedValue(undefined)}
        onRejectSuggestion={vi.fn().mockResolvedValue(undefined)}
        onChangePageStatus={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(container.querySelector('[data-block-id="blk-1"]')?.classList.contains("block-card")).toBe(true);
    expect(container.querySelector('[data-block-id="blk-2"]')?.classList.contains("block-row")).toBe(true);
    expect(container.querySelector(".diff-ins")?.textContent).toBe("పు");
  });

  it("saves dirty drafts when clicking Flag Page instead of discarding unsaved edits", async () => {
    const b1 = makeBlock({ block_id: "blk-1", block_index: 0, current_text: "తెలుగు పస్తకం" });
    const onBatchSaveAndApprovePage = vi.fn().mockResolvedValue(undefined);

    render(
      <ReviewEditorPanel
        review={makeReview([b1])}
        selectedBlockId="blk-1"
        busyBlockId={null}
        onSelectBlock={vi.fn()}
        onSelectPrimaryRun={vi.fn()}
        onSaveEdit={vi.fn().mockResolvedValue(undefined)}
        onBatchSaveAndApprovePage={onBatchSaveAndApprovePage}
        onAcceptSuggestion={vi.fn().mockResolvedValue(undefined)}
        onRejectSuggestion={vi.fn().mockResolvedValue(undefined)}
        onChangePageStatus={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const textarea = screen.getByLabelText("Edit Telugu text for line 1");
    fireEvent.change(textarea, { target: { value: "తెలుగు పుస్తకం" } });
    fireEvent.click(screen.getByRole("button", { name: /Flag Page/i }));

    await waitFor(() => {
      expect(onBatchSaveAndApprovePage).toHaveBeenCalledWith(
        [
          expect.objectContaining({
            block_id: "blk-1",
            edited_text: "తెలుగు పుస్తకం",
            action: "corrected",
          }),
        ],
        expect.objectContaining({ targetStatus: "needs_attention", markPageApproved: false }),
      );
    });
  });
});

describe("SourcePageViewer accessible single-tab-stop SVG listbox", () => {
  it("uses a single tab stop on the SVG overlay and steps lines with ArrowDown", () => {
    const b1 = makeBlock({ block_id: "blk-1", block_index: 0 });
    const b2 = makeBlock({ block_id: "blk-2", block_index: 1, bbox: [10, 60, 200, 90] });
    const onSelectBlock = vi.fn();

    const { container } = render(
      <SourcePageViewer
        bookId="book-1"
        pageNumber={1}
        pageCount={10}
        widthPx={1000}
        heightPx={1400}
        blocks={[b1, b2]}
        selectedBlockId="blk-1"
        hidePageNav
        onSelectBlock={onSelectBlock}
        onNavigatePage={vi.fn()}
      />,
    );

    fireEvent.load(screen.getByAltText("Scanned source page 1"));

    const svg = screen.getByRole("listbox", { name: /OCR text region overlays/i });
    expect(svg.getAttribute("tabindex")).toBe("0");
    // Individual polygons/rects must not be in the Tab sequence
    expect(container.querySelectorAll(".overlay-poly[tabindex]").length).toBe(0);

    fireEvent.keyDown(svg, { key: "ArrowDown" });
    expect(onSelectBlock).toHaveBeenCalledWith("blk-2");
  });
});
