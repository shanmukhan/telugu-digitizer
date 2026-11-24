import { useEffect, useId, useRef } from "react";

interface DeleteConfirmDialogProps {
  open: boolean;
  bookTitle: string;
  onCancel: () => void;
  onConfirm: () => void;
}

export function DeleteConfirmDialog({
  open,
  bookTitle,
  onCancel,
  onConfirm,
}: DeleteConfirmDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog || "closedBy" in HTMLDialogElement.prototype) return;

    function handleBackdropClick(event: MouseEvent) {
      if (!dialog || event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      const isDialogContent =
        rect.top <= event.clientY &&
        event.clientY <= rect.top + rect.height &&
        rect.left <= event.clientX &&
        event.clientX <= rect.left + rect.width;
      if (isDialogContent) return;
      dialog.close();
    }

    dialog.addEventListener("click", handleBackdropClick);
    return () => dialog.removeEventListener("click", handleBackdropClick);
  }, []);

  function handleClose() {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const result = dialog.returnValue;
    dialog.returnValue = "";
    if (result === "delete") {
      onConfirm();
    } else {
      onCancel();
    }
  }

  return (
    <dialog
      ref={dialogRef}
      {...({ closedby: "any" } as Record<string, unknown>)}
      aria-labelledby={titleId}
      onClose={handleClose}
    >
      <h1 id={titleId} style={{ marginTop: 0, fontSize: "1.15rem" }}>
        Delete book and OCR artifacts?
      </h1>
      <p>
        This permanently removes <strong>{bookTitle}</strong>, its source PDF, rendered PNG pages,
        OCR outputs, and review edits from local storage and PostgreSQL.
      </p>
      <form method="dialog" className="dialog-actions">
        <button type="submit" value="cancel" autoFocus>
          Cancel
        </button>
        <button type="submit" value="delete" className="danger">
          Delete Book
        </button>
      </form>
    </dialog>
  );
}
