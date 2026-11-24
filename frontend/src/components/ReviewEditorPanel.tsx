import { memo, useCallback, useEffect, useRef, useState } from "react";
import type { CorrectionSuggestionItem, PageReviewPayload, ReviewBlock } from "../types/api";
import { formatEngineLabel } from "../utils/formatters";
import { scrollIntoViewAsync } from "../utils/scrollSync";

interface UndoEntry {
  blockId: string;
  previousText: string;
  nextText: string;
}

export interface SaveEditOptions {
  addToMemory?: boolean;
  memoryScope?: "book_only" | "global_suggestion";
  correctionType?: string;
}

interface ReviewBlockCardProps {
  block: ReviewBlock;
  draftText: string;
  isSelected: boolean;
  isFlashing: boolean;
  isBusy: boolean;
  remember: boolean;
  scope: "book_only" | "global_suggestion";
  correctionType: string;
  primaryEngine: string | null;
  comparatorEngine: string | null;
  onSelectBlock: (blockId: string) => void;
  onLocateBlockOnScan?: (blockId: string) => void;
  onDraftChange: (blockId: string, value: string) => void;
  onRememberChange: (blockId: string, checked: boolean) => void;
  onScopeChange: (blockId: string, scope: "book_only" | "global_suggestion") => void;
  onTypeChange: (blockId: string, cType: string) => void;
  onCommitEdit: (
    block: ReviewBlock,
    nextText: string,
    action: "corrected" | "approved" | "reverted",
    pushHistory?: boolean,
  ) => Promise<void>;
  onAcceptSuggestion: (
    block: ReviewBlock,
    suggestion: CorrectionSuggestionItem,
  ) => Promise<void>;
  onRejectSuggestion: (suggestionId: string) => Promise<void>;
}

