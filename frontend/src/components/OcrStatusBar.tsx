import { useEffect, useMemo, useState } from "react";
import type {
  BookCalibrationStatus,
  BookOCRRunSummary,
  BookSummary,
  OCRRunStatus,
  PageSummary,
} from "../types/api";
import {
  buildRunTelemetry,
  computeBookOcrCoverage,
  formatDuration,
  formatEngineLabel,
} from "../utils/formatters";
import { CalibrationSetupPanel } from "./CalibrationSetupPanel";

export function mergeBookRunsWithLiveStatuses(
  runs: BookOCRRunSummary[],
  liveStatuses: Record<string, OCRRunStatus>,
): BookOCRRunSummary[] {
  const byId = new Map<string, BookOCRRunSummary>();
  for (const run of runs) {
    const live = liveStatuses[run.ocr_run_id];
    byId.set(
      run.ocr_run_id,
      live
        ? {
            ...run,
            status: live.status,
            engine: live.engine ?? run.engine,
            model_id: live.model_id ?? run.model_id,
            progress_current: live.progress_current,
            progress_total: live.progress_total,
            started_at: live.started_at,
            completed_at: live.completed_at,
            error_summary: live.error_summary,
            config: live.config,
          }
        : run,
    );
  }
  for (const live of Object.values(liveStatuses)) {
    if (!byId.has(live.ocr_run_id)) {
      byId.set(live.ocr_run_id, {
        ocr_run_id: live.ocr_run_id,
        engine: live.engine,
        model_id: live.model_id,
        status: live.status,
        progress_current: live.progress_current,
        progress_total: live.progress_total,
        started_at: live.started_at,
        completed_at: live.completed_at,
        error_summary: live.error_summary,
        config: live.config,
        created_at: live.created_at,
      });
    }
  }
  return Array.from(byId.values());
}

interface HeaderOcrStatusPillProps {
  book: BookSummary | null;
  runs: BookOCRRunSummary[];
}

export function HeaderOcrStatusPill({ book, runs }: HeaderOcrStatusPillProps) {
  if (!book) {
    return (
      <div className="header-status-pill neutral" role="status" aria-live="polite">
        <span className="status-dot neutral" aria-hidden="true" />
        <span>No Book Loaded</span>
      </div>
    );
  }

  const running = runs.find((r) => r.status === "running");
  const queued = runs.find((r) => r.status === "queued");
  const partialOrFailed = runs.filter((r) => r.status === "partial" || r.status === "failed");
  const needsScanOcr = book.scanned_pages_count + book.mixed_pages_count > 0;
  const coverage = computeBookOcrCoverage(book, runs);

  if (running) {
    const telemetry = buildRunTelemetry(running, book, Date.now());
    return (
      <div className="header-status-pill active" role="status" aria-live="polite">
        <span className="status-dot pulse" aria-hidden="true" />
        <span>
          OCR In Progress ·{" "}
          {telemetry.total > 0
            ? `${telemetry.completed}/${telemetry.total} (${telemetry.percent}%)`
            : formatEngineLabel(running.engine)}
        </span>
      </div>
    );
  }

  if (queued) {
    return (
      <div className="header-status-pill active" role="status" aria-live="polite">
        <span className="status-dot pulse" aria-hidden="true" />
        <span>OCR Queued · {formatEngineLabel(queued.engine)}</span>
      </div>
    );
  }

  if (!needsScanOcr || coverage.isFullyCovered) {
    return (
      <div className="header-status-pill ready" role="status" aria-live="polite">
        <span aria-hidden="true">✓</span>
        <span>{needsScanOcr ? "OCR Ready" : "Digital Text Ready"}</span>
      </div>
    );
  }

  if (coverage.isPartialCoverage) {
    return (
      <div className="header-status-pill warn" role="status" aria-live="polite">
        <span aria-hidden="true">⏳</span>
        <span>
          OCR {coverage.coveredPagesCount}/{coverage.totalPages} Pages · Continue
        </span>
      </div>
    );
  }

  if (partialOrFailed.length > 0) {
    return (
      <div className="header-status-pill warn" role="status" aria-live="polite">
        <span aria-hidden="true">⚠</span>
        <span>Partial OCR · Resume Available</span>
      </div>
    );
  }

  return (
    <div className="header-status-pill warn" role="status" aria-live="polite">
      <span aria-hidden="true">⏳</span>
      <span>Needs OCR</span>
    </div>
  );
}

