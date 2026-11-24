import { useEffect, useMemo, useState } from "react";
import type { BookOCRRunSummary, BookSummary, OCRRunStatus, PageSummary } from "../types/api";
import { buildRunTelemetry, formatDuration, formatEngineLabel } from "../utils/formatters";

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
  const completedRuns = runs.filter((r) => r.status === "completed");
  const partialOrFailed = runs.filter((r) => r.status === "partial" || r.status === "failed");
  const needsScanOcr = book.scanned_pages_count + book.mixed_pages_count > 0;

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

  if (completedRuns.length > 0 || !needsScanOcr) {
    return (
      <div className="header-status-pill ready" role="status" aria-live="polite">
        <span aria-hidden="true">✓</span>
        <span>{needsScanOcr ? "OCR Ready" : "Digital Text Ready"}</span>
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
  activeView: "review" | "memory" | "export";
  onQuickStartSample: () => Promise<void>;
  onQuickStartFull: () => Promise<void>;
  onResumeRun: (runId: string) => Promise<void>;
  onGoToExport: () => void;
  onGoToReview: () => void;
}

export function OcrProgressStrip({
  book,
  runs,
  pages,
  activeView,
  onQuickStartSample,
  onQuickStartFull,
  onResumeRun,
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
              Run a quick 5-page test first or process with selected engines. Note: cover/Page 1 scans may be blank; use <strong>Next →</strong> or page jump to inspect body pages.
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

  // Ready state (at least one completed run or digital-only book)
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
