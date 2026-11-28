import { useEffect, useId, useRef } from "react";
import { BookUploadForm } from "./BookUploadForm";

interface ImportBookDialogProps {
  open: boolean;
  busy: boolean;
  maxUploadMb?: number;
  maxPdfPages?: number;
  onClose: () => void;
  onUpload: (formData: FormData) => Promise<void>;
}

export function ImportBookDialog({
  open,
  busy,
  maxUploadMb,
  maxPdfPages,
  onClose,
  onUpload,
}: ImportBookDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();

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
      if (pressedOutside && outside(e) && !busy) dialog.close();
    };
    dialog.addEventListener("pointerdown", onDown);
    dialog.addEventListener("pointerup", onUp);
    return () => {
      dialog.removeEventListener("pointerdown", onDown);
      dialog.removeEventListener("pointerup", onUp);
    };
  }, [busy]);

  return (
    <dialog
      ref={dialogRef}
      className="modal-dialog import-dialog"
      {...({ closedby: busy ? "none" : "any" } as Record<string, unknown>)}
      aria-labelledby={titleId}
      onClose={() => {
        const d = dialogRef.current;
        if (d) d.returnValue = "";
        onClose();
      }}
    >
      <div className="modal-head">
        <h1 id={titleId}>Import Printed Telugu PDF</h1>
        <form method="dialog">
          <button
            type="submit"
            value="close"
            className="btn-compact"
            disabled={busy}
            aria-label="Close import dialog"
          >
            ✕
          </button>
        </form>
      </div>
      <div className="modal-body">
        <BookUploadForm
          busy={busy}
          embedded
          maxUploadMb={maxUploadMb}
          maxPdfPages={maxPdfPages}
          onUpload={async (data) => {
            await onUpload(data);
            onClose();
          }}
        />
      </div>
    </dialog>
  );
}
