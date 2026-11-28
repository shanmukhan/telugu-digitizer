import { useEffect, useId, useRef } from "react";
import type { BookOCRRunSummary, BookSummary, HostCapabilities } from "../types/api";
import { computeBookOcrCoverage, formatEngineLabel } from "../utils/formatters";

interface OcrRunnerDrawerProps {
  open: boolean;
  book: BookSummary;
  runs: BookOCRRunSummary[];
  capabilities: HostCapabilities | null;
  isOcrRunning: boolean;
  usePaddle: boolean;
  useTesseract: boolean;
  ocrStartPage: string;
  ocrEndPage: string;
  ocrPreprocessing: "none" | "deskew" | "contrast_clahe" | "textured_bold";
  ocrRenderDpi: number;
  ocrForceRerun: boolean;
  ocrIncludeDigital: boolean;
  onUsePaddleChange: (v: boolean) => void;
  onUseTesseractChange: (v: boolean) => void;
  onStartPageChange: (v: string) => void;
  onEndPageChange: (v: string) => void;
  onPreprocessingChange: (v: "none" | "deskew" | "contrast_clahe" | "textured_bold") => void;
  onRenderDpiChange: (v: number) => void;
  onForceRerunChange: (v: boolean) => void;
  onIncludeDigitalChange: (v: boolean) => void;
  onStartOcr: (preset?: "sample_5" | "full" | "quick_tesseract" | "remaining") => Promise<void>;
  onResumeRun: (runId: string) => Promise<void>;
  onCancelRun: (runId: string) => Promise<void>;
  onClose: () => void;
}