interface OcrProgressStripProps {
  book: BookSummary;
  runs: BookOCRRunSummary[];
  pages: PageSummary[];
  calibration?: BookCalibrationStatus | null;
  activeView: "review" | "memory" | "export";
  /** When true, hide the static green Ready banner once the entire book is OCR'd to maximize workspace height. */
  hideWhenReady?: boolean;
  onQuickStartSample: () => Promise<void>;
  onQuickStartFull: () => Promise<void>;
  onStartCalibration?: (config: {
    startPage: number;
    calibrationPageCount: number;
    endPage: number;
  }) => Promise<void>;
  onProcessRemainingWithCalibration?: (quickTesseract?: boolean) => Promise<void>;
  onContinueRemaining?: (
    startPage: number,
    endPage: number,
    quickTesseract?: boolean,
  ) => Promise<void>;
  onPreviewPageJump?: (pageNumber: number) => void;
  onOpenOcrDrawer?: () => void;
  onResumeRun: (runId: string) => Promise<void>;
  onCancelRun?: (runId: string) => Promise<void>;
  onGoToExport: () => void;
  onGoToReview: () => void;
}

export function OcrProgressStrip({
  book,
  runs,
  pages,
  calibration,
  activeView,
  hideWhenReady = false,
  onQuickStartSample,
  onQuickStartFull,
  onStartCalibration,
  onProcessRemainingWithCalibration,
  onContinueRemaining,
  onPreviewPageJump,
  onOpenOcrDrawer,
  onResumeRun,
  onCancelRun,
  onGoToExport,
  onGoToReview,
}: OcrProgressStripProps) {
  const activeRuns = runs.filter((r) => r.status === "running" || r.status === "queued");
  const isLive = activeRuns.length > 0;
  const [nowMs, setNowMs] = useState(() => Date.now());

  useEffect(() => {
    if (!isLive) return;
    setNowMs(Date.now());
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [isLive]);

  const completedRuns = runs.filter((r) => r.status === "completed");
  const partialOrFailedRuns = runs.filter((r) => r.status === "partial" || r.status === "failed");
  const needsScanOcr = book.scanned_pages_count + book.mixed_pages_count > 0;
  const approvedCount = pages.filter((p) => p.review_status === "approved").length;

  const primaryActive = useMemo(
    () => activeRuns.find((r) => r.status === "running") ?? activeRuns[0] ?? null,
    [activeRuns],
  );

  if (primaryActive) {
    const telemetry = buildRunTelemetry(primaryActive, book, nowMs);
    const isDeterminate = telemetry.status === "running" && telemetry.total > 0;
    const queuedExtras = activeRuns.filter((r) => r.ocr_run_id !== telemetry.ocrRunId);

    return (
      <section className="ocr-strip live" aria-label="Live OCR job progress">
        <div className="ocr-strip-top">
          <div className="badge-row">
            <span className="pill-tag info">
              <span className="status-dot pulse" aria-hidden="true" />
              {telemetry.status === "running" ? "OCR In Progress" : "OCR Queued"}
            </span>
            <strong>{telemetry.engineLabel}</strong>
            {telemetry.pageRangeLabel && (
              <span className="badge">{telemetry.pageRangeLabel}</span>
            )}
          </div>

          <div className="ocr-metrics-row" role="status" aria-live="polite">
            <span className="metric-chip">
              <strong>{telemetry.completed}</strong> completed
            </span>
            <span className="metric-chip">
              <strong>{telemetry.pending}</strong> pending
            </span>
            <span className="metric-chip">
              <strong>{telemetry.percent}%</strong> ({telemetry.completed}/{telemetry.total})
            </span>
            {telemetry.elapsedSec !== null && (
              <span className="metric-chip">
                Elapsed <strong>{formatDuration(telemetry.elapsedSec)}</strong>
              </span>
            )}
            <span className="metric-chip">
              {telemetry.etaSec !== null && telemetry.secPerPage !== null ? (
                <>
                  Pace <strong>~{telemetry.secPerPage.toFixed(1)}s/p</strong> · Est. left{" "}
                  <strong>~{formatDuration(telemetry.etaSec)}</strong>
                </>
              ) : telemetry.status === "queued" ? (
                "Waiting for worker..."
              ) : (
                "Estimating pace after page 1 finishes..."
              )}
            </span>
            {onCancelRun && (
              <button
                type="button"
                className="danger btn-compact"
                onClick={() => void onCancelRun(telemetry.ocrRunId)}
              >
                Cancel OCR
              </button>
            )}
          </div>
        </div>

        <progress
          className="ocr-progress-bar"
          aria-label={`OCR progress for ${telemetry.engineLabel}`}
          max={isDeterminate ? telemetry.total : undefined}
          value={isDeterminate ? telemetry.completed : undefined}
        />

        {queuedExtras.length > 0 && (
          <div className="badge-row" style={{ marginTop: "0.45rem" }}>
            <span className="hint-text">Queued next:</span>
            {queuedExtras.map((extra) => (
              <span key={extra.ocr_run_id} className="badge">
                ⏳ {formatEngineLabel(extra.engine)} ({extra.progress_total || telemetry.total} pages)
              </span>
            ))}
          </div>
        )}
      </section>
    );
  }

  if (partialOrFailedRuns.length > 0 && completedRuns.length === 0) {
    const latestIncomplete = partialOrFailedRuns[0];
    const telemetry = buildRunTelemetry(latestIncomplete, book, nowMs);
    return (
      <section className="ocr-strip warn" aria-label="Paused OCR run status">
        <div className="ocr-strip-top">
          <div className="badge-row">
            <span className="pill-tag warn">⚠ {latestIncomplete.status === "partial" ? "Partial OCR" : "OCR Stopped"}</span>
            <strong>{telemetry.engineLabel}</strong>
            <span className="hint-text">
              {telemetry.completed}/{telemetry.total} pages saved ({telemetry.pending} pending)
            </span>
          </div>
          <div className="badge-row">
            <button
              type="button"
              className="primary"
              onClick={() => void onResumeRun(latestIncomplete.ocr_run_id)}
            >
              Resume {telemetry.engineLabel}
            </button>
          </div>
        </div>
        {telemetry.total > 0 && (
          <progress
            className="ocr-progress-bar warn"
            aria-label={`Partial OCR progress for ${telemetry.engineLabel}`}
            max={telemetry.total}
            value={telemetry.completed}
          />
        )}
      </section>
    );
  }

  if (completedRuns.length === 0 && needsScanOcr) {
    if (onStartCalibration && activeView === "review") {
      return (
        <CalibrationSetupPanel
          book={book}
          initialStartPage={calibration?.calibration_start_page ?? book.calibration_start_page ?? 1}
          initialCalibrationPages={
            calibration?.calibration_page_count ?? book.calibration_page_count ?? Math.min(5, book.page_count)
          }
          initialEndPage={calibration?.book_end_page ?? book.calibration_end_page ?? book.page_count}
          onStartCalibration={onStartCalibration}
          onSkipCalibrationFullBook={onQuickStartFull}
          onPreviewPageJump={onPreviewPageJump}
        />
      );
    }
    return (
      <section className="ocr-strip warn" aria-label="Book requires OCR">
        <div className="ocr-strip-top">
          <div>
            <div className="badge-row" style={{ marginBottom: "0.2rem" }}>
              <span className="pill-tag warn">⏳ OCR Required</span>
              <strong lang="te">{book.title}</strong>
              <span className="hint-text">
                {book.scanned_pages_count + book.mixed_pages_count} scanned pages · 0 OCR runs yet
              </span>
            </div>
            <p className="hint-text" style={{ margin: 0 }}>
              Run a quick calibration batch (5–10 pages) first or process with selected engines.
            </p>
          </div>
          <div className="badge-row">
            <button type="button" className="primary" onClick={() => void onQuickStartSample()}>
              Test Pages 1–5
            </button>
            <button type="button" onClick={() => void onQuickStartFull()}>
              Run Full Book OCR
            </button>
          </div>
        </div>
      </section>
    );
  }

  // Calibration review / completed banner before processing remaining pages
  const isCalibrationStage =
    calibration &&
    calibration.calibration_start_page !== null &&
    calibration.calibration_range_end !== null &&
    calibration.remaining_pages_count > 0 &&
    (calibration.processing_state === "calibration_review" ||
      calibration.processing_state === "calibration_completed");

  if (isCalibrationStage && calibration && needsScanOcr) {
    const calRange = `${calibration.calibration_start_page}–${calibration.calibration_range_end}`;
    const remRange = `${calibration.remaining_start_page}–${calibration.remaining_end_page}`;
    const calTotal = calibration.calibration_page_count ?? 0;
    const calApproved = calibration.calibration_pages_approved;
    const learnedRules = calibration.learned_word_rules_count;
    const calReady = calTotal > 0 && calApproved >= calTotal;
    return (
      <section className="ocr-strip warn" aria-label="Calibration review and remaining OCR">
        <div className="ocr-strip-top">
          <div>
            <div className="badge-row" style={{ marginBottom: "0.18rem" }}>
              <span className="pill-tag info">
                🎯 Calibration PDF {calRange} ({calApproved}/{calTotal} approved)
              </span>
              <span className="metric-chip">
                <strong>{learnedRules}</strong> word rule{learnedRules === 1 ? "" : "s"} learned
              </span>
              {calibration.learned_char_patterns.length > 0 && (
                <span className="metric-chip">
                  <strong>{calibration.learned_char_patterns.length}</strong> char pattern
                  {calibration.learned_char_patterns.length === 1 ? "" : "s"}
                </span>
              )}
              <span className="metric-chip">
                <strong>{calibration.remaining_pages_count}</strong> remaining (PDF {remRange})
              </span>
            </div>
            <p className="hint-text" style={{ margin: 0 }}>
              {calReady
                ? `Calibration complete! Process remaining PDF pages ${remRange} — your ${learnedRules} learned word correction(s) will be applied safely without overwriting raw OCR.`
                : `Review & approve calibration PDF pages ${calRange} so the system learns recurring Telugu OCR mistakes before processing PDF pages ${remRange}.`}
              {calibration.skipped_front_pages_count > 0
                ? ` (Front-matter PDF pages 1–${calibration.skipped_front_pages_count} remain untouched.)`
                : ""}
            </p>
          </div>
          <div className="badge-row">
            {onProcessRemainingWithCalibration ? (
              <>
                <button
                  type="button"
                  className="primary btn-compact"
                  onClick={() => void onProcessRemainingWithCalibration(false)}
                >
                  ✨ Apply Calibration &amp; Process Remaining (PDF {remRange})
                </button>
                <button
                  type="button"
                  className="btn-compact"
                  title="Run fast Tesseract 5 Telugu draft with learned calibration corrections"
                  onClick={() => void onProcessRemainingWithCalibration(true)}
                >
                  ⚡ Fast Draft ({remRange})
                </button>
              </>
            ) : (
              onContinueRemaining &&
              calibration.remaining_start_page &&
              calibration.remaining_end_page && (
                <button
                  type="button"
                  className="primary btn-compact"
                  onClick={() =>
                    void onContinueRemaining(
                      calibration.remaining_start_page!,
                      calibration.remaining_end_page!,
                      false,
                    )
                  }
                >
                  ▶ Continue Remaining (PDF {remRange})
                </button>
              )
            )}
            {onOpenOcrDrawer && (
              <button type="button" className="btn-compact" onClick={onOpenOcrDrawer}>
                OCR Options…
              </button>
            )}
          </div>
        </div>
      </section>
    );
  }

  // Partial-book coverage (e.g., user tested Pages 1–5 of 406 and is ready to continue Pages 6–406)
  const coverage = computeBookOcrCoverage(book, runs);
  if (coverage.isPartialCoverage && needsScanOcr) {
    const sampleReviewed = approvedCount >= coverage.coveredPagesCount;
    const rangeStr = `${coverage.nextStartPage}–${coverage.nextEndPage}`;
    return (
      <section className="ocr-strip warn" aria-label="Continue OCR on remaining book pages">
        <div className="ocr-strip-top">
          <div>
            <div className="badge-row" style={{ marginBottom: "0.18rem" }}>
              <span className="pill-tag info">
                ✓ Pages {coverage.coveredRangeLabel} OCR&apos;d ({coverage.coveredPagesCount}/
                {coverage.totalPages})
              </span>
              <span className="metric-chip">
                <strong>{coverage.remainingPagesCount}</strong> remaining
              </span>
              {approvedCount > 0 && (
                <span className="metric-chip">
                  <strong>{approvedCount}</strong> approved
                </span>
              )}
            </div>
            <p className="hint-text" style={{ margin: 0 }}>
              {sampleReviewed
                ? `Test pages approved! Continue OCR on Pages ${rangeStr} — your approved edits on Pages ${coverage.coveredRangeLabel} are preserved for review & export.`
                : `Only Pages ${coverage.coveredRangeLabel} have been OCR'd so far. Continue OCR on Pages ${rangeStr} whenever you're ready — your edits on Pages ${coverage.coveredRangeLabel} are preserved.`}
            </p>
          </div>
          <div className="badge-row">
            {onContinueRemaining ? (
              <>
                <button
                  type="button"
                  className="primary btn-compact"
                  onClick={() =>
                    void onContinueRemaining(coverage.nextStartPage, coverage.nextEndPage, false)
                  }
                >
                  ▶ Continue Remaining (Pages {rangeStr})
                </button>
                <button
                  type="button"
                  className="btn-compact"
                  title="Run fast Tesseract 5 Telugu draft (~0.4s/page) on remaining pages"
                  onClick={() =>
                    void onContinueRemaining(coverage.nextStartPage, coverage.nextEndPage, true)
                  }
                >
                  ⚡ Fast Draft ({rangeStr})
                </button>
              </>
            ) : (
              <button type="button" className="primary btn-compact" onClick={() => void onQuickStartFull()}>
                Run Full Book OCR
              </button>
            )}
            {onOpenOcrDrawer && (
              <button type="button" className="btn-compact" onClick={onOpenOcrDrawer}>
                OCR Options…
              </button>
            )}
          </div>
        </div>
      </section>
    );
  }

  // Ready state (full book OCR completed or digital-only book)
  if (hideWhenReady) {
    return null;
  }
  const readyEngines = Array.from(
    new Set(completedRuns.map((r) => formatEngineLabel(r.engine))),
  ).join(" + ");
  const resumable = partialOrFailedRuns.filter(
    (r) => !completedRuns.some((c) => c.engine === r.engine),
  );

  return (
    <section className="ocr-strip ready" aria-label="Book OCR readiness">
      <div className="ocr-strip-top">
        <div className="badge-row">
          <span className="pill-tag ready">✓ Ready</span>
          <strong lang="te">{book.title}</strong>
          <span className="metric-chip">
            {needsScanOcr ? `${readyEngines}` : "Born-Digital PDF"}
          </span>
          <span className="metric-chip">
            <strong>{approvedCount}</strong>/{book.page_count} pages approved
          </span>
        </div>

        <div className="badge-row">
          {resumable.map((r) => (
            <button
              key={r.ocr_run_id}
              type="button"
              onClick={() => void onResumeRun(r.ocr_run_id)}
            >
              Resume {formatEngineLabel(r.engine)} ({r.progress_current ?? 0}/{r.progress_total ?? "?"})
            </button>
          ))}
          {activeView !== "export" ? (
            <button type="button" className="primary" onClick={onGoToExport}>
              Export DOCX / TXT
            </button>
          ) : (
            <button type="button" onClick={onGoToReview}>
              Back to Page Review
            </button>
          )}
        </div>
      </div>
    </section>
  );
}
