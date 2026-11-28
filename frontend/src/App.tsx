import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiClientError,
  approveCorrection,
  autocorrectPage,
  batchSavePage,
  cancelOcrRun,
  createManualPageBlock,
  getHostCapabilities,
  getOcrRunStatus,
  getPageReview,
  listBookOcrRuns,
  listBookPages,
  listBooks,
  rejectCorrection,
  resumeOcrRun,
  startOcrRun,
  submitBlockEdit,
  updatePageDigitalText,
  updatePageReviewStatus,
  uploadBook,
} from "./api/client";
import { BookUploadForm } from "./components/BookUploadForm";
import { CorrectionMemoryPanel } from "./components/CorrectionMemoryPanel";
import { DictionaryPanel } from "./components/DictionaryPanel";
import { ExportPanel } from "./components/ExportPanel";
import { QuickLookupDialog } from "./components/QuickLookupDialog";
import {
  HeaderOcrStatusPill,
  OcrProgressStrip,
  mergeBookRunsWithLiveStatuses,
} from "./components/OcrStatusBar";
import { ReviewEditorPanel, type SaveEditOptions } from "./components/ReviewEditorPanel";
import { SourcePageViewer } from "./components/SourcePageViewer";
import {
  CommitmentBar,
  OverviewPanel,
  WelcomeHero,
} from "./components/StudioChrome";
import { TeluguKeyboard } from "./components/TeluguKeyboard";
import type {
  BatchBlockEditPayload,
  BlockRole,
  BookOCRRunSummary,
  BookSummary,
  CorrectionSuggestionItem,
  HostCapabilities,
  OCRRunStatus,
  PageAutocorrectResponse,
  PageReviewPayload,
  PageSummary,
  ReviewBlock,
} from "./types/api";
import { formatEngineLabel, formatPageKind, formatReviewStatus } from "./utils/formatters";
import {
  type EditableTextElement,
  backspaceAtCursor,
  insertTextAtCursor,
  isEditableTextElement,
} from "./utils/teluguInput";

