import { useCallback, useEffect, useState } from "react";
import {
  ApiClientError,
  approveCorrection,
  deleteBook,
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
import { ReviewEditorPanel, type SaveEditOptions } from "./components/ReviewEditorPanel";
import { SourcePageViewer } from "./components/SourcePageViewer";
import type {
  BookOCRRunSummary,
  BookSummary,
  CorrectionSuggestionItem,
  OCRRunStatus,
  PageReviewPayload,
  PageSummary,
  ReviewBlock,
} from "./types/api";

export function App() {
  const [books, setBooks] = useState<BookSummary[]>([]);
  const [selectedBookId, setSelectedBookId] = useState<string | null>(null);
  const [pages, setPages] = useState<PageSummary[]>([]);
  const [selectedPageNumber, setSelectedPageNumber] = useState<number>(1);
  const [runs, setRuns] = useState<BookOCRRunSummary[]>([]);
  const [selectedPrimaryRunId, setSelectedPrimaryRunId] = useState<string | null>(null);
  const [review, setReview] = useState<PageReviewPayload | null>(null);
  const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<"review" | "memory" | "export">("review");

  const [usePaddle, setUsePaddle] = useState(true);
  const [useTesseract, setUseTesseract] = useState(true);
  const [ocrStartPage, setOcrStartPage] = useState("1");
  const [ocrEndPage, setOcrEndPage] = useState("");
  const [activeRunStatus, setActiveRunStatus] = useState<OCRRunStatus | null>(null);
  const [busyUpload, setBusyUpload] = useState(false);

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
  const [busyBlockId, setBusyBlockId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<BookSummary | null>(null);
  const [banner, setBanner] = useState<{ kind: "info" | "success" | "error"; text: string } | null>(
    null,
  );

  const handleStatusBanner = useCallback(
    (kind: "info" | "success" | "error", text: string) => {
      setBanner({ kind, text });
    },
    [],
  );

  const refreshBooks = useCallback(async () => {
    const items = await listBooks();
    setBooks(items);
    if (items.length > 0 && (!selectedBookId || !items.some((b) => b.book_id === selectedBookId))) {
      setSelectedBookId(items[0].book_id);
      setSelectedPageNumber(1);
    } else if (items.length === 0) {
      setSelectedBookId(null);
      setPages([]);
      setRuns([]);
      setReview(null);
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

  useEffect(() => {
    if (!activeRunStatus) return;
    if (activeRunStatus.status === "completed" || activeRunStatus.status === "failed" || activeRunStatus.status === "partial") {
      return;
    }
    const timer = window.setInterval(async () => {
      try {
        const next = await getOcrRunStatus(activeRunStatus.ocr_run_id);
        setActiveRunStatus(next);
        if (next.status === "completed" || next.status === "partial" || next.status === "failed") {
          if (selectedBookId) {
            await refreshBookDetail(selectedBookId);
            await refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId);
          }
          setBanner({
            kind: next.status === "failed" ? "error" : "success",
            text: `OCR run finished with status "${next.status}" (${next.progress_current}/${next.progress_total} pages).`,
          });
        }
      } catch {
        // Keep polling transiently.
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [activeRunStatus, selectedBookId, selectedPageNumber, selectedPrimaryRunId, refreshBookDetail, refreshReview]);

  async function handleUpload(formData: FormData) {
    setBusyUpload(true);
    try {
      const res = await uploadBook(formData);
      await refreshBooks();
      setSelectedBookId(res.book_id);
      setSelectedPageNumber(1);
      setSelectedPrimaryRunId(null);
      setActiveView("review");
      setBanner({
        kind: "success",
        text: res.duplicate
          ? `Book "${res.title}" matched existing SHA-256 (${res.page_count} pages).`
          : `Imported "${res.title}" (${res.page_count} pages at 300 DPI).`,
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

  async function handleStartOcr() {
    if (!selectedBookId) return;
    const engines: string[] = [];
    if (usePaddle) engines.push("paddle_ppocrv5_te");
    if (useTesseract) engines.push("tesseract_tel_best");
    if (engines.length === 0) {
      setBanner({ kind: "error", text: "Select at least one OCR engine." });
      return;
    }

    const totalPages = selectedBook?.page_count ?? review?.page_count ?? 0;
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
    const pageRange =
      totalPages > 0 && startVal === 1 && endVal === totalPages
        ? null
        : { start: startVal, end: endVal };

    try {
      const created = await startOcrRun(selectedBookId, engines, { pageRange });
      const statusObj = await getOcrRunStatus(created.ocr_run_id);
      setActiveRunStatus(statusObj);
      await refreshBookDetail(selectedBookId);
      if (created.reused_existing) {
        await refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId);
        setBanner({ kind: "info", text: "Reused existing completed OCR run." });
      } else {
        setBanner({
          kind: "info",
          text: `Started OCR (${engines.join(" + ")}) for ${created.pages_total} scanned/mixed page(s)${
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
      setActiveRunStatus(resumed);
      setBanner({ kind: "info", text: `Resumed OCR run ${runId.slice(0, 8)}...` });
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
      setBanner({ kind: "success", text: `Page ${selectedPageNumber} marked "${reviewStatus}".` });
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

  const selectedBook = books.find((b) => b.book_id === selectedBookId) ?? null;

  return (
    <div className="app-shell">
      <a href="#main-review" className="skip-link visually-hidden">
        Skip to review workspace
      </a>

      <header className="app-header">
        <div>
          <h1>Telugu Book Digitizer — Review Studio</h1>
          <span className="header-meta">
            Local-first OCR inspection &amp; contextual correction memory
          </span>
        </div>

        <div className="header-actions">
          <button
            type="button"
            className={activeView === "review" ? "primary" : undefined}
            aria-pressed={activeView === "review"}
            onClick={() => setActiveView("review")}
          >
            Page Review
          </button>
          <button
            type="button"
            className={activeView === "memory" ? "primary" : undefined}
            aria-pressed={activeView === "memory"}
            onClick={() => setActiveView("memory")}
          >
            Correction Memory
          </button>
          <button
            type="button"
            className={activeView === "export" ? "primary" : undefined}
            aria-pressed={activeView === "export"}
            disabled={!selectedBook}
            onClick={() => setActiveView("export")}
          >
            Export DOCX / TXT
          </button>
        </div>
      </header>

      <div className="workspace-grid">
        <aside className="sidebar" aria-label="Library and OCR controls">
          <BookUploadForm busy={busyUpload} onUpload={handleUpload} />

          <section className="panel-card">
            <h2>Books ({books.length})</h2>
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
                          {book.page_count} page(s) · {book.scanned_pages_count} scanned ·{" "}
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
                  className="danger"
                  onClick={() => setDeleteTarget(selectedBook)}
                >
                  Delete Selected Book
                </button>
              </div>
            )}
          </section>

          {selectedBook && (
            <section className="panel-card">
              <h2>Run OCR Engines</h2>
              <fieldset style={{ border: "1px solid var(--border)", borderRadius: "0.45rem", padding: "0.55rem" }}>
                <legend className="hint-text">Engines</legend>
                <div className="checkbox-row">
                  <input
                    id="eng-paddle"
                    type="checkbox"
                    checked={usePaddle}
                    onChange={(e) => setUsePaddle(e.target.checked)}
                  />
                  <label htmlFor="eng-paddle">PaddleOCR PP-OCRv5 (`te`)</label>
                </div>
                <div className="checkbox-row">
                  <input
                    id="eng-tess"
                    type="checkbox"
                    checked={useTesseract}
                    onChange={(e) => setUseTesseract(e.target.checked)}
                  />
                  <label htmlFor="eng-tess">Tesseract 5 (`tel` tessdata_best)</label>
                </div>
              </fieldset>

              <fieldset
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: "0.45rem",
                  padding: "0.55rem",
                  marginTop: "0.55rem",
                }}
              >
                <legend className="hint-text">Page Range</legend>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.45rem" }}>
                  <label className="hint-text" htmlFor="ocr-start-page">
                    Start page
                    <input
                      id="ocr-start-page"
                      type="number"
                      min={1}
                      max={selectedBook.page_count}
                      value={ocrStartPage}
                      onChange={(e) => setOcrStartPage(e.target.value)}
                      style={{ width: "100%", marginTop: "0.2rem" }}
                    />
                  </label>
                  <label className="hint-text" htmlFor="ocr-end-page">
                    End page
                    <input
                      id="ocr-end-page"
                      type="number"
                      min={1}
                      max={selectedBook.page_count}
                      value={ocrEndPage}
                      placeholder={String(selectedBook.page_count)}
                      onChange={(e) => setOcrEndPage(e.target.value)}
                      style={{ width: "100%", marginTop: "0.2rem" }}
                    />
                  </label>
                </div>
                <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.45rem", flexWrap: "wrap" }}>
                  <button
                    type="button"
                    onClick={() => {
                      setOcrStartPage("1");
                      setOcrEndPage(String(Math.min(5, selectedBook.page_count)));
                    }}
                  >
                    Pages 1–5
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setOcrStartPage("1");
                      setOcrEndPage(String(selectedBook.page_count));
                    }}
                  >
                    All ({selectedBook.page_count})
                  </button>
                </div>
                <p className="hint-text" style={{ marginTop: "0.4rem", marginBottom: 0 }}>
                  CPU speed: Tesseract ~0.4 s/page; PaddleOCR PP-OCRv5 ~90 s/page. For large PDFs, test Pages 1–5 first.
                </p>
              </fieldset>

              <div style={{ marginTop: "0.65rem", display: "flex", flexDirection: "column", gap: "0.45rem" }}>
                <button
                  type="button"
                  className="primary"
                  disabled={
                    Boolean(
                      activeRunStatus &&
                        (activeRunStatus.status === "queued" || activeRunStatus.status === "running"),
                    ) || runs.some((r) => r.status === "queued" || r.status === "running")
                  }
                  onClick={() => void handleStartOcr()}
                >
                  {Boolean(
                    activeRunStatus &&
                      (activeRunStatus.status === "queued" || activeRunStatus.status === "running"),
                  ) || runs.some((r) => r.status === "queued" || r.status === "running")
                    ? "OCR Running..."
                    : "Run Selected OCR"}
                </button>
                {activeRunStatus && (
                  <p className="hint-text" role="status">
                    Active run: <strong>{activeRunStatus.status}</strong> (
                    {activeRunStatus.progress_current}/{activeRunStatus.progress_total})
                  </p>
                )}
                {runs
                  .filter((r) => r.status === "partial" || r.status === "failed")
                  .map((r) => (
                    <button
                      key={r.ocr_run_id}
                      type="button"
                      onClick={() => void handleResumeRun(r.ocr_run_id)}
                    >
                      Resume {r.engine} ({r.status})
                    </button>
                  ))}
              </div>
            </section>
          )}

          {pages.length > 0 && (
            <nav className="panel-card" aria-label="Book pages">
              <h2>Pages</h2>
              <ul className="page-list">
                {pages.map((p) => (
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
                      <div className="badge-row">
                        <strong>Page {p.page_number}</strong>
                        <span className="badge">{p.page_kind}</span>
                        <span
                          className={`badge ${p.review_status === "approved" ? "ok" : p.review_status === "needs_attention" ? "warn" : ""}`}
                        >
                          {p.review_status}
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
          {banner && (
            <div
              className={`status-banner ${banner.kind === "error" ? "error" : banner.kind === "success" ? "success" : ""}`}
              role="status"
              aria-live="polite"
            >
              {banner.text}
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
              runs={runs}
              onStatusBanner={handleStatusBanner}
              onGoToReview={() => setActiveView("review")}
            />
          ) : !review ? (
            <div className="panel-card">
              <h2>No Book Selected</h2>
              <p className="hint-text">
                Upload a printed Telugu PDF on the left, run PaddleOCR / Tesseract, and inspect or
                correct lines side-by-side against the original scan.
              </p>
            </div>
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
                onSelectBlock={setSelectedBlockId}
                onNavigatePage={(p) => {
                  setSelectedPageNumber(p);
                  setSelectedBlockId(null);
                }}
              />

              <ReviewEditorPanel
                review={review}
                selectedBlockId={selectedBlockId}
                busyBlockId={busyBlockId}
                ocrRunning={
                  Boolean(
                    activeRunStatus &&
                      (activeRunStatus.status === "queued" || activeRunStatus.status === "running"),
                  ) || runs.some((r) => r.status === "queued" || r.status === "running")
                }
                onQuickStartOcr={handleStartOcr}
                onSelectBlock={setSelectedBlockId}
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

      <DeleteConfirmDialog
        open={deleteTarget !== null}
        bookTitle={deleteTarget?.title ?? ""}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void confirmDeleteBook()}
      />
    </div>
  );
}
