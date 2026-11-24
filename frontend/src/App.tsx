import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiClientError,
  approveCorrection,
  deleteBook,
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
  updatePageReviewStatus,
  uploadBook,
} from "./api/client";
import { BookUploadForm } from "./components/BookUploadForm";
import { CorrectionMemoryPanel } from "./components/CorrectionMemoryPanel";
import { DeleteConfirmDialog } from "./components/DeleteConfirmDialog";
import { ExportPanel } from "./components/ExportPanel";
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
  BookOCRRunSummary,
  BookSummary,
  CorrectionSuggestionItem,
  HostCapabilities,
  OCRRunStatus,
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
  const [syncRequest, setSyncRequest] = useState<{
    target: "scan" | "editor";
    blockId: string;
    seq: number;
  } | null>(null);
  const syncSeqCounterRef = useRef(0);
  const [keyboardOpen, setKeyboardOpen] = useState(false);
  const lastEditableRef = useRef<EditableTextElement | null>(null);
  const [keyboardTargetLabel, setKeyboardTargetLabel] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"review" | "memory" | "export">("review");

  const [uploadExpanded, setUploadExpanded] = useState(true);
  const initializedCollapseRef = useRef(false);
  const [pageFilter, setPageFilter] = useState<"all" | "pending" | "approved">("all");

  const [usePaddle, setUsePaddle] = useState(true);
  const [useTesseract, setUseTesseract] = useState(true);
  const [capabilities, setCapabilities] = useState<HostCapabilities | null>(null);
  const [ocrStartPage, setOcrStartPage] = useState("1");
  const [ocrEndPage, setOcrEndPage] = useState("");
  const [busyUpload, setBusyUpload] = useState(false);
  const [busyBlockId, setBusyBlockId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BookSummary | null>(null);
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
          const advanced = prevEntry && st.progress_current > prevEntry.progress;
          const becameTerminal =
            st.status === "completed" || st.status === "partial" || st.status === "failed";
          if (advanced || becameTerminal) {
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
          setBanner({
            kind: finishedRun.status === "failed" ? "error" : "success",
            text: `${formatEngineLabel(finishedRun.engine)} ${finishedRun.status} (${finishedRun.progress_current}/${finishedRun.progress_total} pages).`,
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
      const created = await startOcrRun(selectedBookId, engines, { pageRange });
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

  async function handleSaveBlockEdit(
    blockId: string,
    editedText: string,
    action: "corrected" | "approved" | "reverted",
    reviewNote?: string,
    options?: SaveEditOptions,
  ) {
    if (!selectedBookId) return;
    setBusyBlockId(blockId);
    try {
      const res = await submitBlockEdit(blockId, {
        edited_text: editedText,
        action,
        review_note: reviewNote,
        add_to_correction_memory: options?.addToMemory ?? false,
        memory_scope: options?.memoryScope ?? "book_only",
        correction_type: options?.correctionType,
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

  async function confirmDeleteBook() {
    if (!deleteTarget) return;
    const targetId = deleteTarget.book_id;
    const targetTitle = deleteTarget.title;
    setDeleteTarget(null);
    try {
      await deleteBook(targetId);
      setBanner({ kind: "success", text: `Deleted "${targetTitle}".` });
      await refreshBooks();
    } catch (err) {
      setBanner({
        kind: "error",
        text: err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Delete failed.",
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
              <div style={{ marginTop: "0.75rem" }}>
                <button
                  type="button"
                  className="danger btn-compact"
                  onClick={() => setDeleteTarget(selectedBook)}
                >
                  Delete Selected Book
                </button>
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
          {selectedBook && (
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

          {selectedBook && (
            <OcrProgressStrip
              book={selectedBook}
              runs={mergedRuns}
              pages={pages}
              activeView={activeView}
              onQuickStartSample={() => handleStartOcr("sample_5")}
              onQuickStartFull={() => handleStartOcr("full")}
              onResumeRun={handleResumeRun}
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

          {activeView === "memory" ? (
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
                keyboardOpen={keyboardOpen}
                onQuickStartOcr={() => handleStartOcr()}
                onSelectBlock={handleSelectFromEditor}
                onLocateBlockOnScan={(blockId) => {
                  setSelectedBlockId(blockId);
                  triggerSync("scan", blockId);
                }}
                onSyncToScan={() => {
                  if (selectedBlockId) {
                    triggerSync("scan", selectedBlockId);
                  }
                }}
                onToggleAutoSync={() => setAutoSyncBlocks((v) => !v)}
                onToggleKeyboard={() => setKeyboardOpen((v) => !v)}
                onSelectPrimaryRun={(runId) => setSelectedPrimaryRunId(runId)}
                onSaveEdit={handleSaveBlockEdit}
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

      <DeleteConfirmDialog
        open={deleteTarget !== null}
        bookTitle={deleteTarget?.title ?? ""}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void confirmDeleteBook()}
      />
    </div>
  );
}
