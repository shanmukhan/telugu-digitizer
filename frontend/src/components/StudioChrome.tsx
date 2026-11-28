import { useState, type ReactNode } from "react";
import type {
  BookOCRRunSummary,
  BookSummary,
  PageReviewPayload,
  PageSummary,
} from "../types/api";
import { formatEngineLabel, formatPageKind, formatReviewStatus } from "../utils/formatters";

/** Product commitments surfaced in the UI. Keep in sync with docs/00-product-brief.md. */
export const CORE_COMMITMENTS: Array<{ icon: string; text: string }> = [
  { icon: "🔒", text: "Runs 100% on this machine" },
  { icon: "🧾", text: "Raw OCR output is never overwritten" },
  { icon: "✍️", text: "No silent Telugu auto-correction" },
  { icon: "📄", text: "Source PDF stored read-only" },
];

export function CommitmentBar() {
  return (
    <div className="commitment-bar" role="note" aria-label="Core commitments">
      {CORE_COMMITMENTS.map((item) => (
        <span key={item.text} className="commit-item">
          <span aria-hidden="true">{item.icon}</span>
          {item.text}
        </span>
      ))}
      <a
        className="commit-link"
        href="https://lahari.org"
        target="_blank"
        rel="noreferrer"
        title="Hosted at lahari.org"
      >
        <span aria-hidden="true">🌐</span>
        lahari.org
      </a>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Workflow stepper                                                    */
/* ------------------------------------------------------------------ */

export type StepState = "done" | "active" | "todo" | "warn";
export type StepKey = "import" | "ocr" | "review" | "export";

export interface WorkflowStep {
  key: StepKey;
  label: string;
  detail: string;
  state: StepState;
  current: boolean;
  enabled: boolean;
}

export function deriveWorkflowSteps(
  book: BookSummary,
  runs: BookOCRRunSummary[],
  pages: PageSummary[],
  activeView: "review" | "memory" | "export",
): WorkflowStep[] {
  const needsOcr = book.scanned_pages_count + book.mixed_pages_count > 0;
  const running = runs.some((r) => r.status === "running" || r.status === "queued");
  const completedRuns = runs.filter((r) => r.status === "completed");
  const incomplete = runs.some((r) => r.status === "partial" || r.status === "failed");
  const ocrDone = !needsOcr || completedRuns.length > 0;
  const approved = pages.filter((p) => p.review_status === "approved").length;
  const total = book.page_count;
  const reviewDone = total > 0 && approved >= total;

  const ocrState: StepState = running ? "active" : ocrDone ? "done" : incomplete ? "warn" : "todo";
  const ocrDetail = running
    ? "In progress"
    : !needsOcr
      ? "Digital text — no OCR needed"
      : ocrDone
        ? `${completedRuns.length} run${completedRuns.length === 1 ? "" : "s"} complete`
        : incomplete
          ? "Partial — resume available"
          : "Not started";

  const steps: WorkflowStep[] = [
    {
      key: "import",
      label: "Import",
      detail: `${book.page_count} pages stored`,
      state: "done",
      current: false,
      enabled: false,
    },
    { key: "ocr", label: "OCR", detail: ocrDetail, state: ocrState, current: false, enabled: false },
    {
      key: "review",
      label: "Review",
      detail: `${approved}/${total} pages approved`,
      state: reviewDone ? "done" : "todo",
      current: false,
      enabled: true,
    },
    {
      key: "export",
      label: "Export",
      detail: ocrDone ? "DOCX / TXT ready" : "Needs OCR first",
      state: "todo",
      current: false,
      enabled: ocrDone,
    },
  ];

  let currentKey: StepKey;
  if (activeView === "export") {
    currentKey = "export";
  } else {
    const firstOpen = steps.find((s) => s.key !== "export" && s.state !== "done");
    currentKey = firstOpen ? firstOpen.key : "export";
  }
  return steps.map((s) => ({
    ...s,
    current: s.key === currentKey,
    state: s.key === currentKey && s.state === "todo" ? "active" : s.state,
  }));
}

interface WorkflowStepperProps {
  steps: WorkflowStep[];
  onGoToReview: () => void;
  onGoToExport: () => void;
}

export function WorkflowStepper({ steps, onGoToReview, onGoToExport }: WorkflowStepperProps) {
  return (
    <ol className="stepper" aria-label="Digitization workflow">
      {steps.map((step, idx) => {
        const handler =
          step.key === "review" ? onGoToReview : step.key === "export" ? onGoToExport : undefined;
        const interactive = Boolean(handler) && step.enabled;
        const badge = step.state === "done" ? "✓" : step.state === "warn" ? "!" : String(idx + 1);
        const body = (
          <>
            <span className="step-badge" aria-hidden="true">
              {badge}
            </span>
            <span className="step-text">
              <strong>{step.label}</strong>
              <span className="step-detail">{step.detail}</span>
            </span>
          </>
        );
        return (
          <li
            key={step.key}
            className={`step ${step.state}${step.current ? " current" : ""}`}
            aria-current={step.current ? "step" : undefined}
          >
            {interactive ? (
              <button type="button" className="step-body step-button" onClick={handler}>
                {body}
              </button>
            ) : (
              <div className="step-body">{body}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/* ------------------------------------------------------------------ */
/* Overview stat cards                                                 */
/* ------------------------------------------------------------------ */

interface OverviewCardsProps {
  book: BookSummary;
  pages: PageSummary[];
  runs: BookOCRRunSummary[];
  review: PageReviewPayload | null;
}

function StatCard({
  icon,
  tone,
  label,
  value,
  sub,
  progress,
}: {
  icon: string;
  tone: "indigo" | "saffron" | "green" | "slate";
  label: string;
  value: string;
  sub: string;
  progress?: { value: number; max: number; label: string };
}) {
  return (
    <article className={`stat-card tone-${tone}`}>
      <div className="stat-card-head">
        <span className="stat-icon" aria-hidden="true">
          {icon}
        </span>
        <span className="stat-label">{label}</span>
      </div>
      <div className="stat-value" lang={label === "Book" ? "te" : undefined}>
        {value}
      </div>
      <div className="stat-sub">{sub}</div>
      {progress && (
        <progress
          className="stat-progress"
          max={progress.max}
          value={progress.value}
          aria-label={progress.label}
        />
      )}
    </article>
  );
}

export function OverviewCards({ book, pages, runs, review }: OverviewCardsProps) {
  const approved = pages.filter((p) => p.review_status === "approved").length;
  const needsAttention = pages.filter((p) => p.review_status === "needs_attention").length;
  const completedRuns = runs.filter((r) => r.status === "completed");
  const activeRuns = runs.filter((r) => r.status === "running" || r.status === "queued");
  const engines = Array.from(new Set(completedRuns.map((r) => formatEngineLabel(r.engine))));
  const percent = book.page_count > 0 ? Math.round((approved / book.page_count) * 100) : 0;

  const flagged = review
    ? review.blocks.filter(
        (b) =>
          b.low_confidence_flag ||
          b.disagreement_flag ||
          b.short_or_empty_flag ||
          b.suggestions.length > 0,
      ).length
    : 0;

  return (
    <div className="stat-grid" role="list" aria-label="Book overview">
      <div role="listitem">
        <StatCard
          icon="📖"
          tone="indigo"
          label="Book"
          value={book.title}
          sub={`${book.page_count} pages · ${book.scanned_pages_count} scanned · ${book.digital_text_pages_count} digital${
            book.mixed_pages_count ? ` · ${book.mixed_pages_count} mixed` : ""
          }`}
        />
      </div>
      <div role="listitem">
        <StatCard
          icon="🧠"
          tone="saffron"
          label="OCR Engines"
          value={
            activeRuns.length > 0
              ? `${activeRuns.length} running`
              : engines.length > 0
                ? `${engines.length} ready`
                : "None yet"
          }
          sub={
            engines.length > 0
              ? engines.join(" + ")
              : activeRuns.length > 0
                ? "Live progress shown above"
                : "Run OCR to extract Telugu text"
          }
        />
      </div>
      <div role="listitem">
        <StatCard
          icon="✅"
          tone="green"
          label="Review Progress"
          value={`${percent}%`}
          sub={`${approved}/${book.page_count} approved${
            needsAttention ? ` · ${needsAttention} need attention` : ""
          }`}
          progress={{
            value: approved,
            max: Math.max(book.page_count, 1),
            label: "Pages approved",
          }}
        />
      </div>
      <div role="listitem">
        <StatCard
          icon="🔎"
          tone="slate"
          label="This Page"
          value={review ? `Page ${review.page_number}` : "—"}
          sub={
            review
              ? `${formatPageKind(review.page_kind)} · ${review.blocks.length} lines · ${flagged} flagged · ${formatReviewStatus(review.review_status)}`
              : "Select a page to inspect"
          }
        />
      </div>
    </div>
  );
}

interface OverviewPanelProps extends OverviewCardsProps {
  activeView: "review" | "memory" | "export";
  onGoToReview: () => void;
  onGoToExport: () => void;
}

export function OverviewPanel({
  book,
  pages,
  runs,
  review,
  activeView,
  onGoToReview,
  onGoToExport,
}: OverviewPanelProps) {
  const [open, setOpen] = useState(true);
  const steps = deriveWorkflowSteps(book, runs, pages, activeView);

  return (
    <section className="overview-panel" aria-label="Workspace overview">
      <div className="overview-head">
        <WorkflowStepper steps={steps} onGoToReview={onGoToReview} onGoToExport={onGoToExport} />
        <button
          type="button"
          className="btn-compact overview-toggle"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Hide stats ▴" : "Show stats ▾"}
        </button>
      </div>
      {open && <OverviewCards book={book} pages={pages} runs={runs} review={review} />}
    </section>
  );
}

/* ------------------------------------------------------------------ */
/* Welcome hero (empty library)                                        */
/* ------------------------------------------------------------------ */

const FEATURES: Array<{ icon: string; title: string; text: string }> = [
  {
    icon: "🔒",
    title: "Local-first & private",
    text: "PDFs, page images, OCR output and edits stay in your own workspace and PostgreSQL. No cloud OCR, no uploads.",
  },
  {
    icon: "⚖️",
    title: "Dual-engine OCR",
    text: "PaddleOCR PP-OCRv5 (te) and Tesseract 5 (tel) run on identical page images. Model identifiers are pinned — never silently swapped.",
  },
  {
    icon: "🧾",
    title: "Raw output preserved",
    text: "Machine text is immutable. Every correction is an append-only event, and Revert to Raw OCR is always one click away.",
  },
  {
    icon: "🔎",
    title: "Side-by-side proofreading",
    text: "Scan boxes and editable lines stay linked with Sync, with flags for low confidence and engine disagreement.",
  },
  {
    icon: "🧠",
    title: "Correction memory",
    text: "Approved fixes become contextual suggestions you accept per block — never a blind global find-and-replace.",
  },
  {
    icon: "📄",
    title: "Faithful export",
    text: "Page-preserving or editable-flow DOCX plus UTF-8 TXT, validated before download, with on-screen Telugu keyboards while you edit.",
  },
];

const PIPELINE = ["Import PDF", "Run OCR", "Review & correct", "Export DOCX / TXT"];

export function WelcomeHero({
  onImportClick,
  uploadSlot,
}: {
  onImportClick: () => void;
  uploadSlot?: ReactNode;
}) {
  return (
    <div className="welcome">
      <div className={uploadSlot ? "welcome-split" : undefined}>
        <section className="hero" aria-labelledby="hero-title">
          <span className="hero-glyphs" aria-hidden="true" lang="te">
            అ ఆ ఇ ఈ ఉ ఊ
          </span>
          <span className="pill-tag info hero-eyebrow">Telugu book digitization studio</span>
          <h2 id="hero-title">
            Turn printed Telugu books into <em>faithful, editable text</em>.
          </h2>
          <p className="hero-lead">
            Import a scanned PDF, extract text with dual OCR engines, proofread line-by-line
            against the original scan, and export validated DOCX — with raw OCR preserved and
            every correction traceable.
          </p>
          {!uploadSlot && (
            <div className="hero-actions">
              <button type="button" className="primary hero-cta" onClick={onImportClick}>
                Import your first PDF
              </button>
              <span className="hint-text">Stored read-only · deduplicated by SHA-256</span>
            </div>
          )}
          <ol className="pipeline" aria-label="How it works">
            {PIPELINE.map((label, idx) => (
              <li key={label}>
                <span className="pipeline-num" aria-hidden="true">
                  {idx + 1}
                </span>
                {label}
              </li>
            ))}
          </ol>
        </section>

        {uploadSlot && <div className="welcome-upload-col">{uploadSlot}</div>}
      </div>

      <section aria-label="What makes this studio different">
        <div className="feature-grid">
          {FEATURES.map((feature) => (
            <article key={feature.title} className="feature-card">
              <span className="feature-icon" aria-hidden="true">
                {feature.icon}
              </span>
              <h3>{feature.title}</h3>
              <p>{feature.text}</p>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}