const ReviewBlockCard = memo(function ReviewBlockCard({
  block,
  draftText,
  isSelected,
  isFlashing,
  isBusy,
  remember,
  scope,
  correctionType,
  primaryEngine,
  comparatorEngine,
  onSelectBlock,
  onLocateBlockOnScan,
  onDraftChange,
  onRememberChange,
  onScopeChange,
  onTypeChange,
  onCommitEdit,
  onAcceptSuggestion,
  onRejectSuggestion,
}: ReviewBlockCardProps) {
  const isDirty = draftText !== block.current_text;
  const isFlagged =
    block.low_confidence_flag || block.disagreement_flag || block.short_or_empty_flag;

  return (
    <article
      data-block-id={block.block_id}
      className={[
        "block-card",
        isFlagged ? "flagged" : "",
        isSelected ? "selected" : "",
        isFlashing ? "sync-flash" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      onClick={() => onSelectBlock(block.block_id)}
    >
      <div className="badge-row">
        <span className="badge">Line {block.block_index + 1}</span>
        {block.confidence !== null && (
          <span className={block.low_confidence_flag ? "badge warn" : "badge"}>
            Conf:{" "}
            {primaryEngine === "tesseract"
              ? `${block.confidence.toFixed(1)}%`
              : block.confidence.toFixed(3)}
          </span>
        )}
        {block.low_confidence_flag && <span className="badge warn">⚠ Low Confidence</span>}
        {block.disagreement_flag && (
          <span className="badge warn">⇄ Engine Disagreement ({comparatorEngine})</span>
        )}
        {block.short_or_empty_flag && <span className="badge warn">! Short / Empty</span>}
        {block.suggestions.length > 0 && (
          <span className="badge">💡 {block.suggestions.length} Suggestion(s)</span>
        )}
        {block.is_edited && <span className="badge ok">✓ Edited</span>}
        {block.latest_action === "approved" && (
          <span className="badge ok">✓ Block Approved</span>
        )}
        {onLocateBlockOnScan && (
          <button
            type="button"
            className="btn-compact sync-card-btn"
            style={{ marginInlineStart: "auto" }}
            aria-label={`Locate line ${block.block_index + 1} on scan`}
            title="Scroll source scan to this line"
            onClick={(e) => {
              e.stopPropagation();
              onLocateBlockOnScan(block.block_id);
            }}
          >
            ⌖ Find on scan
          </button>
        )}
      </div>

      <div className="raw-ocr-box">
        <span className="hint-text">Raw OCR (immutable): </span>
        <span className="telugu-text" lang="te">
          {block.raw_text}
        </span>
      </div>

      {block.disagreement_flag && block.comparator_text !== null && (
        <div className="comparator-box">
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: "0.5rem",
              alignItems: "center",
            }}
          >
            <div>
              <span className="hint-text">{formatEngineLabel(comparatorEngine)} comparator: </span>
              <span className="telugu-text" lang="te">
                {block.comparator_text}
              </span>
            </div>
            <button
              type="button"
              onClick={() => onDraftChange(block.block_id, block.comparator_text ?? "")}
            >
              Use Comparator
            </button>
          </div>
        </div>
      )}

      {block.suggestions.length > 0 && (
        <div
          style={{
            padding: "0.5rem",
            border: "1px solid var(--border)",
            borderRadius: "0.45rem",
            background: "#faf7ef",
            display: "flex",
            flexDirection: "column",
            gap: "0.45rem",
          }}
        >
          <strong style={{ fontSize: "0.82rem" }}>Correction Memory Suggestions</strong>
          {block.suggestions.map((sug) => (
            <div
              key={sug.correction_id}
              style={{
                display: "flex",
                flexWrap: "wrap",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "0.5rem",
                padding: "0.35rem 0.45rem",
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: "0.35rem",
              }}
            >
              <div>
                <div className="telugu-text" lang="te">
                  <span>{sug.incorrect_text}</span> → <strong>{sug.corrected_text}</strong>
                </div>
                <div className="badge-row">
                  <span className="badge">{sug.scope}</span>
                  <span className="badge">Match: {sug.context_match}</span>
                  <span className="badge">
                    +{sug.approved_count} / −{sug.rejected_count}
                  </span>
                  <span className="badge">Books: {sug.source_book_count}</span>
                  {sug.has_conflict && <span className="badge warn">⚠ Conflict</span>}
                </div>
              </div>
              <div className="badge-row">
                <button
                  type="button"
                  className="primary"
                  disabled={isBusy}
                  onClick={() => void onAcceptSuggestion(block, sug)}
                >
                  Apply Suggestion
                </button>
                <button
                  type="button"
                  disabled={isBusy}
                  onClick={() => void onRejectSuggestion(sug.correction_id)}
                >
                  Reject
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <label htmlFor={`block-input-${block.block_id}`} className="visually-hidden">
        Edit Telugu text for line {block.block_index + 1}
      </label>
      <textarea
        id={`block-input-${block.block_id}`}
        lang="te"
        className="block-textarea"
        value={draftText}
        title="Tip: Press Ctrl+Enter (or Cmd+Enter) to save correction or approve block"
        onFocus={() => onSelectBlock(block.block_id)}
        onChange={(e) => onDraftChange(block.block_id, e.target.value)}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            if (isDirty) {
              void onCommitEdit(block, draftText, "corrected");
            } else {
              void onCommitEdit(block, draftText, "approved", false);
            }
          }
        }}
      />

      {isDirty && (
        <div className="badge-row" style={{ paddingBlock: "0.2rem" }}>
          <label
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "0.35rem",
              fontSize: "0.85rem",
            }}
          >
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => onRememberChange(block.block_id, e.target.checked)}
            />
            Save to correction memory
          </label>
          {remember && (
            <>
              <select
                aria-label="Correction memory scope"
                value={scope}
                onChange={(e) =>
                  onScopeChange(
                    block.block_id,
                    e.target.value as "book_only" | "global_suggestion",
                  )
                }
              >
                <option value="book_only">Book only</option>
                <option value="global_suggestion">Global suggestion</option>
              </select>
              <select
                aria-label="Correction error type"
                value={correctionType}
                onChange={(e) => onTypeChange(block.block_id, e.target.value)}
              >
                <option value="">Category (optional)</option>
                <option value="glyph_confusion">glyph_confusion</option>
                <option value="vowel_sign">vowel_sign</option>
                <option value="conjunct_or_virama">conjunct_or_virama</option>
                <option value="word_boundary">word_boundary</option>
                <option value="punctuation">punctuation</option>
                <option value="numeral">numeral</option>
              </select>
            </>
          )}
        </div>
      )}

      <div className="badge-row">
        <button
          type="button"
          className="primary"
          disabled={isBusy || !isDirty}
          onClick={() => void onCommitEdit(block, draftText, "corrected")}
        >
          {isBusy ? "Saving..." : "Save Correction"}
        </button>
        <button
          type="button"
          disabled={isBusy}
          onClick={() => void onCommitEdit(block, draftText, "approved", false)}
        >
          Approve Block
        </button>
        {block.current_text !== block.raw_text && (
          <button
            type="button"
            disabled={isBusy}
            onClick={() => {
              onDraftChange(block.block_id, block.raw_text);
              void onCommitEdit(block, block.raw_text, "reverted");
            }}
          >
            Revert to Raw OCR
          </button>
        )}
      </div>

      {block.edit_history.length > 0 && (
        <details className="edit-history-details">
          <summary className="hint-text">
            Revision history ({block.edit_history.length})
          </summary>
          <ul className="edit-history-list">
            {block.edit_history.map((evt) => (
              <li key={evt.edit_id}>
                <span className="badge">{evt.action}</span>{" "}
                <span className="telugu-text" lang="te">
                  {evt.edited_text}
                </span>
                {evt.review_note && (
                  <span className="hint-text"> — {evt.review_note}</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
});

interface ReviewEditorPanelProps {
  review: PageReviewPayload;
  selectedBlockId: string | null;
  busyBlockId: string | null;
  ocrRunning?: boolean;
  syncTarget?: { blockId: string; seq: number } | null;
  autoSync?: boolean;
  keyboardOpen?: boolean;
  onSelectBlock: (blockId: string) => void;
  onLocateBlockOnScan?: (blockId: string) => void;
  onSyncToScan?: () => void;
  onToggleAutoSync?: () => void;
  onToggleKeyboard?: () => void;
  onSelectPrimaryRun: (runId: string) => void;
  onQuickStartOcr?: () => Promise<void>;
  onSaveEdit: (
    blockId: string,
    editedText: string,
    action: "corrected" | "approved" | "reverted",
    reviewNote?: string,
    options?: SaveEditOptions,
  ) => Promise<void>;
  onAcceptSuggestion: (
    block: ReviewBlock,
    suggestion: CorrectionSuggestionItem,
  ) => Promise<void>;
  onRejectSuggestion: (suggestionId: string) => Promise<void>;
  onChangePageStatus: (
    status: "not_started" | "in_review" | "approved" | "needs_attention",
  ) => Promise<void>;
}

export function ReviewEditorPanel({
  review,
  selectedBlockId,
  busyBlockId,
  ocrRunning = false,
  syncTarget = null,
  autoSync = false,
  keyboardOpen = false,
  onSelectBlock,
  onLocateBlockOnScan,
  onSyncToScan,
  onToggleAutoSync,
  onToggleKeyboard,
  onSelectPrimaryRun,
  onQuickStartOcr,
  onSaveEdit,
  onAcceptSuggestion,
  onRejectSuggestion,
  onChangePageStatus,
}: ReviewEditorPanelProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [rememberByBlock, setRememberByBlock] = useState<Record<string, boolean>>({});
  const [scopeByBlock, setScopeByBlock] = useState<Record<string, "book_only" | "global_suggestion">>({});
  const [typeByBlock, setTypeByBlock] = useState<Record<string, string>>({});
  const [filterFlagged, setFilterFlagged] = useState(false);
  const [lineSearch, setLineSearch] = useState("");
  const [teluguFontScale, setTeluguFontScale] = useState(1.0);
  const [undoStack, setUndoStack] = useState<UndoEntry[]>([]);
  const [redoStack, setRedoStack] = useState<UndoEntry[]>([]);
  const [flashingBlockId, setFlashingBlockId] = useState<string | null>(null);
  const [syncNotice, setSyncNotice] = useState<string>("");
  const paneBodyRef = useRef<HTMLDivElement>(null);
  const syncSeqRef = useRef(0);
  const lastHandledSyncSeqRef = useRef<number | null>(null);
  const pageContextKeyRef = useRef<string>("");
  const serverTextsRef = useRef<Record<string, string>>({});

  useEffect(() => {
    const contextKey = `${review.book_id}:${review.page_number}:${review.primary_run_id ?? ""}`;
    const isSamePageContext = pageContextKeyRef.current === contextKey;
    pageContextKeyRef.current = contextKey;

    const prevServerTexts = serverTextsRef.current;
    const nextServerTexts: Record<string, string> = {};
    for (const blk of review.blocks) {
      nextServerTexts[blk.block_id] = blk.current_text;
    }
    serverTextsRef.current = nextServerTexts;

    setDrafts((prevDrafts) => {
      const nextDrafts: Record<string, string> = {};
      for (const blk of review.blocks) {
        const existingDraft = prevDrafts[blk.block_id];
        const prevServerText = prevServerTexts[blk.block_id];
        // Preserve unsaved user typing if background polling refreshed the same page
        if (
          isSamePageContext &&
          existingDraft !== undefined &&
          prevServerText !== undefined &&
          existingDraft !== prevServerText &&
          prevServerText === blk.current_text
        ) {
          nextDrafts[blk.block_id] = existingDraft;
        } else {
          nextDrafts[blk.block_id] = blk.current_text;
        }
      }
      return nextDrafts;
    });
  }, [review.book_id, review.page_number, review.primary_run_id, review.blocks]);

  const handleDraftChange = useCallback((blockId: string, value: string) => {
    setDrafts((prev) => ({ ...prev, [blockId]: value }));
  }, []);

  const handleRememberChange = useCallback((blockId: string, checked: boolean) => {
    setRememberByBlock((prev) => ({ ...prev, [blockId]: checked }));
  }, []);

  const handleScopeChange = useCallback(
    (blockId: string, nextScope: "book_only" | "global_suggestion") => {
      setScopeByBlock((prev) => ({ ...prev, [blockId]: nextScope }));
    },
    [],
  );

  const handleTypeChange = useCallback((blockId: string, cType: string) => {
    setTypeByBlock((prev) => ({ ...prev, [blockId]: cType }));
  }, []);

  useEffect(() => {
    setUndoStack([]);
    setRedoStack([]);
  }, [review.book_id, review.page_number, review.primary_run_id]);

  async function commitEdit(
    block: ReviewBlock,
    nextText: string,
    action: "corrected" | "approved" | "reverted",
    pushHistory = true,
  ) {
    const prevText = block.current_text;
    const addMem = action === "corrected" && Boolean(rememberByBlock[block.block_id]);
    const scope = scopeByBlock[block.block_id] ?? "book_only";
    const cType = typeByBlock[block.block_id] || undefined;

    await onSaveEdit(block.block_id, nextText, action, undefined, {
      addToMemory: addMem,
      memoryScope: scope,
      correctionType: cType,
    });
    if (addMem) {
      setRememberByBlock((prev) => ({ ...prev, [block.block_id]: false }));
    }
    if (pushHistory && prevText !== nextText) {
      setUndoStack((prev) => [...prev, { blockId: block.block_id, previousText: prevText, nextText }]);
      setRedoStack([]);
    }
  }

  async function handleUndo() {
    const last = undoStack[undoStack.length - 1];
    if (!last) return;
    setUndoStack((prev) => prev.slice(0, -1));
    setRedoStack((prev) => [...prev, last]);
    setDrafts((prev) => ({ ...prev, [last.blockId]: last.previousText }));
    await onSaveEdit(last.blockId, last.previousText, "reverted", "Undo edit");
  }

  async function handleRedo() {
    const next = redoStack[redoStack.length - 1];
    if (!next) return;
    setRedoStack((prev) => prev.slice(0, -1));
    setUndoStack((prev) => [...prev, next]);
    setDrafts((prev) => ({ ...prev, [next.blockId]: next.nextText }));
    await onSaveEdit(next.blockId, next.nextText, "corrected", "Redo edit");
  }

  const flaggedBlocks = review.blocks.filter(
    (b) =>
      b.low_confidence_flag ||
      b.disagreement_flag ||
      b.short_or_empty_flag ||
      b.suggestions.length > 0,
  );
  const flaggedCount = flaggedBlocks.length;

  const trimmedSearch = lineSearch.trim().toLowerCase();
  const visibleBlocks = review.blocks.filter((b) => {
    if (
      filterFlagged &&
      !(
        b.low_confidence_flag ||
        b.disagreement_flag ||
        b.short_or_empty_flag ||
        b.suggestions.length > 0
      )
    ) {
      return false;
    }
    if (trimmedSearch) {
      const draftVal = (drafts[b.block_id] ?? b.current_text).toLowerCase();
      const rawVal = b.raw_text.toLowerCase();
      const lineLabel = `line ${b.block_index + 1}`;
      return (
        draftVal.includes(trimmedSearch) ||
        rawVal.includes(trimmedSearch) ||
        lineLabel.includes(trimmedSearch)
      );
    }
    return true;
  });

  function handleJumpNextFlagged() {
    if (flaggedBlocks.length === 0) return;
    const currentIdx = flaggedBlocks.findIndex((b) => b.block_id === selectedBlockId);
    const nextBlock = flaggedBlocks[(currentIdx + 1) % flaggedBlocks.length];
    onSelectBlock(nextBlock.block_id);
    if (onLocateBlockOnScan) {
      onLocateBlockOnScan(nextBlock.block_id);
    }
    const scroller = paneBodyRef.current;
    if (scroller) {
      const escapedId =
        typeof CSS !== "undefined" && typeof CSS.escape === "function"
          ? CSS.escape(nextBlock.block_id)
          : nextBlock.block_id.replace(/"/g, '\\"');
      const cardEl = scroller.querySelector<HTMLElement>(`[data-block-id="${escapedId}"]`);
      if (cardEl) {
        void scrollIntoViewAsync(cardEl, scroller);
      }
    }
  }

  const usableRuns = review.available_runs.filter(
    (r) => r.status === "completed" || r.status === "partial",
  );

  useEffect(() => {
    if (!syncTarget) return;
    if (lastHandledSyncSeqRef.current === syncTarget.seq) return;
    const existsInPage = review.blocks.some((b) => b.block_id === syncTarget.blockId);
    if (!existsInPage) return;

    const isVisible = visibleBlocks.some((b) => b.block_id === syncTarget.blockId);
    if (!isVisible && filterFlagged) {
      setFilterFlagged(false);
      return;
    }

    const scroller = paneBodyRef.current;
    if (!scroller) return;
    const escapedId =
      typeof CSS !== "undefined" && typeof CSS.escape === "function"
        ? CSS.escape(syncTarget.blockId)
        : syncTarget.blockId.replace(/"/g, '\\"');
    const cardEl = scroller.querySelector<HTMLElement>(`[data-block-id="${escapedId}"]`);
    if (!cardEl) return;

    lastHandledSyncSeqRef.current = syncTarget.seq;
    const targetBlk = review.blocks.find((b) => b.block_id === syncTarget.blockId);
    const token = ++syncSeqRef.current;
    setFlashingBlockId(null);
    void scrollIntoViewAsync(cardEl, scroller).then(() => {
      if (syncSeqRef.current !== token) return;
      setFlashingBlockId(syncTarget.blockId);
      setSyncNotice(`Synced editor to line ${(targetBlk?.block_index ?? 0) + 1}.`);
    });
  }, [syncTarget, review.blocks, visibleBlocks, filterFlagged]);

  useEffect(() => {
    if (!flashingBlockId) return;
    const timer = window.setTimeout(() => setFlashingBlockId(null), 1600);
    return () => window.clearTimeout(timer);
  }, [flashingBlockId]);

  return (
    <section
      className="pane"
      aria-label="Telugu review editor"
      onKeyDown={(e) => {
        if (e.nativeEvent.isComposing) return;
        const mod = e.metaKey || e.ctrlKey;
        if (mod && e.key.toLowerCase() === "z" && !e.shiftKey) {
          if (undoStack.length > 0) {
            e.preventDefault();
            void handleUndo();
          }
        } else if (mod && e.key.toLowerCase() === "z" && e.shiftKey) {
          if (redoStack.length > 0) {
            e.preventDefault();
            void handleRedo();
          }
        }
      }}
    >
      <div className="pane-toolbar" role="toolbar" aria-label="Proofreading editor tools">
        <strong>Proofreading Editor</strong>

        {usableRuns.length > 0 && (
          <label className="hint-text" style={{ display: "inline-flex", alignItems: "center", gap: "0.35rem" }}>
            <span>Engine</span>
            <select
              aria-label="Primary OCR engine run"
              className="toolbar-select"
              value={review.primary_run_id ?? ""}
              onChange={(e) => onSelectPrimaryRun(e.target.value)}
            >
              {usableRuns.map((run) => (
                <option key={run.ocr_run_id} value={run.ocr_run_id} title={run.model_id ?? undefined}>
                  {formatEngineLabel(run.engine)}
                </option>
              ))}
            </select>
          </label>
        )}

        <button
          type="button"
          className="btn-compact"
          aria-pressed={filterFlagged}
          onClick={() => setFilterFlagged((v) => !v)}
        >
          Flagged Only ({flaggedCount})
        </button>

        {flaggedCount > 0 && (
          <button
            type="button"
            className="btn-compact"
            title="Jump to the next line with low confidence, engine disagreement, or suggestion"
            onClick={handleJumpNextFlagged}
          >
            Next Issue ▾
          </button>
        )}

        <input
          type="search"
          lang="te"
          className="editor-search-input"
          aria-label="Filter lines on this page"
          placeholder="Filter lines…"
          value={lineSearch}
          onChange={(e) => setLineSearch(e.target.value)}
        />

        <div className="toolbar-group" role="group" aria-label="Telugu text size">
          <button
            type="button"
            className="btn-compact"
            aria-label="Decrease Telugu font size"
            title="Smaller Telugu text"
            onClick={() => setTeluguFontScale((s) => Math.max(0.85, Number((s - 0.15).toFixed(2))))}
          >
            A−
          </button>
          <button
            type="button"
            className="btn-compact"
            aria-label="Increase Telugu font size"
            title="Larger Telugu text"
            onClick={() => setTeluguFontScale((s) => Math.min(1.6, Number((s + 0.15).toFixed(2))))}
          >
            A+
          </button>
        </div>

        {onSyncToScan && (
          <div className="toolbar-group" role="group" aria-label="Scan sync controls">
            <button
              type="button"
              className="btn-compact sync-trigger-btn"
              disabled={!selectedBlockId}
              title="Scroll source scan to the selected line"
              aria-label="Sync to selected block on scan"
              onClick={onSyncToScan}
            >
              ⌖ Sync → Scan
            </button>
            {onToggleAutoSync && (
              <button
                type="button"
                className="btn-compact"
                aria-pressed={autoSync}
                title="Automatically scroll opposite pane when selecting a block"
                onClick={onToggleAutoSync}
              >
                Auto-Sync
              </button>
            )}
          </div>
        )}

        {onToggleKeyboard && (
          <button
            type="button"
            className="btn-compact"
            aria-pressed={keyboardOpen}
            title="Open on-screen Telugu InScript & Phonetic keyboard"
            onClick={onToggleKeyboard}
          >
            ⌨ Keyboard
          </button>
        )}

        <div className="toolbar-group" role="group" aria-label="Edit history">
          <button type="button" className="btn-compact" disabled={undoStack.length === 0} onClick={() => void handleUndo()}>
            Undo
          </button>
          <button type="button" className="btn-compact" disabled={redoStack.length === 0} onClick={() => void handleRedo()}>
            Redo
          </button>
        </div>

        <div style={{ marginInlineStart: "auto", display: "flex", gap: "0.4rem", alignItems: "center" }}>
          <select
            aria-label="Page review status"
            className="toolbar-select"
            value={review.review_status}
            onChange={(e) =>
              void onChangePageStatus(
                e.target.value as "not_started" | "in_review" | "approved" | "needs_attention",
              )
            }
          >
            <option value="not_started">Pending Review</option>
            <option value="in_review">In Review</option>
            <option value="needs_attention">Needs Attention</option>
            <option value="approved">Approved</option>
          </select>
          <button
            type="button"
            className="primary btn-compact"
            onClick={() => void onChangePageStatus("approved")}
          >
            Approve Page
          </button>
        </div>
      </div>

      <p className="visually-hidden" role="status" aria-live="polite">
        {syncNotice}
      </p>

      <div
        ref={paneBodyRef}
        className="pane-body"
        style={{ "--telugu-scale": String(teluguFontScale) } as React.CSSProperties}
      >
        {review.page_kind === "digital_text" && (
          <div className="panel-card" style={{ marginBottom: "0.75rem" }}>
            <div className="badge-row" style={{ marginBottom: "0.5rem" }}>
              <span className="badge ok">Born-Digital Text Path (Not OCR)</span>
            </div>
            <pre className="telugu-text" lang="te" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
              {review.digital_text_content || "(Empty extracted digital text)"}
            </pre>
          </div>
        )}

        {review.page_kind !== "digital_text" && review.blocks.length === 0 && (
          <div className="panel-card" style={{ marginBottom: "0.75rem" }}>
            <p style={{ marginTop: 0 }}>
              <strong>No OCR text extracted for this page yet.</strong>
            </p>
            <p className="hint-text">
              {review.available_runs.length === 0
                ? "Run OCR from the sidebar (or click below) before inspecting or exporting DOCX/TXT."
                : "This page appears blank or had no detected text lines in the selected OCR run."}
            </p>
            {review.available_runs.length === 0 && onQuickStartOcr && (
              <button
                type="button"
                className="primary"
                disabled={ocrRunning}
                onClick={() => void onQuickStartOcr()}
              >
                {ocrRunning ? "OCR Running..." : "Run Selected OCR Now"}
              </button>
            )}
          </div>
        )}

        {visibleBlocks.map((block) => (
          <ReviewBlockCard
            key={block.block_id}
            block={block}
            draftText={drafts[block.block_id] ?? block.current_text}
            isSelected={block.block_id === selectedBlockId}
            isFlashing={block.block_id === flashingBlockId}
            isBusy={busyBlockId === block.block_id}
            remember={Boolean(rememberByBlock[block.block_id])}
            scope={scopeByBlock[block.block_id] ?? "book_only"}
            correctionType={typeByBlock[block.block_id] ?? ""}
            primaryEngine={review.primary_engine}
            comparatorEngine={review.comparator_engine}
            onSelectBlock={onSelectBlock}
            onLocateBlockOnScan={onLocateBlockOnScan}
            onDraftChange={handleDraftChange}
            onRememberChange={handleRememberChange}
            onScopeChange={handleScopeChange}
            onTypeChange={handleTypeChange}
            onCommitEdit={commitEdit}
            onAcceptSuggestion={onAcceptSuggestion}
            onRejectSuggestion={onRejectSuggestion}
          />
        ))}
      </div>
    </section>
  );
}
