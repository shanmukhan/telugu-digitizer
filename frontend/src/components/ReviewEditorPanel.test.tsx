import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ReviewEditorPanel } from "./ReviewEditorPanel";
import type { PageReviewPayload } from "../types/api";

const SAMPLE_REVIEW: PageReviewPayload = {
  book_id: "00000000-0000-0000-0000-000000000001",
  book_title: "తెలుగు పుస్తకం",
  page_id: "00000000-0000-0000-0000-000000000002",
  page_number: 1,
  page_count: 1,
  page_kind: "scanned_image",
  width_px: 900,
  height_px: 330,
  render_dpi: 300,
  review_status: "not_started",
  digital_text_content: null,
  available_runs: [
    {
      ocr_run_id: "run-1",
      engine: "paddleocr",
      model_id: "PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec",
      status: "completed",
      config: {},
      created_at: "2026-11-23T00:00:00Z",
      completed_at: "2026-11-23T00:00:10Z",
    },
  ],
  primary_run_id: "run-1",
  primary_engine: "paddleocr",
  primary_model_id: "PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec",
  comparator_run_id: "run-2",
  comparator_engine: "tesseract",
  blocks: [
    {
      block_id: "blk-1",
      block_index: 0,
      reading_order: 0,
      block_type: "text_line",
      raw_text: "తెలుగు పస్తకం",
      normalized_text: "తెలుగు పస్తకం",
      current_text: "తెలుగు పస్తకం",
      is_edited: false,
      latest_action: null,
      confidence: 0.72,
      low_confidence_flag: true,
      disagreement_flag: true,
      short_or_empty_flag: false,
      comparator_text: "తెలుగు పుస్తకం",
      polygon: [
        [10, 10],
        [200, 10],
        [200, 50],
        [10, 50],
      ],
      bbox: [10, 10, 200, 50],
      suggestions: [
        {
          correction_id: "cm-1",
          incorrect_text: "పస్తకం",
          corrected_text: "పుస్తకం",
          left_context: "తెలుగు",
          right_context: null,
          correction_type: "vowel_sign",
          scope: "global_suggestion",
          status: "active",
          approved_count: 2,
          rejected_count: 0,
          context_match: "strong",
          source_book_count: 1,
          has_conflict: false,
          proposed_block_text: "తెలుగు పుస్తకం",
        },
      ],
      edit_history: [],
    },
  ],
};

