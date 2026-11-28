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
import { ImportBookDialog } from "./components/ImportBookDialog";
import { OcrRunnerDrawer } from "./components/OcrRunnerDrawer";
import {
  OcrProgressStrip,
  mergeBookRunsWithLiveStatuses,
} from "./components/OcrStatusBar";
import { PageRail } from "./components/PageRail";
import { QuickLookupDialog } from "./components/QuickLookupDialog";
import { ReviewEditorPanel, type SaveEditOptions } from "./components/ReviewEditorPanel";
import { ShortcutsDialog } from "./components/ShortcutsDialog";
import { SourcePageViewer } from "./components/SourcePageViewer";
import { WelcomeHero } from "./components/StudioChrome";
import { TeluguKeyboard } from "./components/TeluguKeyboard";
import { ToastRegion, type ToastItem } from "./components/ToastRegion";
import { TopNavBar, type WorkspaceView } from "./components/TopNavBar";
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
import { formatEngineLabel, formatReviewStatus } from "./utils/formatters";
import {
  type EditableTextElement,
  backspaceAtCursor,
  insertTextAtCursor,
  isEditableTextElement,
} from "./utils/teluguInput";

function parseInitialUrlParams(): {
  view: WorkspaceView;
  bookId: string | null;
  page: number;
  q: string | null;
} {
  if (typeof window === "undefined") {
    return { view: "review", bookId: null, page: 1, q: null };
  }
  const params = new URLSearchParams(window.location.search);
  const rawView = params.get("view");
  const view: WorkspaceView =
    rawView === "dictionary" || rawView === "memory" || rawView === "export"
      ? rawView
      : "review";
  const bookId = params.get("book") || null;
  const rawPage = Number(params.get("page"));
  const page = Number.isInteger(rawPage) && rawPage >= 1 ? rawPage : 1;
  const q = params.get("q");
  return { view, bookId, page, q };
}

