import { useEffect, useRef, useState } from "react";

export interface ToastItem {
  id: number;
  kind: "info" | "success";
  text: string;
}

interface ToastRegionProps {
  toasts: ToastItem[];
  onDismiss: (id: number) => void;
}

function ToastCard({ toast, onDismiss }: { toast: ToastItem; onDismiss: (id: number) => void }) {
  const [paused, setPaused] = useState(false);
  const onDismissRef = useRef(onDismiss);
  onDismissRef.current = onDismiss;

  useEffect(() => {
    if (paused) return;
    const timer = window.setTimeout(() => {
      onDismissRef.current(toast.id);
    }, 4500);
    return () => window.clearTimeout(timer);
  }, [paused, toast.id]);

  return (
    <div
      className={`toast-card ${toast.kind === "success" ? "success" : "info"}`}
      role="status"
      aria-live="polite"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={() => setPaused(false)}
    >
      <span className="toast-icon" aria-hidden="true">
        {toast.kind === "success" ? "✓" : "ℹ"}
      </span>
      <span className="toast-text">{toast.text}</span>
      <button
        type="button"
        className="toast-close-btn"
        aria-label="Dismiss notification"
        onClick={() => onDismiss(toast.id)}
      >
        ✕
      </button>
    </div>
  );
}

export function ToastRegion({ toasts, onDismiss }: ToastRegionProps) {
  if (toasts.length === 0) {
    return null;
  }

  return (
    <div className="toast-region" role="region" aria-label="Notifications">
      {toasts.map((toast) => (
        <ToastCard key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}