export function OcrRunnerDrawer({
  open,
  book,
  runs,
  capabilities,
  isOcrRunning,
  usePaddle,
  useTesseract,
  ocrStartPage,
  ocrEndPage,
  ocrPreprocessing,
  ocrRenderDpi,
  ocrForceRerun,
  ocrIncludeDigital,
  onUsePaddleChange,
  onUseTesseractChange,
  onStartPageChange,
  onEndPageChange,
  onPreprocessingChange,
  onRenderDpiChange,
  onForceRerunChange,
  onIncludeDigitalChange,
  onStartOcr,
  onResumeRun,
  onCancelRun,
  onClose,
}: OcrRunnerDrawerProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  const paddleAvailable = capabilities?.engines.paddle_ppocrv5_te?.available !== false;
  const tesseractAvailable = capabilities?.engines.tesseract_tel_best?.available !== false;

  const activeRuns = runs.filter((r) => r.status === "running" || r.status === "queued");
  const resumableRuns = runs.filter((r) => r.status === "partial" || r.status === "failed");
  const completedRuns = runs.filter((r) => r.status === "completed");
  const coverage = computeBookOcrCoverage(book, runs);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") {
        dialog.showModal();
      } else {
        dialog.setAttribute("open", "");
      }
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || "closedBy" in HTMLDialogElement.prototype) return;
    const outside = (e: PointerEvent) => {
      const r = dialog.getBoundingClientRect();
      return e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom;
    };
    let pressedOutside = false;
    const onDown = (e: PointerEvent) => {
      pressedOutside = outside(e);
    };
    const onUp = (e: PointerEvent) => {
      if (pressedOutside && outside(e)) dialog.close();
    };
    dialog.addEventListener("pointerdown", onDown);
    dialog.addEventListener("pointerup", onUp);
    return () => {
      dialog.removeEventListener("pointerdown", onDown);
      dialog.removeEventListener("pointerup", onUp);
    };
  }, []);

  return (
    <dialog
      ref={dialogRef}
      className="drawer-dialog ocr-drawer"
      {...({ closedby: "any" } as Record<string, unknown>)}
      aria-labelledby={titleId}
      onClose={() => {
        const d = dialogRef.current;
        if (d) d.returnValue = "";
        onClose();
      }}
    >
      <div className="drawer-head">
        <div>
          <h1 id={titleId}>OCR Engines &amp; Runs</h1>
          <p className="hint-text" style={{ margin: "0.15rem 0 0" }}>
            <span lang="te">{book.title}</span> · {book.scanned_pages_count + book.mixed_pages_count} scanned ·{" "}
            {book.digital_text_pages_count} digital
          </p>
        </div>
        <form method="dialog">
          <button type="submit" value="close" className="btn-compact" aria-label="Close OCR panel" autoFocus>
            ✕
          </button>
        </form>
      </div>

      <div className="drawer-body">
        {activeRuns.length > 0 && (
          <section className="drawer-section" aria-label="Active OCR runs">
            <h2 className="drawer-section-title">Running / Queued</h2>
            <ul className="drawer-run-list">
              {activeRuns.map((run) => (
                <li key={run.ocr_run_id} className="drawer-run-item active">
                  <div>
                    <strong>{formatEngineLabel(run.engine)}</strong>
                    <div className="hint-text">
                      {run.status === "running"
                        ? `${run.progress_current ?? 0} / ${run.progress_total ?? book.scanned_pages_count} pages`
                        : "Queued"}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="danger btn-compact"
                    onClick={() => void onCancelRun(run.ocr_run_id)}
                  >
                    Cancel
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {resumableRuns.length > 0 && (
          <section className="drawer-section" aria-label="Paused OCR runs">
            <h2 className="drawer-section-title">Resume Paused / Partial Runs</h2>
            <ul className="drawer-run-list">
              {resumableRuns.map((run) => (
                <li key={run.ocr_run_id} className="drawer-run-item warn">
                  <div>
                    <strong>{formatEngineLabel(run.engine)}</strong>
                    <div className="hint-text">
                      {run.progress_current ?? 0} / {run.progress_total || book.scanned_pages_count} pages saved
                    </div>
                  </div>
                  <button
                    type="button"
                    className="primary btn-compact"
                    disabled={isOcrRunning}
                    onClick={async () => {
                      await onResumeRun(run.ocr_run_id);
                      onClose();
                    }}
                  >
                    Resume
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="drawer-section" aria-label="Quick OCR presets">
          <h2 className="drawer-section-title">Quick Presets</h2>
          <div className="preset-grid">
            {coverage.isPartialCoverage && (
              <button
                type="button"
                className="preset-card preset-card-highlight"
                disabled={isOcrRunning || (!usePaddle && !useTesseract)}
                onClick={async () => {
                  await onStartOcr("remaining");
                  onClose();
                }}
              >
                <strong>
                  ▶ Continue Remaining Pages ({coverage.nextStartPage}–{coverage.nextEndPage})
                </strong>
                <span className="hint-text">
                  Process the remaining {coverage.remainingPagesCount} page(s) with your selected
                  engines. Approved edits on Pages {coverage.coveredRangeLabel} are preserved for
                  review and export.
                </span>
              </button>
            )}

            <button
              type="button"
              className="preset-card"
              disabled={isOcrRunning || !tesseractAvailable}
              onClick={async () => {
                await onStartOcr("quick_tesseract");
                onClose();
              }}
            >
              <strong>
                ⚡{" "}
                {coverage.isPartialCoverage
                  ? `Fast Draft Remaining (${coverage.nextStartPage}–${coverage.nextEndPage})`
                  : "Quick Full-Book Draft"}
              </strong>
              <span className="hint-text">
                Tesseract 5 Telugu (~0.4s/page CPU) across{" "}
                {coverage.isPartialCoverage
                  ? `remaining ${coverage.remainingPagesCount} pages`
                  : `all ${book.page_count} pages`}{" "}
                for fast proofreading.
              </span>
            </button>

            <button
              type="button"
              className="preset-card"
              disabled={isOcrRunning || (!paddleAvailable && !tesseractAvailable)}
              onClick={async () => {
                await onStartOcr("sample_5");
                onClose();
              }}
            >
              <strong>🔎 5-Page Accuracy Test</strong>
              <span className="hint-text">
                Run selected engines on Pages 1–{Math.min(5, book.page_count)} to preview Telugu accuracy first.
              </span>
            </button>
          </div>
        </section>

        <section className="drawer-section" aria-label="Custom OCR configuration">
          <h2 className="drawer-section-title">Custom Run Configuration</h2>

          <fieldset className="sidebar-fieldset">
            <legend className="hint-text">Engines</legend>
            <div className="checkbox-row">
              <input
                id="drawer-eng-paddle"
                type="checkbox"
                checked={usePaddle}
                disabled={!paddleAvailable}
                onChange={(e) => onUsePaddleChange(e.target.checked)}
              />
              <label htmlFor="drawer-eng-paddle">
                PaddleOCR PP-OCRv5{" "}
                <span className="hint-text">
                  {!paddleAvailable
                    ? `(${capabilities?.engines.paddle_ppocrv5_te?.reason ?? "Unavailable"})`
                    : "(~90s/p CPU · high accuracy)"}
                </span>
              </label>
            </div>
            <div className="checkbox-row">
              <input
                id="drawer-eng-tess"
                type="checkbox"
                checked={useTesseract}
                disabled={!tesseractAvailable}
                onChange={(e) => onUseTesseractChange(e.target.checked)}
              />
              <label htmlFor="drawer-eng-tess">
                Tesseract 5 Telugu{" "}
                <span className="hint-text">
                  {!tesseractAvailable
                    ? `(${capabilities?.engines.tesseract_tel_best?.reason ?? "Unavailable"})`
                    : "(~0.4s/p CPU · fast draft)"}
                </span>
              </label>
            </div>
          </fieldset>

          <fieldset className="sidebar-fieldset">
            <legend className="hint-text">Page Range</legend>
            <div className="range-grid">
              <label className="hint-text" htmlFor="drawer-ocr-start">
                Start page
                <input
                  id="drawer-ocr-start"
                  type="number"
                  className="compact-number-input"
                  min={1}
                  max={book.page_count}
                  value={ocrStartPage}
                  onChange={(e) => onStartPageChange(e.target.value)}
                />
              </label>
              <label className="hint-text" htmlFor="drawer-ocr-end">
                End page
                <input
                  id="drawer-ocr-end"
                  type="number"
                  className="compact-number-input"
                  min={1}
                  max={book.page_count}
                  value={ocrEndPage}
                  placeholder={String(book.page_count)}
                  onChange={(e) => onEndPageChange(e.target.value)}
                />
              </label>
            </div>
            <div className="badge-row" style={{ marginTop: "0.45rem" }}>
              {coverage.isPartialCoverage && (
                <button
                  type="button"
                  className="btn-compact"
                  onClick={() => {
                    onStartPageChange(String(coverage.nextStartPage));
                    onEndPageChange(String(coverage.nextEndPage));
                  }}
                >
                  Remaining ({coverage.nextStartPage}–{coverage.nextEndPage})
                </button>
              )}
              <button
                type="button"
                className="btn-compact"
                onClick={() => {
                  onStartPageChange("1");
                  onEndPageChange(String(Math.min(5, book.page_count)));
                }}
              >
                Pages 1–5
              </button>
              <button
                type="button"
                className="btn-compact"
                onClick={() => {
                  onStartPageChange("1");
                  onEndPageChange(String(book.page_count));
                }}
              >
                All ({book.page_count})
              </button>
            </div>
          </fieldset>

          <details className="drawer-advanced">
            <summary className="hint-text">Advanced Preprocessing &amp; DPI</summary>
            <div className="drawer-advanced-body">
              <label className="form-field">
                <span>Scan Preprocessing</span>
                <select
                  aria-label="OCR preprocessing profile"
                  value={ocrPreprocessing}
                  onChange={(e) =>
                    onPreprocessingChange(
                      e.target.value as "none" | "deskew" | "contrast_clahe" | "textured_bold",
                    )
                  }
                >
                  <option value="none">None (Raw 300 DPI scan)</option>
                  <option value="deskew">Auto-Deskew + Contrast</option>
                  <option value="contrast_clahe">CLAHE Adaptive Contrast + Denoise</option>
                  <option value="textured_bold">Textured / Bold Headings (Deskew + Solidify Ink)</option>
                </select>
              </label>
              <label className="form-field">
                <span>Render Resolution</span>
                <select
                  aria-label="OCR render DPI"
                  value={ocrRenderDpi}
                  onChange={(e) => onRenderDpiChange(Number(e.target.value))}
                >
                  <option value={300}>300 DPI (Standard)</option>
                  <option value={400}>400 DPI (Fine / Faded print)</option>
                </select>
              </label>
              <div className="checkbox-row">
                <input
                  id="drawer-force-rerun"
                  type="checkbox"
                  checked={ocrForceRerun}
                  onChange={(e) => onForceRerunChange(e.target.checked)}
                />
                <label htmlFor="drawer-force-rerun">Force fresh OCR re-run</label>
              </div>
              <div className="checkbox-row">
                <input
                  id="drawer-include-digital"
                  type="checkbox"
                  checked={ocrIncludeDigital}
                  onChange={(e) => onIncludeDigitalChange(e.target.checked)}
                />
                <label htmlFor="drawer-include-digital">Include digital-text pages in visual OCR</label>
              </div>
            </div>
          </details>

          <button
            type="button"
            className="primary drawer-submit-btn"
            disabled={isOcrRunning || (!usePaddle && !useTesseract)}
            onClick={async () => {
              await onStartOcr();
              onClose();
            }}
          >
            {isOcrRunning ? "OCR In Progress…" : "Run Selected OCR"}
          </button>
        </section>

        {completedRuns.length > 0 && (
          <section className="drawer-section" aria-label="Completed OCR runs">
            <h2 className="drawer-section-title">Completed Runs ({completedRuns.length})</h2>
            <ul className="drawer-run-list">
              {completedRuns.map((run) => (
                <li key={run.ocr_run_id} className="drawer-run-item">
                  <div>
                    <strong>{formatEngineLabel(run.engine)}</strong>
                    <div className="hint-text">
                      {run.progress_current ?? book.scanned_pages_count} pages ·{" "}
                      <span title={run.model_id ?? undefined}>{run.model_id ?? "default"}</span>
                    </div>
                  </div>
                  <span className="badge ok">✓ Ready</span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </dialog>
  );
}