describe("ReviewEditorPanel", () => {
  it("renders raw OCR, flags, suggestions, and supports save/undo/redo/approve", async () => {
    const onSaveEdit = vi.fn().mockResolvedValue(undefined);
    const onAcceptSuggestion = vi.fn().mockResolvedValue(undefined);
    const onRejectSuggestion = vi.fn().mockResolvedValue(undefined);
    const onChangePageStatus = vi.fn().mockResolvedValue(undefined);

    render(
      <ReviewEditorPanel
        review={SAMPLE_REVIEW}
        selectedBlockId="blk-1"
        busyBlockId={null}
        onSelectBlock={vi.fn()}
        onSelectPrimaryRun={vi.fn()}
        onSaveEdit={onSaveEdit}
        onAcceptSuggestion={onAcceptSuggestion}
        onRejectSuggestion={onRejectSuggestion}
        onChangePageStatus={onChangePageStatus}
      />,
    );

    expect(screen.getByText(/Low Confidence/)).toBeInTheDocument();
    expect(screen.getByText(/Engine Disagreement/)).toBeInTheDocument();
    expect(screen.getByText("Correction Memory Suggestions")).toBeInTheDocument();
    expect(screen.getAllByText("తెలుగు పస్తకం").length).toBeGreaterThanOrEqual(2);

    fireEvent.click(screen.getByRole("button", { name: "Apply Suggestion" }));
    await waitFor(() => {
      expect(onAcceptSuggestion).toHaveBeenCalledTimes(1);
    });

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => {
      expect(onRejectSuggestion).toHaveBeenCalledWith("cm-1");
    });

    const textarea = screen.getByLabelText("Edit Telugu text for line 1") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "తెలుగు పుస్తకం" } });
    // Save to correction memory is checked by default when a manual edit is made.
    const rememberCheckbox = screen.getByLabelText("Save to correction memory") as HTMLInputElement;
    expect(rememberCheckbox.checked).toBe(true);

    const saveBtn = screen.getByRole("button", { name: "Save Correction" });
    expect(saveBtn).toBeEnabled();
    fireEvent.click(saveBtn);

    await waitFor(() => {
      expect(onSaveEdit).toHaveBeenCalledWith("blk-1", "తెలుగు పుస్తకం", "corrected", undefined, {
        addToMemory: true,
        memoryScope: "book_only",
        correctionType: undefined,
      });
    });

    const undoBtn = screen.getByRole("button", { name: "Undo" });
    expect(undoBtn).toBeEnabled();
    fireEvent.click(undoBtn);
    await waitFor(() => {
      expect(onSaveEdit).toHaveBeenCalledWith("blk-1", "తెలుగు పస్తకం", "reverted", "Undo edit");
    });

    const redoBtn = screen.getByRole("button", { name: "Redo" });
    expect(redoBtn).toBeEnabled();
    fireEvent.click(redoBtn);
    await waitFor(() => {
      expect(onSaveEdit).toHaveBeenCalledWith("blk-1", "తెలుగు పుస్తకం", "corrected", "Redo edit");
    });

    fireEvent.click(screen.getByRole("button", { name: "Approve Page" }));
    await waitFor(() => {
      expect(onChangePageStatus).toHaveBeenCalledWith("approved");
    });
  });

  it("preserves unsaved user draft edits when review payload refreshes for the same page", () => {
    const { rerender } = render(
      <ReviewEditorPanel
        review={SAMPLE_REVIEW}
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

    const textarea = screen.getByLabelText("Edit Telugu text for line 1") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "తెలుగు పుస్తకం (ఇంకా సేవ్ చేయనిది)" } });
    expect(textarea.value).toBe("తెలుగు పుస్తకం (ఇంకా సేవ్ చేయనిది)");

    // Simulate background polling refreshing the review prop with a new object reference
    rerender(
      <ReviewEditorPanel
        review={{
          ...SAMPLE_REVIEW,
          blocks: SAMPLE_REVIEW.blocks.map((b) => ({ ...b })),
        }}
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

    expect(
      (screen.getByLabelText("Edit Telugu text for line 1") as HTMLTextAreaElement).value,
    ).toBe("తెలుగు పుస్తకం (ఇంకా సేవ్ చేయనిది)");
  });

  it("supports line filtering, Telugu font scaling, Next Issue jump, and Ctrl+Enter shortcut", async () => {
    const onSaveEdit = vi.fn().mockResolvedValue(undefined);
    const onSelectBlock = vi.fn();
    render(
      <ReviewEditorPanel
        review={SAMPLE_REVIEW}
        selectedBlockId={null}
        busyBlockId={null}
        onSelectBlock={onSelectBlock}
        onSelectPrimaryRun={vi.fn()}
        onSaveEdit={onSaveEdit}
        onAcceptSuggestion={vi.fn().mockResolvedValue(undefined)}
        onRejectSuggestion={vi.fn().mockResolvedValue(undefined)}
        onChangePageStatus={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Next Issue ▾" }));
    expect(onSelectBlock).toHaveBeenCalledWith("blk-1");

    const filterInput = screen.getByLabelText("Filter lines on this page");
    fireEvent.change(filterInput, { target: { value: "nonexistent_word" } });
    expect(screen.queryByLabelText("Edit Telugu text for line 1")).not.toBeInTheDocument();

    fireEvent.change(filterInput, { target: { value: "" } });
    const textarea = screen.getByLabelText("Edit Telugu text for line 1") as HTMLTextAreaElement;
    fireEvent.keyDown(textarea, { key: "Enter", ctrlKey: true });
    await waitFor(() => {
      expect(onSaveEdit).toHaveBeenCalledWith(
        "blk-1",
        "తెలుగు పస్తకం",
        "approved",
        undefined,
        expect.any(Object),
      );
    });
  });

  it("shows Switch to alternate populated engine button when selected partial run has 0 blocks", () => {
    const onSelectPrimaryRun = vi.fn();
    render(
      <ReviewEditorPanel
        review={{
          ...SAMPLE_REVIEW,
          primary_run_id: "run-paddle-empty",
          primary_engine: "paddleocr",
          blocks: [],
          available_runs: [
            {
              ocr_run_id: "run-paddle-empty",
              engine: "paddleocr",
              model_id: "PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec",
              status: "partial",
              progress_current: 0,
              progress_total: 15,
              error_summary: "Interrupted before completion; ready to resume.",
              config: {},
              created_at: "2026-11-23T00:00:00Z",
              completed_at: null,
            },
            {
              ocr_run_id: "run-tess-done",
              engine: "tesseract",
              model_id: "tesseract-5-tel-best",
              status: "completed",
              progress_current: 15,
              progress_total: 15,
              config: {},
              created_at: "2026-11-23T00:00:00Z",
              completed_at: "2026-11-23T00:05:00Z",
            },
          ],
        }}
        selectedBlockId={null}
        busyBlockId={null}
        onSelectBlock={vi.fn()}
        onSelectPrimaryRun={onSelectPrimaryRun}
        onSaveEdit={vi.fn().mockResolvedValue(undefined)}
        onAcceptSuggestion={vi.fn().mockResolvedValue(undefined)}
        onRejectSuggestion={vi.fn().mockResolvedValue(undefined)}
        onChangePageStatus={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const switchBtn = screen.getByRole("button", { name: "Switch to Tesseract 5 Telugu" });
    fireEvent.click(switchBtn);
    expect(onSelectPrimaryRun).toHaveBeenCalledWith("run-tess-done");
  });

  it("supports opt-in Auto-Correct Page preview, revert, and Save All & Approve Page", async () => {
    const onAutocorrectPage = vi.fn().mockResolvedValue({
      book_id: SAMPLE_REVIEW.book_id,
      page_number: 1,
      primary_run_id: "run-1",
      lexicon_word_count: 139709,
      total_blocks_scanned: 1,
      changed_blocks_count: 1,
      total_changes_count: 1,
      blocks: [
        {
          block_id: "blk-1",
          original_text: "తెలుగు పస్తకం",
          proposed_text: "తెలుగు పుస్తకం",
          changes: [
            {
              original: "పస్తకం",
              replacement: "పుస్తకం",
              source: "dictionary",
              confidence: 0.89,
              reason: "Telugu dictionary + OCR similarity match",
            },
          ],
        },
      ],
    });
    const onBatchSaveAndApprovePage = vi.fn().mockResolvedValue(undefined);
    const onLookupWord = vi.fn();
    const onToggleAutoAdvance = vi.fn();

    render(
      <ReviewEditorPanel
        review={SAMPLE_REVIEW}
        selectedBlockId="blk-1"
        busyBlockId={null}
        autoAdvance={true}
        onSelectBlock={vi.fn()}
        onSelectPrimaryRun={vi.fn()}
        onLookupWord={onLookupWord}
        onToggleAutoAdvance={onToggleAutoAdvance}
        onSaveEdit={vi.fn().mockResolvedValue(undefined)}
        onAutocorrectPage={onAutocorrectPage}
        onBatchSaveAndApprovePage={onBatchSaveAndApprovePage}
        onAcceptSuggestion={vi.fn().mockResolvedValue(undefined)}
        onRejectSuggestion={vi.fn().mockResolvedValue(undefined)}
        onChangePageStatus={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    const autoNextBtn = screen.getByRole("button", { name: "Auto-Next" });
    expect(autoNextBtn).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(autoNextBtn);
    expect(onToggleAutoAdvance).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "📚 Dictionary" }));
    expect(onLookupWord).toHaveBeenCalledWith("తెలుగు");

    fireEvent.click(screen.getByRole("button", { name: "✨ Auto-Correct Page" }));
    await waitFor(() => {
      expect(onAutocorrectPage).toHaveBeenCalledTimes(1);
    });

    const textarea = screen.getByLabelText("Edit Telugu text for line 1") as HTMLTextAreaElement;
    expect(textarea.value).toBe("తెలుగు పుస్తకం");
    expect(screen.getByText(/Auto-Correct Draft Preview/)).toBeInTheDocument();

    // Test one-click Revert Auto-Correct restores original draft.
    fireEvent.click(screen.getByRole("button", { name: "↩ Revert Auto-Correct" }));
    expect(textarea.value).toBe("తెలుగు పస్తకం");

    // Re-run auto-correct and commit entire page in one click.
    fireEvent.click(screen.getByRole("button", { name: "✨ Auto-Correct Page" }));
    await waitFor(() => {
      expect(textarea.value).toBe("తెలుగు పుస్తకం");
    });

    const batchApproveBtn = screen.getByRole("button", { name: "Save All (1) & Approve Page" });
    fireEvent.click(batchApproveBtn);
    await waitFor(() => {
      expect(onBatchSaveAndApprovePage).toHaveBeenCalledWith([
        expect.objectContaining({
          block_id: "blk-1",
          edited_text: "తెలుగు పుస్తకం",
          action: "corrected",
          add_to_correction_memory: true,
          memory_scope: "book_only",
        }),
      ]);
    });
  });
});
