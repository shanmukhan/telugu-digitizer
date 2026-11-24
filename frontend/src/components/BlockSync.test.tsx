import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReviewEditorPanel } from "./ReviewEditorPanel";
import { SourcePageViewer } from "./SourcePageViewer";
import type { PageReviewPayload } from "../types/api";

const MULTI_BLOCK_REVIEW: PageReviewPayload = {
  book_id: "00000000-0000-0000-0000-000000000001",
  book_title: "తెలుగు పుస్తకం",
  page_id: "00000000-0000-0000-0000-000000000002",
  page_number: 5,
  page_count: 20,
  page_kind: "scanned_image",
  width_px: 1000,
  height_px: 1600,
  render_dpi: 300,
  review_status: "in_review",
  digital_text_content: null,
  available_runs: [
    {
      ocr_run_id: "run-1",
      engine: "paddleocr",
      model_id: "PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec",
      status: "completed",
      config: {},
      created_at: "2026-11-24T00:00:00Z",
      completed_at: "2026-11-24T00:00:10Z",
    },
  ],
  primary_run_id: "run-1",
  primary_engine: "paddleocr",
  primary_model_id: "PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec",
  comparator_run_id: null,
  comparator_engine: null,
  blocks: [
    {
      block_id: "blk-1",
      block_index: 0,
      reading_order: 0,
      block_type: "text_line",
      raw_text: "మొదటి లైన్",
      normalized_text: "మొదటి లైన్",
      current_text: "మొదటి లైన్",
      is_edited: false,
      latest_action: null,
      confidence: 0.7,
      low_confidence_flag: true,
      disagreement_flag: false,
      short_or_empty_flag: false,
      comparator_text: null,
      polygon: [
        [50, 80],
        [450, 80],
        [450, 120],
        [50, 120],
      ],
      bbox: [50, 80, 450, 120],
      suggestions: [],
      edit_history: [],
    },
    {
      block_id: "blk-2",
      block_index: 1,
      reading_order: 1,
      block_type: "text_line",
      raw_text: "రెండవ లైన్",
      normalized_text: "రెండవ లైన్",
      current_text: "రెండవ లైన్",
      is_edited: false,
      latest_action: null,
      confidence: 0.98,
      low_confidence_flag: false,
      disagreement_flag: false,
      short_or_empty_flag: false,
      comparator_text: null,
      polygon: [
        [50, 1200],
        [450, 1200],
        [450, 1260],
        [50, 1260],
      ],
      bbox: [50, 1200, 450, 1260],
      suggestions: [],
      edit_history: [],
    },
  ],
};

describe("Bidirectional block sync controls", () => {
  it("triggers Sync -> Scan, Auto-Sync, per-card Find on scan, and scrolls editor on syncTarget", async () => {
    const onSyncToScan = vi.fn();
    const onToggleAutoSync = vi.fn();
    const onLocateBlockOnScan = vi.fn();

    const { rerender } = render(
      <ReviewEditorPanel
        review={MULTI_BLOCK_REVIEW}
        selectedBlockId={null}
        busyBlockId={null}
        syncTarget={null}
        autoSync={false}
        onSelectBlock={vi.fn()}
        onLocateBlockOnScan={onLocateBlockOnScan}
        onSyncToScan={onSyncToScan}
        onToggleAutoSync={onToggleAutoSync}
        onSelectPrimaryRun={vi.fn()}
        onSaveEdit={vi.fn().mockResolvedValue(undefined)}
        onAcceptSuggestion={vi.fn().mockResolvedValue(undefined)}
        onRejectSuggestion={vi.fn().mockResolvedValue(undefined)}
        onChangePageStatus={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const syncBtn = screen.getByRole("button", { name: "Sync to selected block on scan" });
    expect(syncBtn).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Auto-Sync" }));
    expect(onToggleAutoSync).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Locate line 2 on scan" }));
    expect(onLocateBlockOnScan).toHaveBeenCalledWith("blk-2");

    // Turn on Flagged Only (which hides blk-2), select blk-1, and click Sync -> Scan
    fireEvent.click(screen.getByRole("button", { name: /Flagged Only/ }));
    expect(screen.queryByText("రెండవ లైన్")).not.toBeInTheDocument();

    const scrollSpy = vi.fn().mockResolvedValue(undefined);
    HTMLElement.prototype.scrollIntoView = scrollSpy;

    rerender(
      <ReviewEditorPanel
        review={MULTI_BLOCK_REVIEW}
        selectedBlockId="blk-1"
        busyBlockId={null}
        syncTarget={{ blockId: "blk-2", seq: 1 }}
        autoSync={false}
        onSelectBlock={vi.fn()}
        onLocateBlockOnScan={onLocateBlockOnScan}
        onSyncToScan={onSyncToScan}
        onToggleAutoSync={onToggleAutoSync}
        onSelectPrimaryRun={vi.fn()}
        onSaveEdit={vi.fn().mockResolvedValue(undefined)}
        onAcceptSuggestion={vi.fn().mockResolvedValue(undefined)}
        onRejectSuggestion={vi.fn().mockResolvedValue(undefined)}
        onChangePageStatus={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByRole("button", { name: "Sync to selected block on scan" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Sync to selected block on scan" }));
    expect(onSyncToScan).toHaveBeenCalledTimes(1);

    // Sync target automatically clears Flagged Only so blk-2 becomes visible and scrolls into view
    await waitFor(() => {
      expect(scrollSpy).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByText("Synced editor to line 2.")).toBeInTheDocument();
    });
  });

  it("scrolls scan pane container and highlights polygon when syncTarget targets a scan box", async () => {
    const onSyncToEditor = vi.fn();
    const scrollToSpy = vi.fn().mockResolvedValue(undefined);
    HTMLElement.prototype.scrollTo = scrollToSpy;

    const { rerender } = render(
      <SourcePageViewer
        bookId={MULTI_BLOCK_REVIEW.book_id}
        pageNumber={5}
        pageCount={20}
        widthPx={1000}
        heightPx={1600}
        blocks={MULTI_BLOCK_REVIEW.blocks}
        selectedBlockId={null}
        syncTarget={null}
        autoSync={false}
        onSelectBlock={vi.fn()}
        onNavigatePage={vi.fn()}
        onSyncToEditor={onSyncToEditor}
        onToggleAutoSync={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Sync to selected block in editor" })).toBeDisabled();

    rerender(
      <SourcePageViewer
        bookId={MULTI_BLOCK_REVIEW.book_id}
        pageNumber={5}
        pageCount={20}
        widthPx={1000}
        heightPx={1600}
        blocks={MULTI_BLOCK_REVIEW.blocks}
        selectedBlockId="blk-2"
        syncTarget={{ blockId: "blk-2", seq: 2 }}
        autoSync={true}
        onSelectBlock={vi.fn()}
        onNavigatePage={vi.fn()}
        onSyncToEditor={onSyncToEditor}
        onToggleAutoSync={vi.fn()}
      />,
    );

    const syncEditorBtn = screen.getByRole("button", { name: "Sync to selected block in editor" });
    expect(syncEditorBtn).toBeEnabled();
    fireEvent.click(syncEditorBtn);
    expect(onSyncToEditor).toHaveBeenCalledTimes(1);

    await waitFor(() => {
      expect(scrollToSpy).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      expect(screen.getByText("Synced scan view to line 2.")).toBeInTheDocument();
    });
  });
});