export function App() {
  const initialUrl = useMemo(() => parseInitialUrlParams(), []);

  const [books, setBooks] = useState<BookSummary[]>([]);
  const [booksLoaded, setBooksLoaded] = useState(false);
  const [selectedBookId, setSelectedBookId] = useState<string | null>(initialUrl.bookId);
  const [pages, setPages] = useState<PageSummary[]>([]);
  const [selectedPageNumber, setSelectedPageNumber] = useState<number>(initialUrl.page);
  const [pageJumpInput, setPageJumpInput] = useState<string>(String(initialUrl.page));
  const [runs, setRuns] = useState<BookOCRRunSummary[]>([]);
  const [liveStatuses, setLiveStatuses] = useState<Record<string, OCRRunStatus>>({});
  const [selectedPrimaryRunId, setSelectedPrimaryRunId] = useState<string | null>(null);
  const [review, setReview] = useState<PageReviewPayload | null>(null);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [dirtyBlockCount, setDirtyBlockCount] = useState<number>(0);

  // Proofreading UX preferences
  const [autoSyncBlocks, setAutoSyncBlocks] = useState(true);
  const [autoAdvancePage, setAutoAdvancePage] = useState(true);
  const [pageRailOpen, setPageRailOpen] = useState(false);
  const [pageFilter, setPageFilter] = useState<"all" | "pending" | "approved" | "needs_attention">("all");
  const [mobilePane, setMobilePane] = useState<"editor" | "scan">("editor");

  // Modals, drawers & overlays
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [ocrDrawerOpen, setOcrDrawerOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [quickLookupWord, setQuickLookupWord] = useState<string | null>(null);
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  const lastEditableRef = useRef<EditableTextElement | null>(null);
  const [keyboardTargetLabel, setKeyboardTargetLabel] = useState<string | null>(null);

  // Workspace view & deep-linked dictionary query
  const [activeView, setActiveView] = useState<WorkspaceView>(initialUrl.view);
  const [dictionaryQuery, setDictionaryQuery] = useState<string | null>(initialUrl.q);
  const [dictionaryReturnContext, setDictionaryReturnContext] = useState<boolean>(false);

  // Sync scan <-> editor scroll requests
  const [syncRequest, setSyncRequest] = useState<{
    target: "scan" | "editor";
    blockId: string;
    seq: number;
  } | null>(null);
  const syncSeqCounterRef = useRef(0);

  // OCR configuration (now hosted cleanly inside OcrRunnerDrawer)
  const [usePaddle, setUsePaddle] = useState(true);
  const [useTesseract, setUseTesseract] = useState(true);
  const [capabilities, setCapabilities] = useState<HostCapabilities | null>(null);
  const [ocrStartPage, setOcrStartPage] = useState("1");
  const [ocrEndPage, setOcrEndPage] = useState("");
  const [ocrPreprocessing, setOcrPreprocessing] = useState<
    "none" | "deskew" | "contrast_clahe" | "textured_bold"
  >("none");
  const [ocrRenderDpi, setOcrRenderDpi] = useState<number>(300);
  const [ocrForceRerun, setOcrForceRerun] = useState<boolean>(false);
  const [ocrIncludeDigital, setOcrIncludeDigital] = useState<boolean>(false);

  // Busy & notification states
  const [busyUpload, setBusyUpload] = useState(false);
  const [busyBlockId, setBusyBlockId] = useState<string | null>(null);
  const [errorBanner, setErrorBanner] = useState<string | null>(null);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const toastSeqRef = useRef(0);

  const prevProgressRef = useRef<Record<string, { progress: number; status: string }>>({});
  const selectedPageNumberRef = useRef(selectedPageNumber);
  selectedPageNumberRef.current = selectedPageNumber;
  const selectedPrimaryRunIdRef = useRef(selectedPrimaryRunId);
  selectedPrimaryRunIdRef.current = selectedPrimaryRunId;
  const reviewBlocksCountRef = useRef(0);
  reviewBlocksCountRef.current = review?.blocks.length ?? 0;
  const dirtyBlockCountRef = useRef(dirtyBlockCount);
  dirtyBlockCountRef.current = dirtyBlockCount;

  const selectedBook = useMemo(
    () => books.find((b) => b.book_id === selectedBookId) ?? null,
    [books, selectedBookId],
  );

  // Sync page jump input whenever page changes
  useEffect(() => {
    setPageJumpInput(String(selectedPageNumber));
  }, [selectedPageNumber]);

  // Keep URL query params in sync (?view=, ?book=, ?page=, ?q=)
  useEffect(() => {
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (activeView === "review") {
      url.searchParams.delete("view");
    } else {
      url.searchParams.set("view", activeView);
    }
    if (selectedBookId) {
      url.searchParams.set("book", selectedBookId);
    } else {
      url.searchParams.delete("book");
    }
    if (selectedBookId && selectedPageNumber > 1) {
      url.searchParams.set("page", String(selectedPageNumber));
    } else {
      url.searchParams.delete("page");
    }
    if (activeView === "dictionary" && dictionaryQuery?.trim()) {
      url.searchParams.set("q", dictionaryQuery.trim());
    } else if (activeView !== "dictionary") {
      url.searchParams.delete("q");
    }
    if (url.toString() !== window.location.href) {
      window.history.replaceState({}, "", url.toString());
    }
  }, [activeView, selectedBookId, selectedPageNumber, dictionaryQuery]);

  // Listen for browser Back/Forward
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onPopState = () => {
      const parsed = parseInitialUrlParams();
      setActiveView(parsed.view);
      if (parsed.bookId) setSelectedBookId(parsed.bookId);
      setSelectedPageNumber(parsed.page);
      setDictionaryQuery(parsed.q);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  // Warn before closing tab if unsaved line edits exist
  useEffect(() => {
    if (typeof window === "undefined" || dirtyBlockCount === 0) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirtyBlockCount]);

  // Sync default OCR page range when book changes
  const reviewBookId = review?.book_id;
  const reviewPageCount = review?.page_count ?? selectedBook?.page_count;
  useEffect(() => {
    if (selectedBookId && reviewPageCount) {
      setOcrStartPage("1");
      setOcrEndPage(String(reviewPageCount));
    } else {
      setOcrStartPage("1");
      setOcrEndPage("");
    }
  }, [selectedBookId, reviewBookId, reviewPageCount]);

  useEffect(() => {
    setLiveStatuses({});
    prevProgressRef.current = {};
  }, [selectedBookId]);

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const handleStatusBanner = useCallback(
    (kind: "info" | "success" | "error", text: string) => {
      if (kind === "error") {
        setErrorBanner(text);
        return;
      }
      setErrorBanner(null);
      toastSeqRef.current += 1;
      const nextId = toastSeqRef.current;
      setToasts((prev) => [...prev.slice(-2), { id: nextId, kind, text }]);
    },
    [],
  );

  const confirmDiscardIfDirty = useCallback((actionLabel: string): boolean => {
    if (dirtyBlockCountRef.current <= 0) return true;
    return window.confirm(
      `You have ${dirtyBlockCountRef.current} unsaved line edit(s) on this page. Discard them and ${actionLabel}?`,
    );
  }, []);

  const navigateToPage = useCallback(
    (nextPage: number, skipDirtyCheck = false) => {
      if (!selectedBook) return;
      const clamped = Math.max(1, Math.min(selectedBook.page_count, nextPage));
      if (clamped === selectedPageNumberRef.current) return;
      if (!skipDirtyCheck && !confirmDiscardIfDirty(`go to Page ${clamped}`)) return;
      setSelectedPageNumber(clamped);
      setSelectedBlockId(null);
      setSyncRequest(null);
      setDirtyBlockCount(0);
    },
    [confirmDiscardIfDirty, selectedBook],
  );

  const navigateToBook = useCallback(
    (bookId: string) => {
      if (bookId === selectedBookId) return;
      if (!confirmDiscardIfDirty("switch books")) return;
      setSelectedBookId(bookId);
      setSelectedPageNumber(1);
      setSelectedPrimaryRunId(null);
      setSelectedBlockId(null);
      setSyncRequest(null);
      setDirtyBlockCount(0);
      setActiveView("review");
    },
    [confirmDiscardIfDirty, selectedBookId],
  );

  // Global keyboard shortcuts ([ toggles PageRail, ? opens shortcuts, Alt+←/→ flips pages)
  useEffect(() => {
    function handleGlobalKeyDown(e: KeyboardEvent) {
      if (e.isComposing) return;
      const active = document.activeElement;
      const inEditable =
        isEditableTextElement(active) ||
        (active instanceof HTMLElement &&
          (active.tagName === "SELECT" || active.isContentEditable));

      if (e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
        if (e.key === "ArrowRight" && activeView === "review" && selectedBook) {
          e.preventDefault();
          navigateToPage(selectedPageNumberRef.current + 1);
          return;
        }
        if (e.key === "ArrowLeft" && activeView === "review" && selectedBook) {
          e.preventDefault();
          navigateToPage(selectedPageNumberRef.current - 1);
          return;
        }
      }

      if (inEditable || e.ctrlKey || e.metaKey || e.altKey) return;

      if (e.key === "[" && activeView === "review" && selectedBook) {
        e.preventDefault();
        setPageRailOpen((v) => !v);
      } else if (e.key === "?") {
        e.preventDefault();
        setShortcutsOpen(true);
      }
    }

    document.addEventListener("keydown", handleGlobalKeyDown);
    return () => document.removeEventListener("keydown", handleGlobalKeyDown);
  }, [activeView, navigateToPage, selectedBook]);

  const refreshBooks = useCallback(async () => {
    const items = await listBooks();
    setBooks(items);
    setBooksLoaded(true);
    setSelectedBookId((currentId) => {
      if (items.length === 0) {
        setPages([]);
        setRuns([]);
        setReview(null);
        return null;
      }
      if (currentId && items.some((b) => b.book_id === currentId)) {
        const matched = items.find((b) => b.book_id === currentId);
        if (matched && selectedPageNumberRef.current > matched.page_count) {
          setSelectedPageNumber(1);
        }
        return currentId;
      }
      setSelectedPageNumber(1);
      return items[0].book_id;
    });
  }, []);

  const refreshBookDetail = useCallback(async (bookId: string) => {
    const [pageList, runList] = await Promise.all([
      listBookPages(bookId),
      listBookOcrRuns(bookId),
    ]);
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
      handleStatusBanner("error", err instanceof Error ? err.message : "Failed to load books.");
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
  }, [refreshBooks, handleStatusBanner]);

  useEffect(() => {
    if (!selectedBookId) return;
    refreshBookDetail(selectedBookId).catch((err) => {
      handleStatusBanner("error", err instanceof Error ? err.message : "Failed to load book.");
    });
  }, [selectedBookId, refreshBookDetail, handleStatusBanner]);

  useEffect(() => {
    if (!selectedBookId) return;
    refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId).catch((err) => {
      handleStatusBanner(
        "error",
        err instanceof Error ? err.message : "Failed to load page review.",
      );
    });
  }, [selectedBookId, selectedPageNumber, selectedPrimaryRunId, refreshReview, handleStatusBanner]);

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
          if (becameTerminal || (advanced && reviewBlocksCountRef.current === 0)) {
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
          handleStatusBanner(
            finishedRun.status === "failed" || isZeroPartial
              ? "error"
              : finishedRun.status === "partial" || finishedRun.status === "cancelled"
                ? "info"
                : "success",
            `${formatEngineLabel(finishedRun.engine)} ${finishedRun.status} (${finishedRun.progress_current}/${finishedRun.progress_total} pages)${finishedRun.error_summary ? `: ${finishedRun.error_summary}` : "."}`,
          );
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
  }, [activeRunIdsKey, selectedBookId, refreshBookDetail, refreshReview, handleStatusBanner]);

  async function handleUpload(formData: FormData) {
    setBusyUpload(true);
    try {
      const res = await uploadBook(formData);
      await refreshBooks();
      setSelectedBookId(res.book_id);
      setSelectedPageNumber(1);
      setSelectedPrimaryRunId(null);
      setSelectedBlockId(null);
      setDirtyBlockCount(0);
      setActiveView("review");
      handleStatusBanner(
        "success",
        res.duplicate
          ? `Book "${res.title}" matched existing SHA-256 (${res.page_count} pages).`
          : `Imported "${res.title}" (${res.page_count} pages). Ready for OCR.`,
      );
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Upload failed.",
      );
      throw err;
    } finally {
      setBusyUpload(false);
    }
  }

  async function handleStartOcr(preset?: "sample_5" | "full" | "quick_tesseract") {
    if (!selectedBookId) return;
    const engines: string[] = [];
    if (preset === "quick_tesseract") {
      engines.push("tesseract_tel_best");
    } else {
      if (usePaddle) engines.push("paddle_ppocrv5_te");
      if (useTesseract) engines.push("tesseract_tel_best");
    }
    if (engines.length === 0) {
      handleStatusBanner("error", "Select at least one OCR engine.");
      return;
    }

    const totalPages = selectedBook?.page_count ?? review?.page_count ?? 0;
    let pageRange: { start: number; end: number } | null = null;

    if (preset === "sample_5") {
      const endSample = Math.min(5, totalPages || 5);
      setOcrStartPage("1");
      setOcrEndPage(String(endSample));
      pageRange = totalPages > 0 && endSample === totalPages ? null : { start: 1, end: endSample };
    } else if (preset === "full" || preset === "quick_tesseract") {
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
        handleStatusBanner(
          "error",
          totalPages > 0
            ? `Enter a valid OCR page range between 1 and ${totalPages}.`
            : "Enter a valid OCR page range.",
        );
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
      const runIdsToFetch =
        created.ocr_run_ids.length > 0 ? created.ocr_run_ids : [created.ocr_run_id];
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
        handleStatusBanner("info", "Reused existing completed OCR run.");
      } else {
        const engineNames = engines.map((e) => formatEngineLabel(e)).join(" + ");
        handleStatusBanner(
          "info",
          `Started OCR (${engineNames}) for ${created.pages_total} scanned page(s)${
            pageRange ? ` (pages ${pageRange.start}–${pageRange.end})` : ""
          }.`,
        );
      }
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to start OCR.",
      );
    }
  }

  async function handleResumeRun(runId: string) {
    try {
      const resumed = await resumeOcrRun(runId);
      setLiveStatuses((prev) => ({ ...prev, [resumed.ocr_run_id]: resumed }));
      if (selectedBookId) {
        await refreshBookDetail(selectedBookId);
      }
      handleStatusBanner(
        "info",
        `Resumed ${formatEngineLabel(resumed.engine)} from ${resumed.progress_current}/${resumed.progress_total} pages.`,
      );
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Resume failed.",
      );
    }
  }

  async function handleCancelRun(runId: string) {
    try {
      const cancelled = await cancelOcrRun(runId);
      setLiveStatuses((prev) => ({ ...prev, [cancelled.ocr_run_id]: cancelled }));
      if (selectedBookId) {
        await refreshBookDetail(selectedBookId);
      }
      handleStatusBanner(
        "info",
        `Cancelled ${formatEngineLabel(cancelled.engine)} (${cancelled.progress_current}/${cancelled.progress_total} pages saved; ready to resume).`,
      );
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Cancel failed.",
      );
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
        memory_scope: options?.memoryScope ?? "global_suggestion",
        correction_type: options?.correctionType,
        auto_filter_noise: true,
      });

      // Optimistically patch current page review & page summary status so line saves are instant
      setReview((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          review_status: res.page_review_status,
          blocks: prev.blocks.map((blk) =>
            blk.block_id !== blockId
              ? blk
              : {
                  ...blk,
                  current_text: res.current_text,
                  block_role: res.block_role ?? blk.block_role,
                  is_edited: res.current_text !== blk.raw_text,
                  latest_action: res.action,
                  edit_history: [
                    {
                      edit_id: res.edit_id,
                      previous_text: res.previous_text,
                      edited_text: res.current_text,
                      action: res.action,
                      reviewer_id: null,
                      review_note: reviewNote ?? null,
                      created_at: res.created_at,
                    },
                    ...blk.edit_history,
                  ],
                },
          ),
        };
      });
      setPages((prev) =>
        prev.map((p) =>
          p.page_number === selectedPageNumber
            ? { ...p, review_status: res.page_review_status }
            : p,
        ),
      );

      // Refresh full review only if a new memory rule was recorded so fresh suggestions surface
      if (res.correction_memory_id) {
        void refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId);
      }

      handleStatusBanner(
        "success",
        res.correction_memory_id
          ? `Saved "${action}" and recorded correction memory rule.`
          : action === "approved"
            ? "Line approved."
            : `Saved "${action}" (raw OCR preserved).`,
      );
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to save edit.",
      );
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
      handleStatusBanner("success", "Applied suggestion to this line and updated memory evidence.");
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to apply suggestion.",
      );
    } finally {
      setBusyBlockId(null);
    }
  }

  async function handleRejectSuggestion(suggestionId: string) {
    if (!selectedBookId) return;
    try {
      await rejectCorrection(suggestionId, false);
      await refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId);
      handleStatusBanner("info", "Recorded suggestion rejection evidence.");
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to reject suggestion.",
      );
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
      handleStatusBanner(
        "success",
        `Page ${selectedPageNumber} marked "${formatReviewStatus(reviewStatus)}".`,
      );
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Status update failed.",
      );
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
      handleStatusBanner("success", `Inserted manual line on Page ${selectedPageNumber}.`);
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to insert line.",
      );
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
      handleStatusBanner("success", `Saved born-digital text for Page ${selectedPageNumber}.`);
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError
          ? `${err.code}: ${err.message}`
          : "Failed to save digital text.",
      );
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
        handleStatusBanner(
          "info",
          `No high-confidence auto-corrections on Page ${selectedPageNumber} (checked ${res.total_blocks_scanned} lines).`,
        );
      } else {
        handleStatusBanner(
          "success",
          `Drafted ${res.total_changes_count} fix(es) across ${res.changed_blocks_count} line(s). Review and approve.`,
        );
      }
      return res;
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Auto-correct failed.",
      );
      return null;
    }
  }

  async function handleBatchSaveAndApprovePage(
    edits: BatchBlockEditPayload[],
    options?: {
      markPageApproved?: boolean;
      approveRemainingBlocks?: boolean;
      targetStatus?: "approved" | "needs_attention";
    },
  ) {
    if (!selectedBookId || !review) return;
    try {
      if (options?.targetStatus === "needs_attention") {
        if (edits.length > 0) {
          await batchSavePage(selectedBookId, selectedPageNumber, {
            primaryRunId: review.primary_run_id,
            edits,
            approveRemainingBlocks: false,
            markPageApproved: false,
          });
        }
        await updatePageReviewStatus(
          selectedBookId,
          selectedPageNumber,
          "needs_attention",
          review.primary_run_id,
        );
        await Promise.all([
          refreshBookDetail(selectedBookId),
          refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId),
        ]);
        setDirtyBlockCount(0);
        handleStatusBanner(
          "info",
          edits.length > 0
            ? `Saved ${edits.length} draft edit(s) and flagged Page ${selectedPageNumber} for attention.`
            : `Flagged Page ${selectedPageNumber} as needing attention.`,
        );
        return;
      }

      const res = await batchSavePage(selectedBookId, selectedPageNumber, {
        primaryRunId: review.primary_run_id,
        edits,
        approveRemainingBlocks: options?.approveRemainingBlocks ?? true,
        markPageApproved: options?.markPageApproved ?? true,
      });
      await Promise.all([
        refreshBookDetail(selectedBookId),
        refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId),
      ]);
      setDirtyBlockCount(0);
      const memNote =
        res.correction_memory_created_count > 0
          ? `, +${res.correction_memory_created_count} memory rule(s)`
          : "";
      let nextMsg = "";
      if (autoAdvancePage) {
        const nextPending =
          pages.find(
            (p) => p.page_number > selectedPageNumber && p.review_status !== "approved",
          ) ??
          pages.find(
            (p) => p.page_number !== selectedPageNumber && p.review_status !== "approved",
          );
        if (nextPending) {
          setSelectedPageNumber(nextPending.page_number);
          setSelectedBlockId(null);
          setSyncRequest(null);
          nextMsg = ` → Page ${nextPending.page_number}`;
        }
      }
      handleStatusBanner(
        "success",
        `Page ${selectedPageNumber} approved (${res.saved_edits_count} edited, ${res.approved_blocks_count} approved${memNote})${nextMsg}.`,
      );
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError
          ? `${err.code}: ${err.message}`
          : "Batch save & approve failed.",
      );
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
      handleStatusBanner("info", "All unflagged lines on this page are already approved.");
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
      handleStatusBanner(
        "success",
        `Approved ${targets.length} unflagged line(s) on Page ${selectedPageNumber}.`,
      );
    } catch (err) {
      handleStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Batch approval failed.",
      );
    }
  }

  const approvedPagesCount = useMemo(
    () => pages.filter((p) => p.review_status === "approved").length,
    [pages],
  );
  const approvalPercent = useMemo(() => {
    const total = selectedBook?.page_count ?? pages.length;
    return total > 0 ? Math.round((approvedPagesCount / total) * 100) : 0;
  }, [approvedPagesCount, pages.length, selectedBook]);

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

  // Track last focused editable input for Telugu Virtual Keyboard
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
        `[data-block-id="${escapedId}"] textarea`,
      );
      if (isEditableTextElement(fallbackArea)) {
        lastEditableRef.current = fallbackArea;
        return fallbackArea;
      }
    }
    const firstArea = document.querySelector<HTMLTextAreaElement>(
      "textarea.block-textarea, textarea.block-textarea-compact",
    );
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

  const handleSelectView = useCallback(
    (nextView: WorkspaceView) => {
      if (nextView === activeView) return;
      if (activeView === "review" && !confirmDiscardIfDirty(`switch to ${nextView}`)) return;
      if (nextView !== "dictionary") {
        setDictionaryReturnContext(false);
      }
      setActiveView(nextView);
    },
    [activeView, confirmDiscardIfDirty],
  );

  function commitSubbarPageJump() {
    if (!selectedBook) return;
    const parsed = Number(pageJumpInput);
    if (Number.isInteger(parsed) && parsed >= 1 && parsed <= selectedBook.page_count) {
      navigateToPage(parsed);
    } else {
      setPageJumpInput(String(selectedPageNumber));
    }
  }

  return (
    <div className={keyboardOpen ? "app-shell has-keyboard" : "app-shell"}>
      <a href="#main-workspace" className="skip-link visually-hidden">
        Skip to workspace
      </a>

      <TopNavBar
        books={books}
        selectedBook={selectedBook}
        runs={mergedRuns}
        activeView={activeView}
        keyboardOpen={keyboardOpen}
        onSelectBook={navigateToBook}
        onSelectView={handleSelectView}
        onOpenImport={() => setImportDialogOpen(true)}
        onOpenOcrDrawer={() => setOcrDrawerOpen(true)}
        onToggleKeyboard={() => setKeyboardOpen((v) => !v)}
        onOpenShortcuts={() => setShortcutsOpen(true)}
      />

      <main id="main-workspace" className="app-main" tabIndex={-1}>
        {errorBanner && (
          <div className="status-banner error" role="alert">
            <span>{errorBanner}</span>
            <button
              type="button"
              className="banner-close-btn"
              aria-label="Dismiss error"
              onClick={() => setErrorBanner(null)}
            >
              ✕
            </button>
          </div>
        )}

        {selectedBook && activeView !== "dictionary" && (
          <OcrProgressStrip
            book={selectedBook}
            runs={mergedRuns}
            pages={pages}
            activeView={activeView}
            hideWhenReady
            onQuickStartSample={() => handleStartOcr("sample_5")}
            onQuickStartFull={() => handleStartOcr("full")}
            onResumeRun={handleResumeRun}
            onCancelRun={handleCancelRun}
            onGoToExport={() => handleSelectView("export")}
            onGoToReview={() => handleSelectView("review")}
          />
        )}

        {activeView === "dictionary" ? (
          <div className="centered-view-stage">
            <DictionaryPanel
              initialQuery={dictionaryQuery}
              keyboardOpen={keyboardOpen}
              returnToBookLabel={
                dictionaryReturnContext && selectedBook
                  ? `${selectedBook.title} · p.${selectedPageNumber}`
                  : null
              }
              onReturnToBook={() => {
                setDictionaryReturnContext(false);
                setActiveView("review");
              }}
              onToggleKeyboard={() => setKeyboardOpen((v) => !v)}
              onStatusBanner={handleStatusBanner}
            />
          </div>
        ) : activeView === "memory" ? (
          <div className="centered-view-stage">
            <CorrectionMemoryPanel
              selectedBookId={selectedBookId}
              onStatusBanner={handleStatusBanner}
            />
          </div>
        ) : activeView === "export" && selectedBook ? (
          <div className="centered-view-stage">
            <ExportPanel
              book={selectedBook}
              runs={mergedRuns}
              pages={pages}
              onStatusBanner={handleStatusBanner}
              onGoToReview={() => handleSelectView("review")}
            />
          </div>
        ) : booksLoaded && books.length === 0 ? (
          <div className="centered-view-stage welcome-stage">
            <WelcomeHero
              onImportClick={() => setImportDialogOpen(true)}
              uploadSlot={
                <BookUploadForm
                  busy={busyUpload}
                  maxUploadMb={capabilities?.max_upload_mb}
                  maxPdfPages={capabilities?.max_pdf_pages}
                  onUpload={handleUpload}
                />
              }
            />
          </div>
        ) : !selectedBook || !review ? (
          <div className="centered-view-stage">
            <div className="panel-card">
              <h2>Loading workspace…</h2>
              <p className="hint-text">Fetching the scan and OCR lines for the selected page.</p>
            </div>
          </div>
        ) : (
          <div className="proofread-shell">
            <div className="proofread-subbar" role="toolbar" aria-label="Page navigation and progress">
              <div className="subbar-left">
                <button
                  type="button"
                  className="btn-compact"
                  aria-pressed={pageRailOpen}
                  aria-label="Toggle pages navigator rail"
                  title="Toggle Pages Rail ([)"
                  onClick={() => setPageRailOpen((v) => !v)}
                >
                  ☰ Pages
                </button>

                <div className="page-stepper" role="group" aria-label="Step pages">
                  <button
                    type="button"
                    className="btn-compact"
                    disabled={selectedPageNumber <= 1}
                    title="Previous page (Alt+←)"
                    onClick={() => navigateToPage(selectedPageNumber - 1)}
                  >
                    ←
                  </button>
                  <form
                    className="page-jump-form"
                    onSubmit={(e) => {
                      e.preventDefault();
                      commitSubbarPageJump();
                    }}
                  >
                    <label htmlFor="subbar-page-jump" className="hint-text">
                      Page
                    </label>
                    <input
                      id="subbar-page-jump"
                      type="number"
                      className="page-jump-input"
                      min={1}
                      max={selectedBook.page_count}
                      value={pageJumpInput}
                      aria-label="Jump to page number"
                      onChange={(e) => setPageJumpInput(e.target.value)}
                      onBlur={commitSubbarPageJump}
                    />
                    <span className="hint-text">/ {selectedBook.page_count}</span>
                  </form>
                  <button
                    type="button"
                    className="btn-compact"
                    disabled={selectedPageNumber >= selectedBook.page_count}
                    title="Next page (Alt+→)"
                    onClick={() => navigateToPage(selectedPageNumber + 1)}
                  >
                    →
                  </button>
                </div>
              </div>

              <div className="subbar-right">
                <div
                  className="subbar-progress"
                  title={`${approvedPagesCount} of ${selectedBook.page_count} pages approved (${approvalPercent}%)`}
                >
                  <span className="hint-text">
                    <strong>{approvedPagesCount}</strong>/{selectedBook.page_count} approved ({approvalPercent}%)
                  </span>
                  <progress
                    className="subbar-progress-bar"
                    max={Math.max(selectedBook.page_count, 1)}
                    value={approvedPagesCount}
                    aria-label="Book approval progress"
                  />
                </div>

                <div
                  className="mobile-pane-switch"
                  role="group"
                  aria-label="Switch mobile pane view"
                >
                  <button
                    type="button"
                    className="btn-compact"
                    aria-pressed={mobilePane === "editor"}
                    onClick={() => setMobilePane("editor")}
                  >
                    Editor
                  </button>
                  <button
                    type="button"
                    className="btn-compact"
                    aria-pressed={mobilePane === "scan"}
                    onClick={() => setMobilePane("scan")}
                  >
                    Full Scan
                  </button>
                </div>
              </div>
            </div>

            <div className="proofread-body">
              <PageRail
                open={pageRailOpen}
                pages={pages}
                selectedPageNumber={selectedPageNumber}
                pageFilter={pageFilter}
                onChangeFilter={setPageFilter}
                onSelectPage={(p) => navigateToPage(p)}
                onClose={() => setPageRailOpen(false)}
              />

              <div className="review-split" data-mobile-pane={mobilePane}>
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
                  hidePageNav
                  onSelectBlock={handleSelectFromScan}
                  onSyncToEditor={() => {
                    if (selectedBlockId) {
                      triggerSync("editor", selectedBlockId);
                    }
                  }}
                  onToggleAutoSync={() => setAutoSyncBlocks((v) => !v)}
                  onNavigatePage={(p) => navigateToPage(p)}
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
                  onQuickStartOcr={async () => {
                    setOcrDrawerOpen(true);
                  }}
                  onOpenFullScanMobile={() => setMobilePane("scan")}
                  onDirtyCountChange={setDirtyBlockCount}
                  onSelectBlock={handleSelectFromEditor}
                  onLocateBlockOnScan={(blockId) => {
                    setSelectedBlockId(blockId);
                    setMobilePane("scan");
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
            </div>
          </div>
        )}
      </main>

      <TeluguKeyboard
        open={keyboardOpen}
        onClose={() => setKeyboardOpen(false)}
        onInsertText={handleKeyboardInsert}
        onBackspace={handleKeyboardBackspace}
        targetDescription={keyboardTargetLabel}
      />

      <ImportBookDialog
        open={importDialogOpen}
        busy={busyUpload}
        maxUploadMb={capabilities?.max_upload_mb}
        maxPdfPages={capabilities?.max_pdf_pages}
        onClose={() => setImportDialogOpen(false)}
        onUpload={handleUpload}
      />

      {selectedBook && (
        <OcrRunnerDrawer
          open={ocrDrawerOpen}
          book={selectedBook}
          runs={mergedRuns}
          capabilities={capabilities}
          isOcrRunning={isOcrRunning}
          usePaddle={usePaddle}
          useTesseract={useTesseract}
          ocrStartPage={ocrStartPage}
          ocrEndPage={ocrEndPage}
          ocrPreprocessing={ocrPreprocessing}
          ocrRenderDpi={ocrRenderDpi}
          ocrForceRerun={ocrForceRerun}
          ocrIncludeDigital={ocrIncludeDigital}
          onUsePaddleChange={setUsePaddle}
          onUseTesseractChange={setUseTesseract}
          onStartPageChange={setOcrStartPage}
          onEndPageChange={setOcrEndPage}
          onPreprocessingChange={setOcrPreprocessing}
          onRenderDpiChange={setOcrRenderDpi}
          onForceRerunChange={setOcrForceRerun}
          onIncludeDigitalChange={setOcrIncludeDigital}
          onStartOcr={handleStartOcr}
          onResumeRun={handleResumeRun}
          onCancelRun={handleCancelRun}
          onClose={() => setOcrDrawerOpen(false)}
        />
      )}

      <QuickLookupDialog
        word={quickLookupWord}
        onClose={() => setQuickLookupWord(null)}
        onOpenFullDictionary={(w) => {
          setDictionaryQuery(w);
          setDictionaryReturnContext(Boolean(selectedBook));
          setActiveView("dictionary");
        }}
      />

      <ShortcutsDialog open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />

      <ToastRegion toasts={toasts} onDismiss={dismissToast} />
    </div>
  );
}
