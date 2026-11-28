import { useCallback, useEffect, useId, useState, type FormEvent } from "react";
import { ApiClientError, createBookExport, listBookExports, resolveAppUrl } from "../api/client";
import type { BookOCRRunSummary, BookSummary, ExportRecord, PageSummary } from "../types/api";
import { computeBookOcrCoverage, formatEngineLabel, formatLayoutMode } from "../utils/formatters";

interface ExportPanelProps {
  book: BookSummary;
  runs: BookOCRRunSummary[];
  pages?: PageSummary[];
  onStatusBanner: (kind: "info" | "success" | "error", text: string) => void;
  onGoToReview?: () => void;
}

export function ExportPanel({
  book,
  runs,
  pages = [],
  onStatusBanner,
  onGoToReview,
}: ExportPanelProps) {
  const headingId = useId();
  const modeId = useId();
  const versionId = useId();
  const runId = useId();
  const fontId = useId();

  const usableRuns = runs.filter((r) => r.status === "completed" || r.status === "partial");
  const coverage = computeBookOcrCoverage(book, runs);
  const needsOcrFirst =
    usableRuns.length === 0 && book.scanned_pages_count + book.mixed_pages_count > 0;

  const approvedCount = pages.filter((p) => p.review_status === "approved").length;
  const unreviewedCount = Math.max(0, book.page_count - approvedCount);

  const [exportChoice, setExportChoice] = useState<
    "docx_page_preserving" | "docx_editable_flow" | "txt"
  >("docx_page_preserving");
  const [textVersion, setTextVersion] = useState<"human_approved" | "raw_ocr">("human_approved");
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const [fontFamily, setFontFamily] = useState("Noto Serif Telugu");
  const [includePageNumbers, setIncludePageNumbers] = useState(true);
  const [includeToc, setIncludeToc] = useState(false);
  const [busy, setBusy] = useState(false);
  const [exportsList, setExportsList] = useState<ExportRecord[]>([]);

  const loadExports = useCallback(async () => {
    try {
      const items = await listBookExports(book.book_id);
      setExportsList(items);
    } catch {
      // Ignore transient list errors.
    }
  }, [book.book_id]);

  useEffect(() => {
    void loadExports();
  }, [loadExports]);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const isTxt = exportChoice === "txt";
      const layoutMode =
        exportChoice === "docx_editable_flow" ? "editable_flow" : "page_preserving";

      const record = await createBookExport(book.book_id, {
        format: isTxt ? "txt" : "docx",
        layout_mode: layoutMode,
        text_version: textVersion,
        primary_run_id: selectedRunId || null,
        font_family: fontFamily,
        body_font_size: 12,
        include_page_numbers: includePageNumbers,
        include_table_of_contents: exportChoice === "docx_editable_flow" ? includeToc : false,
      });

      onStatusBanner(
        "success",
        record.is_fully_reviewed
          ? `Export ready: ${record.filename}`
          : `Export ready (labeled unreviewed/partial): ${record.filename}`,
      );
      await loadExports();

      const anchor = document.createElement("a");
      anchor.href = resolveAppUrl(record.download_url);
      anchor.download = record.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
    } catch (err) {
      onStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Export failed.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel-card centered-stage-card" aria-labelledby={headingId}>
      <div className="section-head-row">
        <div>
          <h2 id={headingId} className="card-title" style={{ margin: 0 }}>
            <span className="card-icon" aria-hidden="true">
              📄
            </span>
            Export Document — <span lang="te">{book.title}</span>
          </h2>
          <p className="hint-text" style={{ margin: "0.2rem 0 0" }}>
            Generates genuine Telugu Unicode DOCX (page-preserving or editable-flow) or UTF-8 TXT and validates XML/paragraph integrity before download.
          </p>
        </div>
        {onGoToReview && (
          <button type="button" className="btn-compact" onClick={onGoToReview}>
            ← Back to Proofreading
          </button>
        )}
      </div>

      {needsOcrFirst && (
        <div className="status-banner error" role="alert" style={{ marginBottom: "1rem" }}>
          <div>
            <strong>No completed OCR run exists for this book yet.</strong> This book has{" "}
            {book.scanned_pages_count + book.mixed_pages_count} scanned/mixed page(s) and 0 OCR text
            blocks. Run OCR first before generating DOCX or TXT.
            {onGoToReview && (
              <div style={{ marginTop: "0.5rem" }}>
                <button type="button" onClick={onGoToReview}>
                  Go to Page Review &amp; Run OCR
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {!needsOcrFirst && coverage.isPartialCoverage && (
        <div className="export-callout warn" role="status">
          <div>
            <strong>
              Partial OCR coverage ({coverage.coveredPagesCount} of {coverage.totalPages} pages OCR&apos;d)
            </strong>
            <span className="hint-text">
              {" "}
              · Only Pages {coverage.coveredRangeLabel} currently have OCR text. Continue OCR on
              Pages {coverage.nextStartPage}–{coverage.nextEndPage} for a complete book export.
            </span>
          </div>
          {onGoToReview && (
            <button type="button" className="btn-compact" onClick={onGoToReview}>
              Continue OCR →
            </button>
          )}
        </div>
      )}

      {!needsOcrFirst && pages.length > 0 && (
        <div className={`export-coverage-callout ${unreviewedCount === 0 ? "ok" : "info"}`}>
          <strong>
            {unreviewedCount === 0
              ? `✓ All ${book.page_count} pages human-approved`
              : `${approvedCount} of ${book.page_count} pages human-approved`}
          </strong>
          {unreviewedCount > 0 && (
            <span className="hint-text">
              {" "}
              · Remaining {unreviewedCount} page(s) will fall back to your selected OCR run (labeled partial in the manifest).
            </span>
          )}
        </div>
      )}

      <div className="export-grid">
        <form onSubmit={handleSubmit} className="export-form-col">
          <div className="form-field">
            <label htmlFor={modeId}>Export format &amp; layout mode</label>
            <select
              id={modeId}
              value={exportChoice}
              onChange={(e) =>
                setExportChoice(
                  e.target.value as "docx_page_preserving" | "docx_editable_flow" | "txt",
                )
              }
            >
              <option value="docx_page_preserving">Page-preserving DOCX (.docx)</option>
              <option value="docx_editable_flow">Editable-flow DOCX (.docx)</option>
              <option value="txt">Plain Text UTF-8 (.txt)</option>
            </select>
          </div>

          <div className="form-field">
            <label htmlFor={versionId}>Transcript version</label>
            <select
              id={versionId}
              value={textVersion}
              onChange={(e) => setTextVersion(e.target.value as "human_approved" | "raw_ocr")}
            >
              <option value="human_approved">Human-reviewed / latest edits (recommended)</option>
              <option value="raw_ocr">Raw OCR output (unreviewed machine text)</option>
            </select>
          </div>

          {usableRuns.length > 0 && (
            <div className="form-field">
              <label htmlFor={runId}>Source OCR run (for unedited or raw OCR pages)</label>
              <select
                id={runId}
                value={selectedRunId}
                onChange={(e) => setSelectedRunId(e.target.value)}
              >
                <option value="">Auto-select best per page (stitches multi-range runs &amp; approved edits)</option>
                {usableRuns.map((run) => (
                  <option key={run.ocr_run_id} value={run.ocr_run_id} title={run.model_id ?? undefined}>
                    {formatEngineLabel(run.engine)} ({run.progress_current ?? 0}/{run.progress_total ?? book.page_count} pages)
                  </option>
                ))}
              </select>
            </div>
          )}

          {exportChoice !== "txt" && (
            <>
              <div className="form-field">
                <label htmlFor={fontId}>Telugu font family</label>
                <select
                  id={fontId}
                  value={fontFamily}
                  onChange={(e) => setFontFamily(e.target.value)}
                >
                  <option value="Noto Serif Telugu">Noto Serif Telugu</option>
                  <option value="Noto Sans Telugu">Noto Sans Telugu</option>
                  <option value="Kohinoor Telugu">Kohinoor Telugu (macOS)</option>
                </select>
              </div>

              <div className="checkbox-row">
                <input
                  id="exp-page-nums"
                  type="checkbox"
                  checked={includePageNumbers}
                  onChange={(e) => setIncludePageNumbers(e.target.checked)}
                />
                <label htmlFor="exp-page-nums">Include page numbers / source page markers</label>
              </div>

              {exportChoice === "docx_editable_flow" && (
                <div className="checkbox-row">
                  <input
                    id="exp-toc"
                    type="checkbox"
                    checked={includeToc}
                    onChange={(e) => setIncludeToc(e.target.checked)}
                  />
                  <label htmlFor="exp-toc">Include Table of Contents field</label>
                </div>
              )}
            </>
          )}

          <button type="submit" className="primary" disabled={busy || needsOcrFirst}>
            {busy ? "Generating & Validating…" : "Generate & Download Export"}
          </button>
        </form>

        <div className="export-history-col">
          <h3 style={{ marginTop: 0 }}>Generated Exports ({exportsList.length})</h3>
          {exportsList.length === 0 ? (
            <p className="hint-text">No exports generated for this book yet.</p>
          ) : (
            <ul className="book-list">
              {exportsList.map((item) => (
                <li key={item.export_id} className="export-history-card">
                  <div>
                    <strong lang="te">{item.filename}</strong>
                    <div className="badge-row" style={{ marginTop: "0.25rem" }}>
                      <span className="badge">{item.format.toUpperCase()}</span>
                      <span className="badge">{formatLayoutMode(item.layout_mode)}</span>
                      <span className="badge">{formatLayoutMode(item.text_version)}</span>
                      <span className={`badge ${item.is_fully_reviewed ? "ok" : "warn"}`}>
                        {item.is_fully_reviewed ? "✓ Reviewed" : "⚠ Partial / Unreviewed"}
                      </span>
                      {Boolean(item.validation?.passed) && (
                        <span className="badge ok">✓ Verified</span>
                      )}
                    </div>
                  </div>
                  <div className="badge-row">
                    <a
                      href={resolveAppUrl(item.download_url)}
                      download={item.filename}
                      className="btn-link primary"
                    >
                      Download
                    </a>
                    <a
                      href={resolveAppUrl(item.manifest_url)}
                      target="_blank"
                      rel="noreferrer"
                      className="btn-link"
                    >
                      Sidecar JSON
                    </a>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </section>
  );
}
