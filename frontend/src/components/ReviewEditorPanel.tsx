import { memo, useCallback, useEffect, useRef, useState } from "react";
import type {
  AutocorrectChangeItem,
  BatchBlockEditPayload,
  BlockRole,
  CorrectionSuggestionItem,
  PageAutocorrectResponse,
  PageReviewPayload,
  ReviewBlock,
} from "../types/api";
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
  blockRole?: BlockRole;
}

function formatAutocorrectSource(source: string): string {
  if (source === "correction_memory") return "Memory";
  if (source === "sentence_context") return "Context";
  return "Dictionary";
}

interface ReviewBlockCardProps {
  block: ReviewBlock;
  draftText: string;
  role: BlockRole;
  isSelected: boolean;
  isFlashing: boolean;
  isBusy: boolean;
  remember: boolean;
  scope: "book_only" | "global_suggestion";
  correctionType: string;
  autoCorrectChanges?: AutocorrectChangeItem[];
  primaryEngine: string | null;
  comparatorEngine: string | null;
  onSelectBlock: (blockId: string) => void;
  onLocateBlockOnScan?: (blockId: string) => void;
  onLookupWord?: (word: string) => void;
  onDraftChange: (blockId: string, value: string) => void;
  onRoleChange: (blockId: string, role: BlockRole) => void;
  onRememberChange: (blockId: string, checked: boolean) => void;
  onScopeChange: (blockId: string, scope: "book_only" | "global_suggestion") => void;
  onTypeChange: (blockId: string, cType: string) => void;
  onCommitEdit: (
    block: ReviewBlock,
    nextText: string,
    action: "corrected" | "approved" | "reverted" | "ignored",
    pushHistory?: boolean,
    overrideRole?: BlockRole,
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
  role,
  isSelected,
  isFlashing,
  isBusy,
  remember,
  scope,
  correctionType,
  autoCorrectChanges,
  primaryEngine,
  comparatorEngine,
  onSelectBlock,
  onLocateBlockOnScan,
  onLookupWord,
  onDraftChange,
  onRoleChange,
  onRememberChange,
  onScopeChange,
  onTypeChange,
  onCommitEdit,
  onAcceptSuggestion,
  onRejectSuggestion,
}: ReviewBlockCardProps) {
  const isDirty = draftText !== block.current_text || role !== (block.block_role ?? "paragraph");
  const isFlagged =
    block.low_confidence_flag || block.disagreement_flag || block.short_or_empty_flag;
  const isIgnored = block.latest_action === "ignored" || role === "ignore";

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
        {autoCorrectChanges && autoCorrectChanges.length > 0 && (
          <span className="badge autocorr-badge">
            ✨ {autoCorrectChanges.length} Auto-Fix(es)
          </span>
        )}
        {block.is_edited && <span className="badge ok">✓ Edited</span>}
        {block.latest_action === "approved" && (
          <span className="badge ok">✓ Block Approved</span>
        )}
        {isIgnored && <span className="badge warn">✕ Ignored in Export</span>}
        {role !== "paragraph" && role !== "ignore" && (
          <span className="badge">{role === "heading_1" ? "H1" : role === "heading_2" ? "H2" : "Verse"}</span>
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

      {autoCorrectChanges && autoCorrectChanges.length > 0 && (
        <div className="autocorrect-preview-box" aria-label="Proposed auto-corrections">
          <strong style={{ fontSize: "0.8rem" }}>Auto-Correct Draft Preview (review before saving)</strong>
          <div className="badge-row">
            {autoCorrectChanges.map((chg, idx) => (
              <span
                key={`${chg.original}-${chg.replacement}-${idx}`}
                className="autocorrect-chip"
                title={chg.reason}
              >
                <span className="telugu-text" lang="te">
                  {chg.original} → <strong>{chg.replacement}</strong>
                </span>
                <span className="autocorrect-meta">
                  {formatAutocorrectSource(chg.source)} · {Math.round(chg.confidence * 100)}%
                </span>
              </span>
            ))}
          </div>
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
          if (e.nativeEvent.isComposing) return;
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
        <select
          aria-label={`Layout role for line ${block.block_index + 1}`}
          className="toolbar-select"
          value={role}
          disabled={isBusy}
          onChange={(e) => onRoleChange(block.block_id, e.target.value as BlockRole)}
        >
          <option value="paragraph">Paragraph</option>
          <option value="heading_1">Heading 1 (TOC)</option>
          <option value="heading_2">Heading 2 (TOC)</option>
          <option value="verse">Verse / Stanza</option>
          <option value="ignore">Ignore / Noise</option>
        </select>
        {!isIgnored && (
          <button
            type="button"
            disabled={isBusy}
            title="Mark this bounding box as margin noise or artifact so it is excluded from DOCX/TXT exports"
            onClick={() => {
              onRoleChange(block.block_id, "ignore");
              void onCommitEdit(block, draftText, "ignored", false, "ignore");
            }}
          >
            Ignore Box
          </button>
        )}
        {onLookupWord && (
          <button
            type="button"
            className="btn-compact"
            title="Look up selected Telugu word (or first Telugu word in this line) in the Telugu Dictionary"
            onClick={(e) => {
              e.stopPropagation();
              const textarea = document.getElementById(
                `block-input-${block.block_id}`,
              ) as HTMLTextAreaElement | null;
              let targetWord = "";
              if (textarea && textarea.selectionStart !== textarea.selectionEnd) {
                targetWord = textarea.value
                  .slice(textarea.selectionStart, textarea.selectionEnd)
                  .trim();
              }
              if (!targetWord) {
                const match = draftText.match(/[\u0C01-\u0C63\u0C78-\u0C7F]{2,}/);
                targetWord = match ? match[0] : draftText.trim().split(/\s+/)[0] || "";
              }
              if (targetWord) {
                onLookupWord(targetWord);
              }
            }}
          >
            📚 Dictionary
          </button>
        )}
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
  onLookupWord?: (word: string) => void;
  onSyncToScan?: () => void;
  onToggleAutoSync?: () => void;
  onToggleKeyboard?: () => void;
  onSelectPrimaryRun: (runId: string) => void;
  onQuickStartOcr?: () => Promise<void>;
  onSaveEdit: (
    blockId: string,
    editedText: string,
    action: "corrected" | "approved" | "reverted" | "ignored",
    reviewNote?: string,
    options?: SaveEditOptions,
  ) => Promise<void>;
  onAddManualBlock?: (text: string, blockRole: BlockRole) => Promise<void>;
  onSaveDigitalText?: (text: string) => Promise<void>;
  onBatchApproveUnflagged?: () => Promise<void>;
  onAutocorrectPage?: (
    currentTexts: Record<string, string>,
  ) => Promise<PageAutocorrectResponse | null>;
  onBatchSaveAndApprovePage?: (edits: BatchBlockEditPayload[]) => Promise<void>;
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
  onLookupWord,
  onSyncToScan,
  onToggleAutoSync,
  onToggleKeyboard,
  onSelectPrimaryRun,
  onQuickStartOcr,
  onSaveEdit,
  onAddManualBlock,
  onSaveDigitalText,
  onBatchApproveUnflagged,
  onAutocorrectPage,
  onBatchSaveAndApprovePage,
  onAcceptSuggestion,
  onRejectSuggestion,
  onChangePageStatus,
}: ReviewEditorPanelProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [roleByBlock, setRoleByBlock] = useState<Record<string, BlockRole>>({});
  const [rememberByBlock, setRememberByBlock] = useState<Record<string, boolean>>({});
  const [scopeByBlock, setScopeByBlock] = useState<Record<string, "book_only" | "global_suggestion">>({});
  const [typeByBlock, setTypeByBlock] = useState<Record<string, string>>({});
  const [autoCorrectByBlock, setAutoCorrectByBlock] = useState<Record<string, AutocorrectChangeItem[]>>({});
  const [autoCorrectSnapshot, setAutoCorrectSnapshot] = useState<Record<string, string> | null>(null);
  const [busyAutocorrect, setBusyAutocorrect] = useState(false);
  const [busyBatchApprove, setBusyBatchApprove] = useState(false);
  const [filterFlagged, setFilterFlagged] = useState(false);
  const [lineSearch, setLineSearch] = useState("");
  const [teluguFontScale, setTeluguFontScale] = useState(1.0);
  const [undoStack, setUndoStack] = useState<UndoEntry[]>([]);
  const [redoStack, setRedoStack] = useState<UndoEntry[]>([]);
  const [flashingBlockId, setFlashingBlockId] = useState<string | null>(null);
  const [syncNotice, setSyncNotice] = useState<string>("");
  const [showAddManualLine, setShowAddManualLine] = useState(false);
  const [manualLineText, setManualLineText] = useState("");
  const [manualLineRole, setManualLineRole] = useState<BlockRole>("paragraph");
  const [digitalDraft, setDigitalDraft] = useState<string>(review.digital_text_content ?? "");
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
    setRoleByBlock(() => {
      const nextRoles: Record<string, BlockRole> = {};
      for (const blk of review.blocks) {
        nextRoles[blk.block_id] = blk.block_role ?? "paragraph";
      }
      return nextRoles;
    });
    setDigitalDraft(review.digital_text_content ?? "");
  }, [review.book_id, review.page_number, review.primary_run_id, review.blocks, review.digital_text_content]);

  const handleDraftChange = useCallback((blockId: string, value: string) => {
    setDrafts((prev) => ({ ...prev, [blockId]: value }));
  }, []);

  const handleRoleChange = useCallback((blockId: string, role: BlockRole) => {
    setRoleByBlock((prev) => ({ ...prev, [blockId]: role }));
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
    setAutoCorrectByBlock({});
    setAutoCorrectSnapshot(null);
    setRememberByBlock({});
  }, [review.book_id, review.page_number, review.primary_run_id]);

  async function commitEdit(
    block: ReviewBlock,
    nextText: string,
    action: "corrected" | "approved" | "reverted" | "ignored",
    pushHistory = true,
    overrideRole?: BlockRole,
  ) {
    const prevText = block.current_text;
    const addMem = action === "corrected" && (rememberByBlock[block.block_id] ?? true);
    const scope = scopeByBlock[block.block_id] ?? "book_only";
    const cType = typeByBlock[block.block_id] || undefined;
    const effectiveRole = overrideRole ?? roleByBlock[block.block_id] ?? block.block_role;
    const opts: SaveEditOptions = {
      addToMemory: addMem,
      memoryScope: scope,
      correctionType: cType,
    };
    if (
      (effectiveRole && effectiveRole !== "paragraph") ||
      (block.block_role && block.block_role !== "paragraph" && effectiveRole === "paragraph")
    ) {
      opts.blockRole = effectiveRole;
    }

    await onSaveEdit(block.block_id, nextText, action, undefined, opts);
    setAutoCorrectByBlock((prev) => {
      if (!(block.block_id in prev)) return prev;
      const next = { ...prev };
      delete next[block.block_id];
      return next;
    });
    if (pushHistory && prevText !== nextText) {
      setUndoStack((prev) => [...prev, { blockId: block.block_id, previousText: prevText, nextText }]);
      setRedoStack([]);
    }
  }

  const dirtyBlocks = review.blocks.filter((b) => {
    const draftVal = drafts[b.block_id] ?? b.current_text;
    const roleVal = roleByBlock[b.block_id] ?? b.block_role ?? "paragraph";
    return draftVal !== b.current_text || roleVal !== (b.block_role ?? "paragraph");
  });

  async function handleRunAutocorrect() {
    if (!onAutocorrectPage || review.blocks.length === 0) return;
    setBusyAutocorrect(true);
    try {
      const currentTexts: Record<string, string> = {};
      for (const b of review.blocks) {
        currentTexts[b.block_id] = drafts[b.block_id] ?? b.current_text;
      }
      const res = await onAutocorrectPage(currentTexts);
      if (!res || res.blocks.length === 0) {
        setSyncNotice(`No auto-corrections suggested on page ${review.page_number}.`);
        return;
      }
      setAutoCorrectSnapshot((prev) => prev ?? { ...currentTexts });
      const nextDrafts = { ...currentTexts };
      const nextChanges: Record<string, AutocorrectChangeItem[]> = {};
      for (const prop of res.blocks) {
        nextDrafts[prop.block_id] = prop.proposed_text;
        nextChanges[prop.block_id] = prop.changes;
      }
      setDrafts(nextDrafts);
      setAutoCorrectByBlock(nextChanges);
      setSyncNotice(
        `Auto-corrected ${res.changed_blocks_count} line(s) (${res.total_changes_count} fix(es)) into drafts for review.`,
      );
    } finally {
      setBusyAutocorrect(false);
    }
  }

  function handleRevertAutocorrect() {
    if (!autoCorrectSnapshot) return;
    setDrafts(autoCorrectSnapshot);
    setAutoCorrectByBlock({});
    setAutoCorrectSnapshot(null);
    setSyncNotice("Reverted uncommitted auto-corrections.");
  }

  async function handleApproveEntirePage() {
    if (!onBatchSaveAndApprovePage) {
      await onChangePageStatus("approved");
      return;
    }
    setBusyBatchApprove(true);
    try {
      const edits: BatchBlockEditPayload[] = dirtyBlocks.map((b) => {
        const draftVal = drafts[b.block_id] ?? b.current_text;
        const roleVal = roleByBlock[b.block_id] ?? b.block_role ?? "paragraph";
        const isTextChanged = draftVal !== b.current_text;
        const hasAutoChanges = Boolean(autoCorrectByBlock[b.block_id]?.length);
        return {
          block_id: b.block_id,
          edited_text: draftVal,
          action: roleVal === "ignore" ? "ignored" : isTextChanged ? "corrected" : "approved",
          block_role: roleVal,
          add_to_correction_memory: isTextChanged ? (rememberByBlock[b.block_id] ?? true) : false,
          memory_scope: scopeByBlock[b.block_id] ?? "book_only",
          correction_type: typeByBlock[b.block_id] || undefined,
          review_note: hasAutoChanges ? "Auto-correct reviewed & batch-approved" : undefined,
        };
      });
      await onBatchSaveAndApprovePage(edits);
      setAutoCorrectByBlock({});
      setAutoCorrectSnapshot(null);
      setSyncNotice(
        edits.length > 0
          ? `Saved ${edits.length} edited line(s) and approved page ${review.page_number}.`
          : `Approved page ${review.page_number}.`,
      );
    } finally {
      setBusyBatchApprove(false);
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
  const selectedRun =
    review.available_runs.find((r) => r.ocr_run_id === review.primary_run_id) ?? null;
  const alternatePopulatedRun =
    usableRuns.find(
      (r) => r.ocr_run_id !== review.primary_run_id && ((r.progress_current ?? 0) > 0 || r.status === "completed"),
    ) ?? null;

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
                  {run.status === "partial"
                    ? ` (partial ${run.progress_current ?? 0}/${run.progress_total ?? "?"})`
                    : ""}
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

        <div style={{ marginInlineStart: "auto", display: "flex", gap: "0.4rem", alignItems: "center", flexWrap: "wrap" }}>
          {onAutocorrectPage && review.page_kind !== "digital_text" && review.blocks.length > 0 && (
            <button
              type="button"
              className="btn-compact autocorr-btn"
              disabled={busyAutocorrect || busyBatchApprove}
              title="Propose Telugu OCR fixes using Correction Memory, Telugu Dictionary, and sentence context (review before saving)"
              onClick={() => void handleRunAutocorrect()}
            >
              {busyAutocorrect ? "Auto-Correcting…" : "✨ Auto-Correct Page"}
            </button>
          )}
          {autoCorrectSnapshot && (
            <button
              type="button"
              className="btn-compact"
              disabled={busyBatchApprove}
              title="Discard uncommitted auto-corrections and restore previous drafts"
              onClick={handleRevertAutocorrect}
            >
              ↩ Revert Auto-Correct
            </button>
          )}
          {onAddManualBlock && review.page_kind !== "digital_text" && (
            <button
              type="button"
              className="btn-compact"
              aria-pressed={showAddManualLine}
              onClick={() => setShowAddManualLine((v) => !v)}
            >
              ＋ Add Line
            </button>
          )}
          {onBatchApproveUnflagged && review.blocks.length > 0 && (
            <button
              type="button"
              className="btn-compact"
              title="Approve all unflagged blocks on this page"
              onClick={() => void onBatchApproveUnflagged()}
            >
              Approve Unflagged
            </button>
          )}
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
            disabled={busyBatchApprove || busyAutocorrect}
            title={
              dirtyBlocks.length > 0
                ? `Save all ${dirtyBlocks.length} edited line(s), update correction memory, and approve the entire page`
                : "Approve all remaining lines and mark this page Approved"
            }
            onClick={() => void handleApproveEntirePage()}
          >
            {busyBatchApprove
              ? "Saving & Approving…"
              : onBatchSaveAndApprovePage && dirtyBlocks.length > 0
                ? `Save All (${dirtyBlocks.length}) & Approve Page`
                : "Approve Page"}
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
        {showAddManualLine && onAddManualBlock && (
          <div className="panel-card" style={{ marginBottom: "0.75rem" }}>
            <div className="badge-row" style={{ marginBottom: "0.45rem", justifyContent: "space-between" }}>
              <strong>Insert Missed Telugu Line</strong>
              <select
                aria-label="New line layout role"
                className="toolbar-select"
                value={manualLineRole}
                onChange={(e) => setManualLineRole(e.target.value as BlockRole)}
              >
                <option value="paragraph">Paragraph</option>
                <option value="heading_1">Heading 1 (TOC)</option>
                <option value="heading_2">Heading 2 (TOC)</option>
                <option value="verse">Verse / Stanza</option>
              </select>
            </div>
            <textarea
              lang="te"
              className="block-textarea"
              aria-label="Manual Telugu line text"
              placeholder="Type missed Telugu line…"
              value={manualLineText}
              onChange={(e) => setManualLineText(e.target.value)}
            />
            <div className="badge-row" style={{ marginTop: "0.45rem" }}>
              <button
                type="button"
                className="primary"
                disabled={!manualLineText.trim()}
                onClick={async () => {
                  await onAddManualBlock(manualLineText.trim(), manualLineRole);
                  setManualLineText("");
                  setShowAddManualLine(false);
                }}
              >
                Insert Line
              </button>
              <button
                type="button"
                onClick={() => setShowAddManualLine(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {review.page_kind === "digital_text" && (
          <div className="panel-card" style={{ marginBottom: "0.75rem" }}>
            <div className="badge-row" style={{ marginBottom: "0.5rem", justifyContent: "space-between" }}>
              <span className="badge ok">Born-Digital Text Path (Not OCR)</span>
              {onSaveDigitalText && (
                <button
                  type="button"
                  className="primary btn-compact"
                  disabled={digitalDraft === (review.digital_text_content ?? "")}
                  onClick={() => void onSaveDigitalText(digitalDraft)}
                >
                  Save Digital Text
                </button>
              )}
            </div>
            {onSaveDigitalText ? (
              <textarea
                lang="te"
                aria-label="Born-digital page text"
                className="block-textarea"
                rows={8}
                value={digitalDraft}
                onChange={(e) => setDigitalDraft(e.target.value)}
              />
            ) : (
              <pre className="telugu-text" lang="te" style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                {review.digital_text_content || "(Empty extracted digital text)"}
              </pre>
            )}
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
                : selectedRun && (selectedRun.status === "partial" || selectedRun.status === "failed") && (selectedRun.progress_current ?? 0) === 0
                  ? `${formatEngineLabel(selectedRun.engine)} stopped before processing this page (${selectedRun.error_summary || "0 pages completed"}).`
                  : "This page appears blank or had no detected text lines in the selected OCR run."}
            </p>
            <div className="badge-row">
              {alternatePopulatedRun && (
                <button
                  type="button"
                  className="primary"
                  onClick={() => onSelectPrimaryRun(alternatePopulatedRun.ocr_run_id)}
                >
                  Switch to {formatEngineLabel(alternatePopulatedRun.engine)}
                </button>
              )}
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
          </div>
        )}

        {visibleBlocks.map((block) => (
          <ReviewBlockCard
            key={block.block_id}
            block={block}
            draftText={drafts[block.block_id] ?? block.current_text}
            role={roleByBlock[block.block_id] ?? block.block_role ?? "paragraph"}
            isSelected={block.block_id === selectedBlockId}
            isFlashing={block.block_id === flashingBlockId}
            isBusy={busyBlockId === block.block_id || busyBatchApprove}
            remember={rememberByBlock[block.block_id] ?? true}
            scope={scopeByBlock[block.block_id] ?? "book_only"}
            correctionType={typeByBlock[block.block_id] ?? ""}
            autoCorrectChanges={autoCorrectByBlock[block.block_id]}
            primaryEngine={review.primary_engine}
            comparatorEngine={review.comparator_engine}
            onSelectBlock={onSelectBlock}
            onLocateBlockOnScan={onLocateBlockOnScan}
            onLookupWord={onLookupWord}
            onDraftChange={handleDraftChange}
            onRoleChange={handleRoleChange}
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