export function App() {
  const [books, setBooks] = useState<BookSummary[]>([]);
  const [selectedBookId, setSelectedBookId] = useState<string | null>(null);
  const [pages, setPages] = useState<PageSummary[]>([]);
  const [selectedPageNumber, setSelectedPageNumber] = useState<number>(1);
  const [runs, setRuns] = useState<BookOCRRunSummary[]>([]);
  const [liveStatuses, setLiveStatuses] = useState<Record<string, OCRRunStatus>>({});
  const [selectedPrimaryRunId, setSelectedPrimaryRunId] = useState<string | null>(null);
  const [review, setReview] = useState<PageReviewPayload | null>(null);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [autoSyncBlocks, setAutoSyncBlocks] = useState(false);
  const [autoAdvancePage, setAutoAdvancePage] = useState(true);
  const [quickLookupWord, setQuickLookupWord] = useState<string | null>(null);
  const [syncRequest, setSyncRequest] = useState<{
    target: "scan" | "editor";
    blockId: string;
    seq: number;
  } | null>(null);
  const syncSeqCounterRef = useRef(0);
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  const lastEditableRef = useRef<EditableTextElement | null>(null);
  const [keyboardTargetLabel, setKeyboardTargetLabel] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"review" | "dictionary" | "memory" | "export">(() => {
    if (typeof window !== "undefined") {
      const viewParam = new URLSearchParams(window.location.search).get("view");
      if (viewParam === "dictionary" || viewParam === "memory" || viewParam === "export") {
        return viewParam;
      }
    }
    return "review";
  });
  const [dictionaryQuery, setDictionaryQuery] = useState<string | null>(() => {
    if (typeof window !== "undefined") {
      return new URLSearchParams(window.location.search).get("q");
    }
    return null;
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (activeView === "review") {
      url.searchParams.delete("view");
    } else {
      url.searchParams.set("view", activeView);
    }
    if (activeView !== "dictionary") {
      url.searchParams.delete("q");
    }
    window.history.replaceState({}, "", url.toString());
  }, [activeView]);

  const [uploadExpanded, setUploadExpanded] = useState(true);
  const initializedCollapseRef = useRef(false);
  const [pageFilter, setPageFilter] = useState<"all" | "pending" | "approved">("all");

  const [usePaddle, setUsePaddle] = useState(true);
  const [useTesseract, setUseTesseract] = useState(true);
  const [capabilities, setCapabilities] = useState<HostCapabilities | null>(null);
  const [ocrStartPage, setOcrStartPage] = useState("1");
  const [ocrEndPage, setOcrEndPage] = useState("");
  const [ocrPreprocessing, setOcrPreprocessing] = useState<"none" | "deskew" | "contrast_clahe">("none");
  const [ocrRenderDpi, setOcrRenderDpi] = useState<number>(300);
  const [ocrForceRerun, setOcrForceRerun] = useState<boolean>(false);
  const [ocrIncludeDigital, setOcrIncludeDigital] = useState<boolean>(false);
  const [busyUpload, setBusyUpload] = useState(false);
  const [busyBlockId, setBusyBlockId] = useState<string | null>(null);
  const [banner, setBanner] = useState<{ kind: "info" | "success" | "error"; text: string } | null>(
    null,
  );

  const prevProgressRef = useRef<Record<string, { progress: number; status: string }>>({});
  const selectedPageNumberRef = useRef(selectedPageNumber);
  selectedPageNumberRef.current = selectedPageNumber;
  const selectedPrimaryRunIdRef = useRef(selectedPrimaryRunId);
  selectedPrimaryRunIdRef.current = selectedPrimaryRunId;
  const reviewBlocksCountRef = useRef(0);
  reviewBlocksCountRef.current = review?.blocks.length ?? 0;

  const reviewBookId = review?.book_id;
  const reviewPageCount = review?.page_count;
  useEffect(() => {
    if (reviewBookId && reviewPageCount) {
      setOcrStartPage("1");
      setOcrEndPage(String(reviewPageCount));
    } else {
      setOcrStartPage("1");
      setOcrEndPage("");
    }
  }, [reviewBookId, reviewPageCount]);

  useEffect(() => {
    setLiveStatuses({});
    prevProgressRef.current = {};
  }, [selectedBookId]);

  const handleStatusBanner = useCallback(
    (kind: "info" | "success" | "error", text: string) => {
      setBanner({ kind, text });
    },
    [],
  );

  const refreshBooks = useCallback(async () => {
    const items = await listBooks();
    setBooks(items);
    if (!initializedCollapseRef.current) {
      initializedCollapseRef.current = true;
      if (items.length > 0) {
        setUploadExpanded(false);
      }
    }
    if (items.length > 0 && (!selectedBookId || !items.some((b) => b.book_id === selectedBookId))) {
      setSelectedBookId(items[0].book_id);
      setSelectedPageNumber(1);
    } else if (items.length === 0) {
      setSelectedBookId(null);
      setPages([]);
      setRuns([]);
      setReview(null);
      setUploadExpanded(true);
    }
  }, [selectedBookId]);

  const refreshBookDetail = useCallback(async (bookId: string) => {
    const [pageList, runList] = await Promise.all([listBookPages(bookId), listBookOcrRuns(bookId)]);
    setPages(pageList);
    setRuns(runList);
  }, []);

  const refreshReview = useCallback(
    async (bookId: string, pageNumber: number, primaryRunId?: string | null) => {
      const payload = await getPageReview(bookId, pageNumber, primaryRunId);
      setReview(payload);
    },
    [],
  );

  useEffect(() => {
    refreshBooks().catch((err) => {
      setBanner({ kind: "error", text: err instanceof Error ? err.message : "Failed to load books." });
    });
    getHostCapabilities()
      .then((caps) => {
        setCapabilities(caps);
        if (caps.engines.paddle_ppocrv5_te && !caps.engines.paddle_ppocrv5_te.available) {
          setUsePaddle(false);
        }
        if (caps.engines.tesseract_tel_best && !caps.engines.tesseract_tel_best.available) {
          setUseTesseract(false);
        }
      })
      .catch(() => {
        // Optional capabilities check; keep defaults if endpoint unavailable.
      });
  }, [refreshBooks]);

  useEffect(() => {
    if (!selectedBookId) return;
    refreshBookDetail(selectedBookId).catch((err) => {
      setBanner({ kind: "error", text: err instanceof Error ? err.message : "Failed to load book." });
    });
  }, [selectedBookId, refreshBookDetail]);

  useEffect(() => {
    if (!selectedBookId) return;
    refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId).catch((err) => {
      setBanner({
        kind: "error",
        text: err instanceof Error ? err.message : "Failed to load page review.",
      });
    });
  }, [selectedBookId, selectedPageNumber, selectedPrimaryRunId, refreshReview]);

  const mergedRuns = useMemo(
    () => mergeBookRunsWithLiveStatuses(runs, liveStatuses),
    [runs, liveStatuses],
  );

  const activeRunIds = useMemo(
    () =>
      mergedRuns
        .filter((r) => r.status === "running" || r.status === "queued")
        .map((r) => r.ocr_run_id)
        .sort(),
    [mergedRuns],
  );
  const activeRunIdsKey = activeRunIds.join(",");
  const isOcrRunning = activeRunIds.length > 0;

  useEffect(() => {
    if (!activeRunIdsKey || !selectedBookId) return;
    const currentBookId = selectedBookId;
    const ids = activeRunIdsKey.split(",").filter(Boolean);
    let cancelled = false;
    let timerId: number | undefined;

    async function pollLoop() {
      try {
        const fetched = await Promise.all(ids.map((id) => getOcrRunStatus(id)));
        if (cancelled) return;

        setLiveStatuses((prev) => {
          const nextMap = { ...prev };
          for (const st of fetched) {
            nextMap[st.ocr_run_id] = st;
          }
          return nextMap;
        });

        let shouldRefreshBookDetail = false;
        let shouldRefreshCurrentPageReview = false;
        let finishedRun: OCRRunStatus | null = null;
        for (const st of fetched) {
          const prevEntry = prevProgressRef.current[st.ocr_run_id];
          const advanced = Boolean(prevEntry && st.progress_current > prevEntry.progress);
          const becameTerminal =
            st.status === "completed" ||
            st.status === "partial" ||
            st.status === "failed" ||
            st.status === "cancelled";
          const periodicRefresh =
            advanced &&
            (st.progress_current === 1 ||
              (st.progress_total > 0 && st.progress_current >= st.progress_total) ||
              st.progress_current % 4 === 0);
          if (becameTerminal || periodicRefresh) {
            shouldRefreshBookDetail = true;
          }
          if (
            becameTerminal ||
            (advanced && reviewBlocksCountRef.current === 0)
          ) {
            shouldRefreshCurrentPageReview = true;
          }
          if (becameTerminal && (!prevEntry || prevEntry.status !== st.status)) {
            finishedRun = st;
          }
          prevProgressRef.current[st.ocr_run_id] = {
            progress: st.progress_current,
            status: st.status,
          };
        }

        if (shouldRefreshBookDetail && !cancelled) {
          await refreshBookDetail(currentBookId);
        }
        if (shouldRefreshCurrentPageReview && !cancelled) {
          await refreshReview(
            currentBookId,
            selectedPageNumberRef.current,
            selectedPrimaryRunIdRef.current,
          );
        }
        if (finishedRun && !cancelled) {
          const isZeroPartial =
            finishedRun.status === "partial" && (finishedRun.progress_current ?? 0) === 0;
          setBanner({
            kind:
              finishedRun.status === "failed" || isZeroPartial
                ? "error"
                : finishedRun.status === "partial" || finishedRun.status === "cancelled"
                  ? "info"
                  : "success",
            text: `${formatEngineLabel(finishedRun.engine)} ${finishedRun.status} (${finishedRun.progress_current}/${finishedRun.progress_total} pages)${finishedRun.error_summary ? `: ${finishedRun.error_summary}` : "."}`,
          });
        }
      } catch {
        // Ignore transient polling hiccups.
      } finally {
        if (!cancelled) {
          timerId = window.setTimeout(() => void pollLoop(), 1500);
        }
      }
    }

    void pollLoop();
    return () => {
      cancelled = true;
      if (timerId !== undefined) {
        window.clearTimeout(timerId);
      }
    };
  }, [activeRunIdsKey, selectedBookId, refreshBookDetail, refreshReview]);

  async function handleUpload(formData: FormData) {
    setBusyUpload(true);
    try {
      const res = await uploadBook(formData);
      await refreshBooks();
      setSelectedBookId(res.book_id);
      setSelectedPageNumber(1);
      setSelectedPrimaryRunId(null);
      setActiveView("review");
      setUploadExpanded(false);
      setBanner({
        kind: "success",
        text: res.duplicate
          ? `Book "${res.title}" matched existing SHA-256 (${res.page_count} pages).`
          : `Imported "${res.title}" (${res.page_count} pages at 300 DPI). Ready for OCR.`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Upload failed.",
      });
    } finally {
      setBusyUpload(false);
    }
  }

  const selectedBook = books.find((b) => b.book_id === selectedBookId) ?? null;

  async function handleStartOcr(preset?: "sample_5" | "full") {
    if (!selectedBookId) return;
    const engines: string[] = [];
    if (usePaddle) engines.push("paddle_ppocrv5_te");
    if (useTesseract) engines.push("tesseract_tel_best");
    if (engines.length === 0) {
      setBanner({ kind: "error", text: "Select at least one OCR engine." });
      return;
    }

    const totalPages = selectedBook?.page_count ?? review?.page_count ?? 0;
    let pageRange: { start: number; end: number } | null = null;

    if (preset === "sample_5") {
      const endSample = Math.min(5, totalPages || 5);
      setOcrStartPage("1");
      setOcrEndPage(String(endSample));
      pageRange = totalPages > 0 && endSample === totalPages ? null : { start: 1, end: endSample };
    } else if (preset === "full") {
      setOcrStartPage("1");
      if (totalPages > 0) setOcrEndPage(String(totalPages));
      pageRange = null;
    } else {
      const startVal = ocrStartPage.trim() === "" ? 1 : Number(ocrStartPage.trim());
      const endVal =
        ocrEndPage.trim() === "" ? totalPages || startVal : Number(ocrEndPage.trim());
      if (
        !Number.isInteger(startVal) ||
        !Number.isInteger(endVal) ||
        startVal < 1 ||
        endVal < startVal ||
        (totalPages > 0 && endVal > totalPages)
      ) {
        setBanner({
          kind: "error",
          text:
            totalPages > 0
              ? `Enter a valid OCR page range between 1 and ${totalPages}.`
              : "Enter a valid OCR page range.",
        });
        return;
      }
      pageRange =
        totalPages > 0 && startVal === 1 && endVal === totalPages
          ? null
          : { start: startVal, end: endVal };
    }

    try {
      const created = await startOcrRun(selectedBookId, engines, {
        pageRange,
        renderDpi: ocrRenderDpi !== 300 ? ocrRenderDpi : undefined,
        preprocessingProfile: ocrPreprocessing !== "none" ? ocrPreprocessing : undefined,
        forceRerun: ocrForceRerun || undefined,
        includeDigitalTextPages: ocrIncludeDigital ? true : undefined,
      });
      const runIdsToFetch = created.ocr_run_ids.length > 0 ? created.ocr_run_ids : [created.ocr_run_id];
      const fetchedStatuses = await Promise.all(runIdsToFetch.map((id) => getOcrRunStatus(id)));
      setLiveStatuses((prev) => {
        const nextMap = { ...prev };
        for (const st of fetchedStatuses) {
          nextMap[st.ocr_run_id] = st;
        }
        return nextMap;
      });
      await refreshBookDetail(selectedBookId);
      if (created.reused_existing) {
        await refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId);
        setBanner({ kind: "info", text: "Reused existing completed OCR run." });
      } else {
        const engineNames = engines.map((e) => formatEngineLabel(e)).join(" + ");
        setBanner({
          kind: "info",
          text: `Started OCR (${engineNames}) for ${created.pages_total} scanned page(s)${
            pageRange ? ` (pages ${pageRange.start}–${pageRange.end})` : ""
          }.`,
        });
      }
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to start OCR.",
      });
    }
  }

  async function handleResumeRun(runId: string) {
    try {
      const resumed = await resumeOcrRun(runId);
      setLiveStatuses((prev) => ({ ...prev, [resumed.ocr_run_id]: resumed }));
      if (selectedBookId) {
        await refreshBookDetail(selectedBookId);
      }
      setBanner({
        kind: "info",
        text: `Resumed ${formatEngineLabel(resumed.engine)} from ${resumed.progress_current}/${resumed.progress_total} pages.`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Resume failed.",
      });
    }
  }

  async function handleCancelRun(runId: string) {
    try {
      const cancelled = await cancelOcrRun(runId);
      setLiveStatuses((prev) => ({ ...prev, [cancelled.ocr_run_id]: cancelled }));
      if (selectedBookId) {
        await refreshBookDetail(selectedBookId);
      }
      setBanner({
        kind: "info",
        text: `Cancelled ${formatEngineLabel(cancelled.engine)} (${cancelled.progress_current}/${cancelled.progress_total} pages saved; ready to resume).`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Cancel failed.",
      });
    }
  }

  async function handleSaveBlockEdit(
    blockId: string,
    editedText: string,
    action: "corrected" | "approved" | "reverted" | "ignored",
    reviewNote?: string,
    options?: SaveEditOptions,
  ) {
    if (!selectedBookId) return;
    setBusyBlockId(blockId);
    try {
      const res = await submitBlockEdit(blockId, {
        edited_text: editedText,
        action,
        block_role: options?.blockRole,
        review_note: reviewNote,
        add_to_correction_memory: options?.addToMemory ?? false,
        memory_scope: options?.memoryScope ?? "book_only",
        correction_type: options?.correctionType,
        auto_filter_noise: true,
      });
      await Promise.all([
        refreshBookDetail(selectedBookId),
        refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId),
      ]);
      setBanner({
        kind: "success",
        text: res.correction_memory_id
          ? `Saved "${action}" event and recorded correction memory candidate.`
          : `Saved "${action}" event (raw OCR preserved).`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to save edit.",
      });
    } finally {
      setBusyBlockId(null);
    }
  }

  async function handleAcceptSuggestion(
    block: ReviewBlock,
    suggestion: CorrectionSuggestionItem,
  ) {
    if (!selectedBookId || !suggestion.proposed_block_text) return;
    setBusyBlockId(block.block_id);
    try {
      await approveCorrection(suggestion.correction_id);
      await submitBlockEdit(block.block_id, {
        edited_text: suggestion.proposed_block_text,
        action: "corrected",
        review_note: `Accepted correction memory suggestion ${suggestion.correction_id}`,
      });
      await Promise.all([
        refreshBookDetail(selectedBookId),
        refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId),
      ]);
      setBanner({
        kind: "success",
        text: "Applied suggestion to this block only and incremented approved count.",
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to apply suggestion.",
      });
    } finally {
      setBusyBlockId(null);
    }
  }

  async function handleRejectSuggestion(suggestionId: string) {
    if (!selectedBookId) return;
    try {
      await rejectCorrection(suggestionId, false);
      await refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId);
      setBanner({ kind: "info", text: "Recorded suggestion rejection evidence." });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to reject suggestion.",
      });
    }
  }

  async function handlePageStatusChange(
    reviewStatus: "not_started" | "in_review" | "approved" | "needs_attention",
  ) {
    if (!selectedBookId) return;
    try {
      await updatePageReviewStatus(
        selectedBookId,
        selectedPageNumber,
        reviewStatus,
        review?.primary_run_id,
      );
      await Promise.all([
        refreshBookDetail(selectedBookId),
        refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId),
      ]);
      setBanner({
        kind: "success",
        text: `Page ${selectedPageNumber} marked "${formatReviewStatus(reviewStatus)}".`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Status update failed.",
      });
    }
  }

  async function handleAddManualBlock(text: string, blockRole: BlockRole) {
    if (!selectedBookId) return;
    try {
      await createManualPageBlock(selectedBookId, selectedPageNumber, {
        text,
        block_role: blockRole,
        primary_run_id: review?.primary_run_id,
      });
      await Promise.all([
        refreshBookDetail(selectedBookId),
        refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId),
      ]);
      setBanner({
        kind: "success",
        text: `Inserted manual line on Page ${selectedPageNumber}.`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to insert line.",
      });
    }
  }

  async function handleSaveDigitalText(digitalTextContent: string) {
    if (!selectedBookId) return;
    try {
      await updatePageDigitalText(selectedBookId, selectedPageNumber, digitalTextContent);
      await Promise.all([
        refreshBookDetail(selectedBookId),
        refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId),
      ]);
      setBanner({
        kind: "success",
        text: `Saved born-digital text for Page ${selectedPageNumber}.`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to save digital text.",
      });
    }
  }

  async function handleAutocorrectPage(
    currentTexts: Record<string, string>,
  ): Promise<PageAutocorrectResponse | null> {
    if (!selectedBookId || !review) return null;
    try {
      const res = await autocorrectPage(selectedBookId, selectedPageNumber, {
        primaryRunId: review.primary_run_id,
        useCorrectionMemory: true,
        useDictionary: true,
        useSentenceContext: true,
        currentTexts,
      });
      if (res.changed_blocks_count === 0) {
        setBanner({
          kind: "info",
          text: `No high-confidence auto-corrections found on Page ${selectedPageNumber} (scanned ${res.total_blocks_scanned} line(s) against ${res.lexicon_word_count.toLocaleString()} Telugu words & correction memory).`,
        });
      } else {
        setBanner({
          kind: "success",
          text: `Auto-corrected ${res.changed_blocks_count} line(s) (${res.total_changes_count} fix(es)) into drafts. Review highlighted cards and click "Save All & Approve Page".`,
        });
      }
      return res;
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Auto-correct failed.",
      });
      return null;
    }
  }

  async function handleBatchSaveAndApprovePage(edits: BatchBlockEditPayload[]) {
    if (!selectedBookId || !review) return;
    try {
      const res = await batchSavePage(selectedBookId, selectedPageNumber, {
        primaryRunId: review.primary_run_id,
        edits,
        approveRemainingBlocks: true,
        markPageApproved: true,
      });
      await Promise.all([
        refreshBookDetail(selectedBookId),
        refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId),
      ]);
      const memNote =
        res.correction_memory_created_count > 0
          ? `, added ${res.correction_memory_created_count} rule(s) to correction memory`
          : "";
      let nextMsg = "";
      if (autoAdvancePage) {
        const nextPending =
          pages.find(
            (p) => p.page_number > selectedPageNumber && p.review_status !== "approved",
          ) ?? pages.find((p) => p.page_number !== selectedPageNumber && p.review_status !== "approved");
        if (nextPending) {
          setSelectedPageNumber(nextPending.page_number);
          setSelectedBlockId(null);
          setSyncRequest(null);
          nextMsg = ` → Advancing to Page ${nextPending.page_number}.`;
        }
      }
      setBanner({
        kind: "success",
        text: `Page ${selectedPageNumber} approved: saved ${res.saved_edits_count} edit(s), approved ${res.approved_blocks_count} line(s)${memNote}.${nextMsg}`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Batch save & approve failed.",
      });
    }
  }

  async function handleBatchApproveUnflagged() {
    if (!selectedBookId || !review) return;
    const targets = review.blocks.filter(
      (b) =>
        b.latest_action !== "approved" &&
        b.latest_action !== "ignored" &&
        !b.low_confidence_flag &&
        !b.disagreement_flag &&
        !b.short_or_empty_flag,
    );
    if (targets.length === 0) {
      setBanner({ kind: "info", text: "All unflagged blocks on this page are already approved." });
      return;
    }
    try {
      await batchSavePage(selectedBookId, selectedPageNumber, {
        primaryRunId: review.primary_run_id,
        edits: targets.map((blk) => ({
          block_id: blk.block_id,
          edited_text: blk.current_text,
          action: "approved",
          block_role: blk.block_role ?? "paragraph",
          add_to_correction_memory: false,
        })),
        approveRemainingBlocks: false,
        markPageApproved: false,
      });
      await Promise.all([
        refreshBookDetail(selectedBookId),
        refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId),
      ]);
      setBanner({
        kind: "success",
        text: `Approved ${targets.length} unflagged block(s) on Page ${selectedPageNumber}.`,
      });
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Batch approval failed.",
      });
    }
  }

  const approvedPagesCount = useMemo(
    () => pages.filter((p) => p.review_status === "approved").length,
    [pages],
  );
  const filteredPages = useMemo(() => {
    if (pageFilter === "approved") {
      return pages.filter((p) => p.review_status === "approved");
    }
    if (pageFilter === "pending") {
      return pages.filter((p) => p.review_status !== "approved");
    }
    return pages;
  }, [pages, pageFilter]);

  const resumableRuns = useMemo(
    () =>
      mergedRuns.filter(
        (r) => (r.status === "partial" || r.status === "failed") && !activeRunIds.includes(r.ocr_run_id),
      ),
    [mergedRuns, activeRunIds],
  );

  const triggerSync = useCallback((target: "scan" | "editor", blockId: string) => {
    syncSeqCounterRef.current += 1;
    setSyncRequest({ target, blockId, seq: syncSeqCounterRef.current });
  }, []);

  const handleSelectFromScan = useCallback(
    (blockId: string) => {
      setSelectedBlockId(blockId);
      if (autoSyncBlocks) {
        triggerSync("editor", blockId);
      }
    },
    [autoSyncBlocks, triggerSync],
  );

  const handleSelectFromEditor = useCallback(
    (blockId: string) => {
      const changed = blockId !== selectedBlockId;
      setSelectedBlockId(blockId);
      if (autoSyncBlocks && changed) {
        triggerSync("scan", blockId);
      }
    },
    [autoSyncBlocks, selectedBlockId, triggerSync],
  );

  useEffect(() => {
    function handleFocusIn(event: FocusEvent) {
      const el = event.target;
      if (isEditableTextElement(el)) {
        lastEditableRef.current = el;
        const label =
          el.getAttribute("aria-label") ||
          (el.id && document.querySelector(`label[for="${el.id}"]`)?.textContent?.trim()) ||
          el.getAttribute("name") ||
          "Active text box";
        setKeyboardTargetLabel(label);
      }
    }
    document.addEventListener("focusin", handleFocusIn);
    return () => document.removeEventListener("focusin", handleFocusIn);
  }, []);

  const resolveKeyboardTarget = useCallback((): EditableTextElement | null => {
    if (isEditableTextElement(document.activeElement)) {
      lastEditableRef.current = document.activeElement;
      return document.activeElement;
    }
    if (
      lastEditableRef.current &&
      isEditableTextElement(lastEditableRef.current) &&
      lastEditableRef.current.isConnected
    ) {
      return lastEditableRef.current;
    }
    if (selectedBlockId) {
      const escapedId =
        typeof CSS !== "undefined" && typeof CSS.escape === "function"
          ? CSS.escape(selectedBlockId)
          : selectedBlockId.replace(/"/g, '\\"');
      const fallbackArea = document.querySelector<HTMLTextAreaElement>(
        `[data-block-id="${escapedId}"] textarea.block-textarea`,
      );
      if (isEditableTextElement(fallbackArea)) {
        lastEditableRef.current = fallbackArea;
        return fallbackArea;
      }
    }
    const firstArea = document.querySelector<HTMLTextAreaElement>("textarea.block-textarea");
    if (isEditableTextElement(firstArea)) {
      lastEditableRef.current = firstArea;
      return firstArea;
    }
    return null;
  }, [selectedBlockId]);

  const handleKeyboardInsert = useCallback(
    (text: string): boolean => {
      const target = resolveKeyboardTarget();
      if (!target) return false;
      return insertTextAtCursor(target, text);
    },
    [resolveKeyboardTarget],
  );

  const handleKeyboardBackspace = useCallback((): boolean => {
    const target = resolveKeyboardTarget();
    if (!target) return false;
    return backspaceAtCursor(target);
  }, [resolveKeyboardTarget]);

  const handleImportCta = useCallback(() => {
    setUploadExpanded(true);
    setActiveView("review");
    window.requestAnimationFrame(() => {
      const input = document.querySelector<HTMLInputElement>('.sidebar input[type="file"]');
      if (input) {
        input.scrollIntoView({ block: "center" });
        input.focus();
        input.click();
      }
    });
  }, []);

  return (
    <div className={keyboardOpen ? "app-shell has-keyboard" : "app-shell"}>
      <a href="#main-review" className="skip-link visually-hidden">
        Skip to review workspace
      </a>

      <div className="app-top">
      <CommitmentBar />
      <header className="app-header">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">
            <span lang="te">తె</span>
          </div>
          <div>
            <h1>
              Telugu Book Digitizer <span className="brand-badge">Local Studio</span>
            </h1>
            <span className="header-meta">
              Dual-engine OCR · Human proofreading · Correction memory
            </span>
          </div>
        </div>

        <div className="header-actions">
          <HeaderOcrStatusPill book={selectedBook} runs={mergedRuns} />

          <button
            type="button"
            className="btn-compact"
            aria-pressed={keyboardOpen}
            title="Toggle on-screen Telugu InScript & Phonetic keyboard"
            onClick={() => setKeyboardOpen((v) => !v)}
          >
            ⌨ Telugu Keyboard
          </button>

          <button
            type="button"
            className="primary btn-compact header-cta"
            title="Import a scanned Telugu PDF"
            onClick={handleImportCta}
          >
            ＋ Import PDF
          </button>

          <nav className="segmented-nav" aria-label="Workspace views">
            <button
              type="button"
              className={activeView === "review" ? "primary" : undefined}
              aria-pressed={activeView === "review"}
              onClick={() => setActiveView("review")}
            >
              <span aria-hidden="true">📖</span> Page Review
            </button>
            <button
              type="button"
              className={activeView === "dictionary" ? "primary" : undefined}
              aria-pressed={activeView === "dictionary"}
              onClick={() => setActiveView("dictionary")}
            >
              <span aria-hidden="true">📚</span> Dictionary
            </button>
            <button
              type="button"
              className={activeView === "memory" ? "primary" : undefined}
              aria-pressed={activeView === "memory"}
              onClick={() => setActiveView("memory")}
            >
              <span aria-hidden="true">🧠</span> Correction Memory
            </button>
            <button
              type="button"
              className={activeView === "export" ? "primary" : undefined}
              aria-pressed={activeView === "export"}
              disabled={!selectedBook}
              onClick={() => setActiveView("export")}
            >
              <span aria-hidden="true">📄</span> Export DOCX / TXT
            </button>
          </nav>
        </div>
      </header>
      </div>

      <div className="workspace-grid">
        <aside className="sidebar" aria-label="Library and OCR controls">
          {uploadExpanded || books.length === 0 ? (
            <div>
              {books.length > 0 && (
                <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "0.35rem" }}>
                  <button
                    type="button"
                    className="btn-compact"
                    onClick={() => setUploadExpanded(false)}
                  >
                    Hide Upload Form
                  </button>
                </div>
              )}
              <BookUploadForm busy={busyUpload} onUpload={handleUpload} />
            </div>
          ) : (
            <section className="panel-card panel-card-compact">
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem" }}>
                <div>
                  <strong style={{ fontSize: "0.95rem" }}>Library Import</strong>
                  <div className="hint-text">Add another scanned Telugu PDF</div>
                </div>
                <button
                  type="button"
                  className="primary btn-compact"
                  onClick={() => setUploadExpanded(true)}
                >
                  + Import PDF
                </button>
              </div>
            </section>
          )}

          <section className="panel-card">
            <h2 className="card-title">
              <span className="card-icon" aria-hidden="true">
                📚
              </span>
              Books ({books.length})
            </h2>
            {books.length === 0 ? (
              <p className="hint-text">Upload a printed Telugu PDF above to begin.</p>
            ) : (
              <ul className="book-list">
                {books.map((book) => {
                  const isSel = book.book_id === selectedBookId;
                  return (
                    <li key={book.book_id}>
                      <button
                        type="button"
                        className={`book-item-btn ${isSel ? "selected" : ""}`}
                        onClick={() => {
                          setSelectedBookId(book.book_id);
                          setSelectedPageNumber(1);
                          setSelectedPrimaryRunId(null);
                        }}
                      >
                        <strong lang="te">{book.title}</strong>
                        <span className="hint-text">
                          {book.page_count} pages · {book.scanned_pages_count} scanned ·{" "}
                          {book.digital_text_pages_count} digital
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}

            {selectedBook && (
              <div style={{ marginTop: "0.75rem", display: "flex", flexDirection: "column", gap: "0.45rem" }}>
                <label className="hint-text" style={{ display: "flex", flexDirection: "column", gap: "0.25rem" }}>
                  <span>Select another book</span>
                  <select
                    aria-label="Select another book"
                    value={selectedBookId ?? ""}
                    onChange={(e) => {
                      const nextId = e.target.value;
                      if (!nextId) return;
                      setSelectedBookId(nextId);
                      setSelectedPageNumber(1);
                      setSelectedPrimaryRunId(null);
                      setSelectedBlockId(null);
                    }}
                  >
                    {books.map((book) => (
                      <option key={book.book_id} value={book.book_id}>
                        {book.title} ({book.page_count}p)
                      </option>
                    ))}
                  </select>
                </label>
                <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
                  {books.length > 1 && (
                    <button
                      type="button"
                      className="btn-compact"
                      onClick={() => {
                        const idx = books.findIndex((b) => b.book_id === selectedBookId);
                        const nextBook = books[(idx + 1) % books.length];
                        if (!nextBook) return;
                        setSelectedBookId(nextBook.book_id);
                        setSelectedPageNumber(1);
                        setSelectedPrimaryRunId(null);
                        setSelectedBlockId(null);
                      }}
                    >
                      Switch Book →
                    </button>
                  )}
                  <button
                    type="button"
                    className="btn-compact"
                    onClick={() => setUploadExpanded(true)}
                  >
                    + Upload Another Book
                  </button>
                </div>
              </div>
            )}
          </section>

          {selectedBook && (
            <section className="panel-card">
              <h2 className="card-title">
                <span className="card-icon" aria-hidden="true">
                  ⚙️
                </span>
                Run OCR Engines
              </h2>
              <fieldset className="sidebar-fieldset">
                <legend className="hint-text">Engines</legend>
                <div className="checkbox-row">
                  <input
                    id="eng-paddle"
                    type="checkbox"
                    checked={usePaddle}
                    disabled={capabilities?.engines.paddle_ppocrv5_te?.available === false}
                    onChange={(e) => setUsePaddle(e.target.checked)}
                  />
                  <label htmlFor="eng-paddle">
                    PaddleOCR PP-OCRv5{" "}
                    <span className="hint-text">
                      {capabilities?.engines.paddle_ppocrv5_te?.available === false
                        ? `(${capabilities.engines.paddle_ppocrv5_te.reason ?? "Unavailable"})`
                        : "(~90s/p CPU)"}
                    </span>
                  </label>
                </div>
                <div className="checkbox-row">
                  <input
                    id="eng-tess"
                    type="checkbox"
                    checked={useTesseract}
                    disabled={capabilities?.engines.tesseract_tel_best?.available === false}
                    onChange={(e) => setUseTesseract(e.target.checked)}
                  />
                  <label htmlFor="eng-tess">
                    Tesseract 5 Telugu{" "}
                    <span className="hint-text">
                      {capabilities?.engines.tesseract_tel_best?.available === false
                        ? `(${capabilities.engines.tesseract_tel_best.reason ?? "Unavailable"})`
                        : "(~0.4s/p CPU)"}
                    </span>
                  </label>
                </div>
              </fieldset>

              <fieldset className="sidebar-fieldset" style={{ marginTop: "0.55rem" }}>
                <legend className="hint-text">Page Range</legend>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.45rem" }}>
                  <label className="hint-text" htmlFor="ocr-start-page">
                    Start page
                    <input
                      id="ocr-start-page"
                      type="number"
                      className="compact-number-input"
                      min={1}
                      max={selectedBook.page_count}
                      value={ocrStartPage}
                      onChange={(e) => setOcrStartPage(e.target.value)}
                    />
                  </label>
                  <label className="hint-text" htmlFor="ocr-end-page">
                    End page
                    <input
                      id="ocr-end-page"
                      type="number"
                      className="compact-number-input"
                      min={1}
                      max={selectedBook.page_count}
                      value={ocrEndPage}
                      placeholder={String(selectedBook.page_count)}
                      onChange={(e) => setOcrEndPage(e.target.value)}
                    />
                  </label>
                </div>
                <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.45rem", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    className="btn-compact"
                    onClick={() => {
                      setOcrStartPage("1");
                      setOcrEndPage(String(Math.min(5, selectedBook.page_count)));
                    }}
                  >
                    Pages 1–5
                  </button>
                  <button
                    type="button"
                    className="btn-compact"
                    onClick={() => {
                      setOcrStartPage("1");
                      setOcrEndPage(String(selectedBook.page_count));
                    }}
                  >
                    All ({selectedBook.page_count})
                  </button>
                </div>
                <p className="hint-text" style={{ marginTop: "0.4rem", marginBottom: 0 }}>
                  For large PDFs on CPU, test Pages 1–5 first or run Tesseract alone for a quick draft.
                </p>
              </fieldset>

              <details style={{ marginTop: "0.5rem" }}>
                <summary className="hint-text" style={{ cursor: "pointer", userSelect: "none" }}>
                  Advanced Preprocessing &amp; DPI
                </summary>
                <div style={{ marginTop: "0.45rem", display: "flex", flexDirection: "column", gap: "0.45rem" }}>
                  <label className="hint-text" style={{ display: "flex", flexDirection: "column", gap: "0.2rem" }}>
                    <span>Scan Preprocessing</span>
                    <select
                      aria-label="OCR preprocessing profile"
                      value={ocrPreprocessing}
                      onChange={(e) =>
                        setOcrPreprocessing(e.target.value as "none" | "deskew" | "contrast_clahe")
                      }
                    >
                      <option value="none">None (Raw 300 DPI scan)</option>
                      <option value="deskew">Auto-Deskew + Contrast</option>
                      <option value="contrast_clahe">CLAHE Adaptive Contrast + Denoise</option>
                    </select>
                  </label>
                  <label className="hint-text" style={{ display: "flex", flexDirection: "column", gap: "0.2rem" }}>
                    <span>Render Resolution</span>
                    <select
                      aria-label="OCR render DPI"
                      value={ocrRenderDpi}
                      onChange={(e) => setOcrRenderDpi(Number(e.target.value))}
                    >
                      <option value={300}>300 DPI (Standard)</option>
                      <option value={400}>400 DPI (Fine / Faded print)</option>
                    </select>
                  </label>
                  <div className="checkbox-row">
                    <input
                      id="ocr-force-rerun"
                      type="checkbox"
                      checked={ocrForceRerun}
                      onChange={(e) => setOcrForceRerun(e.target.checked)}
                    />
                    <label htmlFor="ocr-force-rerun">Force fresh OCR re-run</label>
                  </div>
                  <div className="checkbox-row">
                    <input
                      id="ocr-include-digital"
                      type="checkbox"
                      checked={ocrIncludeDigital}
                      onChange={(e) => setOcrIncludeDigital(e.target.checked)}
                    />
                    <label htmlFor="ocr-include-digital">Include digital-text pages in visual OCR</label>
                  </div>
                </div>
              </details>

              <div style={{ marginTop: "0.65rem", display: "flex", flexDirection: "column", gap: "0.45rem" }}>
                <button
                  type="button"
                  className="primary"
                  disabled={isOcrRunning}
                  onClick={() => void handleStartOcr()}
                >
                  {isOcrRunning ? "OCR In Progress..." : "Run Selected OCR"}
                </button>
                {resumableRuns.map((r) => (
                  <button
                    key={r.ocr_run_id}
                    type="button"
                    className="btn-compact"
                    onClick={() => void handleResumeRun(r.ocr_run_id)}
                  >
                    Resume {formatEngineLabel(r.engine)} ({r.progress_current ?? 0}/
                    {r.progress_total || selectedBook.scanned_pages_count})
                  </button>
                ))}
              </div>
            </section>
          )}

          {pages.length > 0 && (
            <nav className="panel-card" aria-label="Book pages">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: "0.5rem" }}>
                <h2 className="card-title" style={{ margin: 0 }}>
                  <span className="card-icon" aria-hidden="true">
                    🗂️
                  </span>
                  Pages ({pages.length})
                </h2>
                <span className="hint-text">{approvedPagesCount} approved</span>
              </div>
              <div className="segmented-control" role="group" aria-label="Filter pages" style={{ marginBottom: "0.6rem" }}>
                <button
                  type="button"
                  className={`btn-compact ${pageFilter === "all" ? "primary" : ""}`.trim()}
                  aria-pressed={pageFilter === "all"}
                  onClick={() => setPageFilter("all")}
                >
                  All
                </button>
                <button
                  type="button"
                  className={`btn-compact ${pageFilter === "pending" ? "primary" : ""}`.trim()}
                  aria-pressed={pageFilter === "pending"}
                  onClick={() => setPageFilter("pending")}
                >
                  Pending
                </button>
                <button
                  type="button"
                  className={`btn-compact ${pageFilter === "approved" ? "primary" : ""}`.trim()}
                  aria-pressed={pageFilter === "approved"}
                  onClick={() => setPageFilter("approved")}
                >
                  Approved
                </button>
              </div>
              <ul className="page-list">
                {filteredPages.map((p) => (
                  <li key={p.page_id}>
                    <button
                      type="button"
                      className={`page-item-btn ${p.page_number === selectedPageNumber ? "selected" : ""}`}
                      onClick={() => {
                        setSelectedPageNumber(p.page_number);
                        setSelectedBlockId(null);
                        setActiveView("review");
                      }}
                    >
                      <div className="badge-row" style={{ justifyContent: "space-between", width: "100%" }}>
                        <strong>Page {p.page_number}</strong>
                        <span className="badge">{formatPageKind(p.page_kind)}</span>
                      </div>
                      <div className="badge-row">
                        <span
                          className={`badge ${
                            p.review_status === "approved"
                              ? "ok"
                              : p.review_status === "needs_attention"
                                ? "warn"
                                : ""
                          }`}
                        >
                          {formatReviewStatus(p.review_status)}
                        </span>
                      </div>
                    </button>
                  </li>
                ))}
              </ul>
            </nav>
          )}
        </aside>

        <main id="main-review" className="main-stage" tabIndex={-1}>
          {selectedBook && activeView !== "dictionary" && (
            <OverviewPanel
              book={selectedBook}
              pages={pages}
              runs={mergedRuns}
              review={review}
              activeView={activeView}
              onGoToReview={() => setActiveView("review")}
              onGoToExport={() => setActiveView("export")}
            />
          )}

          {selectedBook && activeView !== "dictionary" && (
            <OcrProgressStrip
              book={selectedBook}
              runs={mergedRuns}
              pages={pages}
              activeView={activeView}
              onQuickStartSample={() => handleStartOcr("sample_5")}
              onQuickStartFull={() => handleStartOcr("full")}
              onResumeRun={handleResumeRun}
              onCancelRun={handleCancelRun}
              onGoToExport={() => setActiveView("export")}
              onGoToReview={() => setActiveView("review")}
            />
          )}

          {banner && (
            <div
              className={`status-banner ${
                banner.kind === "error" ? "error" : banner.kind === "success" ? "success" : ""
              }`}
              role="status"
              aria-live="polite"
            >
              <span>{banner.text}</span>
              <button
                type="button"
                className="banner-close-btn"
                aria-label="Dismiss status message"
                onClick={() => setBanner(null)}
              >
                ✕
              </button>
            </div>
          )}

          {activeView === "dictionary" ? (
            <DictionaryPanel
              initialQuery={dictionaryQuery}
              keyboardOpen={keyboardOpen}
              onToggleKeyboard={() => setKeyboardOpen((v) => !v)}
              onStatusBanner={handleStatusBanner}
            />
          ) : activeView === "memory" ? (
            <CorrectionMemoryPanel
              selectedBookId={selectedBookId}
              onStatusBanner={handleStatusBanner}
            />
          ) : activeView === "export" && selectedBook ? (
            <ExportPanel
              book={selectedBook}
              runs={mergedRuns}
              onStatusBanner={handleStatusBanner}
              onGoToReview={() => setActiveView("review")}
            />
          ) : !review ? (
            books.length === 0 ? (
              <WelcomeHero onImportClick={handleImportCta} />
            ) : (
              <div className="panel-card">
                <h2>Loading page…</h2>
                <p className="hint-text">Fetching the scan and OCR lines for the selected page.</p>
              </div>
            )
          ) : (
            <div className="review-split">
              <SourcePageViewer
                bookId={review.book_id}
                pageNumber={review.page_number}
                pageCount={review.page_count}
                widthPx={review.width_px}
                heightPx={review.height_px}
                blocks={review.blocks}
                selectedBlockId={selectedBlockId}
                syncTarget={syncRequest?.target === "scan" ? syncRequest : null}
                autoSync={autoSyncBlocks}
                onSelectBlock={handleSelectFromScan}
                onSyncToEditor={() => {
                  if (selectedBlockId) {
                    triggerSync("editor", selectedBlockId);
                  }
                }}
                onToggleAutoSync={() => setAutoSyncBlocks((v) => !v)}
                onNavigatePage={(p) => {
                  setSelectedPageNumber(p);
                  setSelectedBlockId(null);
                  setSyncRequest(null);
                }}
              />

              <ReviewEditorPanel
                review={review}
                selectedBlockId={selectedBlockId}
                busyBlockId={busyBlockId}
                ocrRunning={isOcrRunning}
                syncTarget={syncRequest?.target === "editor" ? syncRequest : null}
                autoSync={autoSyncBlocks}
                autoAdvance={autoAdvancePage}
                keyboardOpen={keyboardOpen}
                onQuickStartOcr={() => handleStartOcr()}
                onSelectBlock={handleSelectFromEditor}
                onLocateBlockOnScan={(blockId) => {
                  setSelectedBlockId(blockId);
                  triggerSync("scan", blockId);
                }}
                onLookupWord={(word) => {
                  setQuickLookupWord(word);
                }}
                onSyncToScan={() => {
                  if (selectedBlockId) {
                    triggerSync("scan", selectedBlockId);
                  }
                }}
                onToggleAutoSync={() => setAutoSyncBlocks((v) => !v)}
                onToggleAutoAdvance={() => setAutoAdvancePage((v) => !v)}
                onToggleKeyboard={() => setKeyboardOpen((v) => !v)}
                onSelectPrimaryRun={(runId) => setSelectedPrimaryRunId(runId)}
                onSaveEdit={handleSaveBlockEdit}
                onAddManualBlock={handleAddManualBlock}
                onSaveDigitalText={handleSaveDigitalText}
                onBatchApproveUnflagged={handleBatchApproveUnflagged}
                onAutocorrectPage={handleAutocorrectPage}
                onBatchSaveAndApprovePage={handleBatchSaveAndApprovePage}
                onAcceptSuggestion={handleAcceptSuggestion}
                onRejectSuggestion={handleRejectSuggestion}
                onChangePageStatus={handlePageStatusChange}
              />
            </div>
          )}
        </main>
      </div>

      <TeluguKeyboard
        open={keyboardOpen}
        onClose={() => setKeyboardOpen(false)}
        onInsertText={handleKeyboardInsert}
        onBackspace={handleKeyboardBackspace}
        targetDescription={keyboardTargetLabel}
      />

      <QuickLookupDialog
        word={quickLookupWord}
        onClose={() => setQuickLookupWord(null)}
        onOpenFullDictionary={(w) => {
          setDictionaryQuery(w);
          setActiveView("dictionary");
        }}
      />
    </div>
  );
}
