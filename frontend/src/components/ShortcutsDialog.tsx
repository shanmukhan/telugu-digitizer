import { useEffect, useId, useRef } from "react";

interface ShortcutsDialogProps {
  open: boolean;
  onClose: () => void;
}

const SHORTCUTS: Array<{ keys: string; description: string }> = [
  { keys: "Ctrl / ⌘ + Enter", description: "Save active line (or approve if unchanged) and advance to next line" },
  { keys: "Ctrl / ⌘ + Shift + Enter", description: "Save all edited lines and approve the entire page" },
  { keys: "Alt + ↓ / Alt + ↑", description: "Move between lines on the current page" },
  { keys: "Alt + → / Alt + ←", description: "Go to next / previous page" },
  { keys: "Ctrl / ⌘ + D", description: "Quick dictionary lookup for selected word (or word at cursor)" },
  { keys: "Ctrl / ⌘ + Z / Shift+Z", description: "Undo / Redo line edit" },
  { keys: "[", description: "Toggle the collapsible Page Navigator rail" },
  { keys: "?", description: "Open this shortcuts & studio guarantees dialog" },
];

export function ShortcutsDialog({ open, onClose }: ShortcutsDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  const isLocalHost =
    typeof window !== "undefined" &&
    (window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1" ||
      window.location.hostname === "::1");

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
      className="modal-dialog shortcuts-dialog"
      {...({ closedby: "any" } as Record<string, unknown>)}
      aria-labelledby={titleId}
      onClose={() => {
        const d = dialogRef.current;
        if (d) d.returnValue = "";
        onClose();
      }}
    >
      <div className="modal-head">
        <h1 id={titleId}>Proofreading Shortcuts &amp; Studio Guarantees</h1>
        <form method="dialog">
          <button type="submit" value="close" className="btn-compact" aria-label="Close shortcuts dialog">
            ✕
          </button>
        </form>
      </div>

      <div className="modal-body">
        <section aria-label="Keyboard shortcuts">
          <h2 className="modal-section-title">Keyboard Shortcuts</h2>
          <dl className="shortcuts-list">
            {SHORTCUTS.map((item) => (
              <div key={item.keys} className="shortcut-row">
                <dt>
                  <kbd className="kbd-chip">{item.keys}</kbd>
                </dt>
                <dd>{item.description}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section aria-label="Core studio guarantees" className="guarantees-box">
          <h2 className="modal-section-title">Data &amp; Fidelity Guarantees</h2>
          <ul className="guarantees-list">
            <li>
              <strong>{isLocalHost ? "Runs 100% on this machine" : "Private self-hosted processing"}:</strong>{" "}
              {isLocalHost
                ? "PDFs, page renders, OCR models, and PostgreSQL edits remain entirely local."
                : "Processed on your self-hosted Telugu Digitizer server with no third-party cloud OCR APIs."}
            </li>
            <li>
              <strong>Raw OCR output is never overwritten:</strong> Every human edit is stored as an append-only revision event with one-click Revert to Raw OCR.
            </li>
            <li>
              <strong>No silent Telugu auto-correction:</strong> Dictionary &amp; memory suggestions are always opt-in previews you inspect before saving.
            </li>
            <li>
              <strong>Source PDF stored read-only:</strong> Original uploads are deduplicated by SHA-256 and never mutated.
            </li>
          </ul>
          <p className="hint-text" style={{ marginBottom: 0 }}>
            Project home:{" "}
            <a href="https://lahari.org" target="_blank" rel="noreferrer">
              lahari.org
            </a>
          </p>
        </section>
      </div>

      <div className="dialog-actions">
        <form method="dialog">
          <button type="submit" value="done" className="primary" autoFocus>
            Back to Studio
          </button>
        </form>
      </div>
    </dialog>
  );
}
