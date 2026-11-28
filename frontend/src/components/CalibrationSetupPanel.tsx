import { useEffect, useId, useState, type FormEvent } from "react";
import { resolveAppUrl } from "../api/client";
import type { BookSummary } from "../types/api";

interface CalibrationSetupPanelProps {
  book: BookSummary;
  initialStartPage?: number;
  initialCalibrationPages?: number;
  initialEndPage?: number;
  disabled?: boolean;
  compact?: boolean;
  onStartCalibration: (config: {
    startPage: number;
    calibrationPageCount: number;
    endPage: number;
  }) => Promise<void>;
  onSkipCalibrationFullBook?: () => Promise<void>;
  onPreviewPageJump?: (pageNumber: number) => void;
}

const CALIBRATION_PRESETS = [5, 6, 7, 8, 9, 10] as const;

export function CalibrationSetupPanel({
  book,
  initialStartPage,
  initialCalibrationPages,
  initialEndPage,
  disabled = false,
  compact = false,
  onStartCalibration,
  onSkipCalibrationFullBook,
  onPreviewPageJump,
}: CalibrationSetupPanelProps) {
  const headingId = useId();
  const startId = useId();
  const startHintId = useId();
  const startErrorId = useId();
  const countId = useId();
  const countErrorId = useId();
  const endId = useId();
  const endErrorId = useId();

  const totalPages = Math.max(1, book.page_count);
  const defaultStart = Math.max(1, Math.min(totalPages, initialStartPage ?? book.calibration_start_page ?? 1));
  const defaultCount = Math.max(
    1,
    Math.min(
      totalPages - defaultStart + 1,
      initialCalibrationPages ?? book.calibration_page_count ?? Math.min(5, totalPages),
    ),
  );
  const defaultEnd = Math.max(
    defaultStart + defaultCount - 1,
    Math.min(totalPages, initialEndPage ?? book.calibration_end_page ?? totalPages),
  );

  const [startPageStr, setStartPageStr] = useState(String(defaultStart));
  const [calCountStr, setCalCountStr] = useState(String(defaultCount));
  const [endPageStr, setEndPageStr] = useState(String(defaultEnd));
  const [touchedStart, setTouchedStart] = useState(false);
  const [touchedCount, setTouchedCount] = useState(false);
  const [touchedEnd, setTouchedEnd] = useState(false);
  const [submitAttempted, setSubmitAttempted] = useState(false);
  const [previewLoaded, setPreviewLoaded] = useState(false);
  const [previewError, setPreviewError] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // Reset form defaults cleanly when switching books.
  useEffect(() => {
    const nextStart = Math.max(1, Math.min(totalPages, initialStartPage ?? book.calibration_start_page ?? 1));
    const nextCount = Math.max(
      1,
      Math.min(
        totalPages - nextStart + 1,
        initialCalibrationPages ?? book.calibration_page_count ?? Math.min(5, totalPages),
      ),
    );
    const nextEnd = Math.max(
      nextStart + nextCount - 1,
      Math.min(totalPages, initialEndPage ?? book.calibration_end_page ?? totalPages),
    );
    setStartPageStr(String(nextStart));
    setCalCountStr(String(nextCount));
    setEndPageStr(String(nextEnd));
    setTouchedStart(false);
    setTouchedCount(false);
    setTouchedEnd(false);
    setSubmitAttempted(false);
  }, [
    book.book_id,
    book.calibration_start_page,
    book.calibration_page_count,
    book.calibration_end_page,
    initialStartPage,
    initialCalibrationPages,
    initialEndPage,
    totalPages,
  ]);

  const parsedStart = Number(startPageStr.trim());
  const parsedCount = Number(calCountStr.trim());
  const parsedEnd = endPageStr.trim() === "" ? totalPages : Number(endPageStr.trim());

  const startValid = Number.isInteger(parsedStart) && parsedStart >= 1 && parsedStart <= totalPages;
  const maxCalFromStart = startValid ? totalPages - parsedStart + 1 : totalPages;
  const countValid =
    Number.isInteger(parsedCount) && parsedCount >= 1 && parsedCount <= maxCalFromStart;
  const calRangeEnd = startValid && countValid ? parsedStart + parsedCount - 1 : null;
  const endValid =
    Number.isInteger(parsedEnd) &&
    parsedEnd <= totalPages &&
    (calRangeEnd !== null ? parsedEnd >= calRangeEnd : parsedEnd >= 1);

  const startErrorMsg = !startValid
    ? `Enter a PDF starting page between 1 and ${totalPages}.`
    : null;
  const countErrorMsg = !countValid
    ? `Enter between 1 and ${maxCalFromStart} calibration page(s) from PDF page ${startValid ? parsedStart : 1}.`
    : null;
  const endErrorMsg = !endValid
    ? `Ending PDF page must be between ${calRangeEnd ?? 1} and ${totalPages}.`
    : null;

  const showStartError = Boolean(startErrorMsg && (touchedStart || submitAttempted));
  const showCountError = Boolean(countErrorMsg && (touchedCount || submitAttempted));
  const showEndError = Boolean(endErrorMsg && (touchedEnd || submitAttempted));

  const previewPage = startValid ? parsedStart : 1;
  const previewUrl = resolveAppUrl(`/api/v1/books/${book.book_id}/pages/${previewPage}/image`);

  useEffect(() => {
    setPreviewLoaded(false);
    setPreviewError(false);
  }, [previewUrl]);

  const skippedFrontCount = startValid ? Math.max(0, parsedStart - 1) : 0;
  const remainingStart = calRangeEnd !== null && endValid && calRangeEnd < parsedEnd ? calRangeEnd + 1 : null;
  const remainingCount =
    remainingStart !== null && endValid ? Math.max(0, parsedEnd - remainingStart + 1) : 0;

  // Percentage widths for visual PDF range indicator bar.
  const skippedPct = (skippedFrontCount / totalPages) * 100;
  const calPct = calRangeEnd !== null && startValid ? ((calRangeEnd - parsedStart + 1) / totalPages) * 100 : 0;
  const remPct = (remainingCount / totalPages) * 100;

  function stepStartPage(delta: number) {
    const base = startValid ? parsedStart : 1;
    const next = Math.max(1, Math.min(totalPages, base + delta));
    setStartPageStr(String(next));
    setTouchedStart(true);
    const maxFromNext = totalPages - next + 1;
    if (Number.isInteger(parsedCount) && parsedCount > maxFromNext) {
      setCalCountStr(String(maxFromNext));
    }
    if (onPreviewPageJump) {
      onPreviewPageJump(next);
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitAttempted(true);
    if (!startValid || !countValid || !endValid) {
      return;
    }
    setSubmitting(true);
    try {
      await onStartCalibration({
        startPage: parsedStart,
        calibrationPageCount: parsedCount,
        endPage: parsedEnd,
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section
      className={`calibration-panel${compact ? " compact" : ""}`}
      aria-labelledby={headingId}
    >
      <div className="calibration-panel-head">
        <div>
          <div className="badge-row" style={{ marginBottom: "0.2rem" }}>
            <span className="pill-tag info">🎯 Step 1 · OCR Calibration</span>
            <h2 id={headingId} className="calibration-title">
              OCR Calibration Settings
            </h2>
            <span className="badge">Total PDF pages: {totalPages}</span>
          </div>
          <p className="hint-text" style={{ margin: 0 }}>
            Process a small sample (5–10 pages) first, fix recurring Telugu OCR mistakes once, and
            automatically apply your learned corrections to the remaining pages.
          </p>
        </div>
      </div>

      <form className="calibration-grid" onSubmit={handleSubmit} noValidate>
        <div className="calibration-controls">
          {/* PDF Starting Page */}
          <div className="form-field">
            <label htmlFor={startId}>PDF Starting Page</label>
            <span id={startHintId} className="hint-text calibration-helper">
              Select the PDF page where the actual book text begins. This may differ from the
              printed page number.
            </span>
            <div className="calibration-stepper-row">
              <button
                type="button"
                className="btn-compact"
                disabled={disabled || submitting || previewPage <= 1}
                aria-label="Previous starting PDF page"
                onClick={() => stepStartPage(-1)}
              >
                ← Prev
              </button>
              <input
                id={startId}
                type="number"
                className="compact-number-input"
                min={1}
                max={totalPages}
                required
                value={startPageStr}
                aria-invalid={showStartError ? "true" : "false"}
                aria-describedby={showStartError ? `${startHintId} ${startErrorId}` : startHintId}
                onChange={(e) => setStartPageStr(e.target.value)}
                onBlur={() => setTouchedStart(true)}
              />
              <button
                type="button"
                className="btn-compact"
                disabled={disabled || submitting || previewPage >= totalPages}
                aria-label="Next starting PDF page"
                onClick={() => stepStartPage(1)}
              >
                Next →
              </button>
              <span className="hint-text">of {totalPages} PDF pages</span>
            </div>
            {showStartError && (
              <div id={startErrorId} className="field-error-msg" role="alert">
                <span role="img" aria-label="Error">
                  ❌
                </span>{" "}
                {startErrorMsg}
              </div>
            )}
          </div>

          {/* Calibration Pages Count */}
          <div className="form-field">
            <label htmlFor={countId}>Calibration Pages</label>
            <div className="calibration-preset-pills" role="group" aria-label="Calibration page count presets">
              {CALIBRATION_PRESETS.map((n) => {
                const exceeds = n > maxCalFromStart;
                const active = parsedCount === n;
                return (
                  <button
                    key={n}
                    type="button"
                    className={`btn-compact cal-count-pill${active ? " active" : ""}`}
                    aria-pressed={active}
                    disabled={disabled || submitting || exceeds}
                    onClick={() => {
                      setCalCountStr(String(n));
                      setTouchedCount(true);
                    }}
                  >
                    {n}
                  </button>
                );
              })}
              <input
                id={countId}
                type="number"
                className="compact-number-input"
                aria-label="Custom calibration page count"
                min={1}
                max={maxCalFromStart}
                required
                value={calCountStr}
                aria-invalid={showCountError ? "true" : "false"}
                aria-describedby={showCountError ? countErrorId : undefined}
                onChange={(e) => setCalCountStr(e.target.value)}
                onBlur={() => setTouchedCount(true)}
              />
              <span className="hint-text">pages</span>
            </div>
            {showCountError && (
              <div id={countErrorId} className="field-error-msg" role="alert">
                <span role="img" aria-label="Error">
                  ❌
                </span>{" "}
                {countErrorMsg}
              </div>
            )}
          </div>

          {/* Optional Book Ending PDF Page */}
          <div className="form-field">
            <label htmlFor={endId}>Ending PDF Page (optional)</label>
            <div className="calibration-stepper-row">
              <input
                id={endId}
                type="number"
                className="compact-number-input"
                min={calRangeEnd ?? 1}
                max={totalPages}
                value={endPageStr}
                placeholder={String(totalPages)}
                aria-invalid={showEndError ? "true" : "false"}
                aria-describedby={showEndError ? endErrorId : undefined}
                onChange={(e) => setEndPageStr(e.target.value)}
                onBlur={() => setTouchedEnd(true)}
              />
              <span className="hint-text">
                Defaults to last PDF page ({totalPages})
              </span>
            </div>
            {showEndError && (
              <div id={endErrorId} className="field-error-msg" role="alert">
                <span role="img" aria-label="Error">
                  ❌
                </span>{" "}
                {endErrorMsg}
              </div>
            )}
          </div>

          {/* Visual Range Summary */}
          <div className="calibration-range-summary" aria-live="polite">
            <div className="calibration-range-bar" aria-hidden="true">
              {skippedPct > 0 && (
                <div
                  className="cal-bar-seg skipped"
                  style={{ width: `${Math.max(2, skippedPct)}%` }}
                  title={`Skipped front matter: PDF pages 1–${parsedStart - 1}`}
                />
              )}
              {calPct > 0 && (
                <div
                  className="cal-bar-seg calibration"
                  style={{ width: `${Math.max(4, calPct)}%` }}
                  title={`Calibration batch: PDF pages ${parsedStart}–${calRangeEnd}`}
                />
              )}
              {remPct > 0 && (
                <div
                  className="cal-bar-seg remaining"
                  style={{ width: `${Math.max(2, remPct)}%` }}
                  title={`Remaining pages: PDF pages ${remainingStart}–${parsedEnd}`}
                />
              )}
            </div>
            <div className="badge-row">
              {calRangeEnd !== null && startValid && (
                <span className="badge ok">
                  Pages selected for calibration: PDF {parsedStart}–{calRangeEnd} ({parsedCount}{" "}
                  {parsedCount === 1 ? "page" : "pages"})
                </span>
              )}
              {remainingStart !== null && remainingCount > 0 ? (
                <span className="badge">
                  Remaining after calibration: PDF {remainingStart}–{parsedEnd} ({remainingCount}{" "}
                  pages)
                </span>
              ) : (
                <span className="badge">0 remaining pages after calibration</span>
              )}
              {skippedFrontCount > 0 && (
                <span className="hint-text">
                  PDF pages 1–{parsedStart - 1} untouched (front matter)
                </span>
              )}
            </div>
          </div>

          <div className="badge-row" style={{ marginTop: "0.35rem" }}>
            <button
              type="submit"
              className="primary"
              disabled={disabled || submitting || !startValid || !countValid || !endValid}
            >
              {submitting
                ? "Starting Calibration…"
                : calRangeEnd !== null && startValid
                  ? `▶ Start Calibration OCR (PDF Pages ${parsedStart}–${calRangeEnd})`
                  : "▶ Start Calibration OCR"}
            </button>
            {onSkipCalibrationFullBook && (
              <button
                type="button"
                disabled={disabled || submitting}
                onClick={() => void onSkipCalibrationFullBook()}
              >
                Skip Calibration · Run Full Book
              </button>
            )}
          </div>
        </div>

        {/* Live Starting PDF Page Thumbnail Preview */}
        <aside className="calibration-preview-card" aria-label="PDF starting page preview">
          <div className="calibration-preview-head">
            <strong>PDF Page {previewPage} Preview</strong>
            <span className="hint-text">Verify Telugu body text starts here</span>
          </div>
          <div className="calibration-preview-frame">
            {!previewError ? (
              <img
                key={previewUrl}
                src={previewUrl}
                alt={`Preview of PDF page ${previewPage} of ${book.title}`}
                className={`calibration-preview-img${previewLoaded ? " loaded" : ""}`}
                onLoad={() => setPreviewLoaded(true)}
                onError={() => setPreviewError(true)}
              />
            ) : (
              <div className="calibration-preview-fallback hint-text">
                Preview unavailable for PDF page {previewPage}.
              </div>
            )}
          </div>
        </aside>
      </form>
    </section>
  );
}
