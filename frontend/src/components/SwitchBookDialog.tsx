import { useEffect, useId, useRef, useState } from "react";
import type { BookSummary } from "../types/api";
import { formatProcessingState } from "../utils/formatters";

interface SwitchBookDialogProps {
  open: boolean;
  currentBook: BookSummary | null;
  books: BookSummary[];
  /** Target book ID if the user already picked a specific book from the switcher menu. */
  pendingTargetBookId: string | null;
  /** True if the user clicked "Import / Start Another Book" directly. */
  pendingOpenImport: boolean;
  dirtyBlockCount: number;
  isOcrRunning: boolean;
  approvedPagesCount: number;
  busy?: boolean;
  onKeepWorking: () => void;
  onConfirmSwitch: (options: {
    targetBookId: string | null;
    openImport: boolean;
    saveCurrentPageDrafts: boolean;
  }) => Promise<void>;
}

export function SwitchBookDialog({
  open,
  currentBook,
  books,
  pendingTargetBookId,
  pendingOpenImport,
  dirtyBlockCount,
  isOcrRunning,
  approvedPagesCount,
  busy = false,
  onKeepWorking,
  onConfirmSwitch,
}: SwitchBookDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [selectedBookId, setSelectedBookId] = useState<string | null>(pendingTargetBookId);
  const [submitting, setSubmitting] = useState(false);

  const otherBooks = books.filter((b) => b.book_id !== currentBook?.book_id);
  const targetBook = selectedBookId
    ? books.find((b) => b.book_id === selectedBookId) ?? null
    : null;

  useEffect(() => {
    if (open) {
      setSelectedBookId(pendingTargetBookId ?? (otherBooks[0]?.book_id ?? null));
    }
  }, [open, pendingTargetBookId, otherBooks.length]);

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

  // Safari fallback for closedby="any" using pointerdown + pointerup outside bounds.
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
      if (pressedOutside && outside(e) && !submitting) dialog.close();
    };
    dialog.addEventListener("pointerdown", onDown);
    dialog.addEventListener("pointerup", onUp);
    return () => {
      dialog.removeEventListener("pointerdown", onDown);
      dialog.removeEventListener("pointerup", onUp);
    };
  }, [submitting]);

  async function executeSwitch(opts: {
    targetBookId: string | null;
    openImport: boolean;
    saveCurrentPageDrafts: boolean;
  }) {
    setSubmitting(true);
    try {
      await onConfirmSwitch(opts);
    } finally {
      setSubmitting(false);
    }
  }

  const hasUnfinishedReasons: string[] = [];
  if (dirtyBlockCount > 0) {
    hasUnfinishedReasons.push(`${dirtyBlockCount} unsaved line edit(s) on the current page`);
  }
  if (isOcrRunning) {
    hasUnfinishedReasons.push("an OCR run is currently processing in the background");
  }
  if (currentBook && approvedPagesCount < currentBook.page_count) {
    hasUnfinishedReasons.push(
      `${approvedPagesCount} of ${currentBook.page_count} pages approved (${formatProcessingState(currentBook.processing_state)})`,
    );
  }

  return (
    <dialog
      ref={dialogRef}
      className="modal-dialog switch-book-dialog"
      {...({ closedby: submitting ? "none" : "any" } as Record<string, unknown>)}
      aria-labelledby={titleId}
      onClose={() => {
        const d = dialogRef.current;
        if (d) d.returnValue = "";
        if (!submitting) {
          onKeepWorking();
        }
      }}
    >
      <div className="modal-head">
        <h1 id={titleId} style={{ margin: 0, fontSize: "1.12rem" }}>
          {pendingOpenImport
            ? "Start Another Book?"
            : targetBook && pendingTargetBookId
              ? "Switch to Another Book?"
              : "Switch Book / Start Another Book"}
        </h1>
        <form method="dialog">
          <button
            type="submit"
            value="cancel"
            className="btn-compact"
            disabled={submitting}
            aria-label="Close switch book dialog"
          >
            ✕
          </button>
        </form>
      </div>

      <div className="modal-body">
        {currentBook && (
          <div className="switch-book-notice">
            <p style={{ margin: "0 0 0.45rem" }}>
              Current book: <strong lang="te">{currentBook.title}</strong>
            </p>
            {hasUnfinishedReasons.length > 0 && (
              <ul className="switch-book-reasons">
                {hasUnfinishedReasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            )}
            <p className="hint-text" style={{ margin: "0.45rem 0 0" }}>
              <strong>Your work will NOT be deleted.</strong> Switching books pauses{" "}
              <span lang="te">{currentBook.title}</span> and retains all OCR results, calibration
              settings, and saved corrections so you can return and continue later.
              {isOcrRunning
                ? " Any active OCR run will be safely paused with completed pages saved."
                : ""}
            </p>
          </div>
        )}

        {!pendingOpenImport && !pendingTargetBookId && otherBooks.length > 0 && (
          <div className="switch-book-picker">
            <p className="field-label" style={{ margin: "0 0 0.35rem" }}>
              Choose a book to switch to:
            </p>
            <ul className="switch-book-list" role="radiogroup" aria-label="Available books">
              {otherBooks.map((b) => {
                const isSel = selectedBookId === b.book_id;
                return (
                  <li key={b.book_id}>
                    <button
                      type="button"
                      role="radio"
                      aria-checked={isSel}
                      className={`switch-book-option${isSel ? " selected" : ""}`}
                      onClick={() => setSelectedBookId(b.book_id)}
                    >
                      <span className="telugu-text" lang="te">
                        <strong>{b.title}</strong>
                      </span>
                      <span className="badge-row">
                        <span className="badge">{b.page_count}p</span>
                        <span className="badge">
                          {formatProcessingState(b.processing_state)}
                        </span>
                        {typeof b.approved_pages_count === "number" && (
                          <span className="hint-text">
                            {b.approved_pages_count}/{b.page_count} approved
                          </span>
                        )}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {targetBook && pendingTargetBookId && (
          <p className="hint-text" style={{ margin: "0.5rem 0" }}>
            Destination book: <strong lang="te">{targetBook.title}</strong> ({targetBook.page_count}{" "}
            pages · {formatProcessingState(targetBook.processing_state)})
          </p>
        )}

        <div className="dialog-actions switch-book-actions">
          <form method="dialog">
            <button type="submit" value="cancel" autoFocus disabled={submitting || busy}>
              Continue Current Book
            </button>
          </form>

          {dirtyBlockCount > 0 && (
            <button
              type="button"
              className="primary"
              disabled={submitting || busy || (!pendingOpenImport && !selectedBookId)}
              onClick={() =>
                void executeSwitch({
                  targetBookId: pendingOpenImport ? null : selectedBookId,
                  openImport: pendingOpenImport,
                  saveCurrentPageDrafts: true,
                })
              }
            >
              {submitting
                ? "Saving & Switching…"
                : pendingOpenImport
                  ? "Save Drafts & Start New Book"
                  : "Save Drafts & Switch Book"}
            </button>
          )}

          {(pendingOpenImport || otherBooks.length === 0) ? (
            <button
              type="button"
              className={dirtyBlockCount > 0 ? undefined : "primary"}
              disabled={submitting || busy}
              onClick={() =>
                void executeSwitch({
                  targetBookId: null,
                  openImport: true,
                  saveCurrentPageDrafts: false,
                })
              }
            >
              {dirtyBlockCount > 0 ? "Discard Draft & Upload New Book" : "＋ Upload / Start Another Book"}
            </button>
          ) : (
            <>
              <button
                type="button"
                className={dirtyBlockCount > 0 ? undefined : "primary"}
                disabled={submitting || busy || !selectedBookId}
                onClick={() =>
                  void executeSwitch({
                    targetBookId: selectedBookId,
                    openImport: false,
                    saveCurrentPageDrafts: false,
                  })
                }
              >
                {dirtyBlockCount > 0 ? "Discard Draft & Switch" : "Pause Current & Switch Book"}
              </button>
              {!pendingTargetBookId && (
                <button
                  type="button"
                  disabled={submitting || busy}
                  onClick={() =>
                    void executeSwitch({
                      targetBookId: null,
                      openImport: true,
                      saveCurrentPageDrafts: dirtyBlockCount > 0,
                    })
                  }
                >
                  ＋ Start Another Book (Upload PDF)
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </dialog>
  );
}
