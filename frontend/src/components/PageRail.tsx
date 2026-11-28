import { useEffect, useMemo, useRef, useState } from "react";
import type { PageSummary } from "../types/api";
import { formatReviewStatus } from "../utils/formatters";

interface PageRailProps {
  open: boolean;
  pages: PageSummary[];
  selectedPageNumber: number;
  pageFilter: "all" | "pending" | "approved" | "needs_attention";
  onChangeFilter: (filter: "all" | "pending" | "approved" | "needs_attention") => void;
  onSelectPage: (pageNumber: number) => void;
  onClose: () => void;
}

const ROW_HEIGHT = 38;
const OVERSCAN = 8;

function shortKind(kind: string): string {
  if (kind === "digital_text") return "Dig";
  if (kind === "mixed") return "Mix";
  return "Scan";
}

function statusIndicator(status: PageSummary["review_status"]): { symbol: string; cls: string } {
  switch (status) {
    case "approved":
      return { symbol: "✓", cls: "ok" };
    case "needs_attention":
      return { symbol: "⚑", cls: "warn" };
    case "in_review":
      return { symbol: "◐", cls: "info" };
    default:
      return { symbol: "○", cls: "neutral" };
  }
}

export function PageRail({
  open,
  pages,
  selectedPageNumber,
  pageFilter,
  onChangeFilter,
  onSelectPage,
  onClose,
}: PageRailProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(540);

  const counts = useMemo(() => {
    let approved = 0;
    let needsAttention = 0;
    for (const p of pages) {
      if (p.review_status === "approved") approved += 1;
      else if (p.review_status === "needs_attention") needsAttention += 1;
    }
    return {
      all: pages.length,
      approved,
      pending: pages.length - approved,
      needsAttention,
    };
  }, [pages]);

  const filteredPages = useMemo(() => {
    if (pageFilter === "approved") {
      return pages.filter((p) => p.review_status === "approved");
    }
    if (pageFilter === "pending") {
      return pages.filter((p) => p.review_status !== "approved");
    }
    if (pageFilter === "needs_attention") {
      return pages.filter((p) => p.review_status === "needs_attention");
    }
    return pages;
  }, [pages, pageFilter]);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    const updateHeight = () => {
      if (el.clientHeight > 0) setViewportHeight(el.clientHeight);
    };
    updateHeight();
    if (typeof ResizeObserver === "function") {
      const obs = new ResizeObserver(updateHeight);
      obs.observe(el);
      return () => obs.disconnect();
    }
    return undefined;
  }, [open]);

  // Keep selected page scrolled into view in the virtual list when changed externally
  useEffect(() => {
    if (!open || !scrollerRef.current) return;
    const idx = filteredPages.findIndex((p) => p.page_number === selectedPageNumber);
    if (idx === -1) return;
    const top = idx * ROW_HEIGHT;
    const el = scrollerRef.current;
    if (top < el.scrollTop || top + ROW_HEIGHT > el.scrollTop + el.clientHeight) {
      el.scrollTop = Math.max(0, top - el.clientHeight / 2 + ROW_HEIGHT / 2);
    }
  }, [open, selectedPageNumber, filteredPages]);

  if (!open) {
    return null;
  }

  const totalHeight = filteredPages.length * ROW_HEIGHT;
  const startIdx = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const visibleCount = Math.ceil(viewportHeight / ROW_HEIGHT) + OVERSCAN * 2;
  const endIdx = Math.min(filteredPages.length, startIdx + visibleCount);
  const visibleSlice = filteredPages.slice(startIdx, endIdx);

  return (
    <aside className="page-rail" aria-label="Book pages navigator">
      <div className="page-rail-head">
        <div>
          <strong className="page-rail-title">Pages ({counts.all})</strong>
          <div className="hint-text">
            {counts.approved} approved · {counts.pending} left
          </div>
        </div>
        <button
          type="button"
          className="btn-compact icon-only-btn"
          aria-label="Collapse pages rail"
          title="Hide Pages Rail ([)"
          onClick={onClose}
        >
          ✕
        </button>
      </div>

      <div className="page-rail-filters" role="group" aria-label="Filter pages">
        <button
          type="button"
          className="btn-compact"
          aria-pressed={pageFilter === "all"}
          onClick={() => onChangeFilter("all")}
        >
          All
        </button>
        <button
          type="button"
          className="btn-compact"
          aria-pressed={pageFilter === "pending"}
          onClick={() => onChangeFilter("pending")}
        >
          Pending
        </button>
        <button
          type="button"
          className="btn-compact"
          aria-pressed={pageFilter === "approved"}
          onClick={() => onChangeFilter("approved")}
        >
          Done
        </button>
        {counts.needsAttention > 0 && (
          <button
            type="button"
            className="btn-compact"
            aria-pressed={pageFilter === "needs_attention"}
            onClick={() => onChangeFilter("needs_attention")}
          >
            ⚑ {counts.needsAttention}
          </button>
        )}
      </div>

      <div
        ref={scrollerRef}
        className="page-rail-scroller"
        onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
      >
        {filteredPages.length === 0 ? (
          <p className="hint-text" style={{ padding: "0.75rem" }}>
            No pages in this filter.
          </p>
        ) : (
          <div className="page-rail-virtual-space" style={{ blockSize: `${totalHeight}px` }}>
            <ul
              className="page-rail-list"
              style={{ transform: `translateY(${startIdx * ROW_HEIGHT}px)` }}
            >
              {visibleSlice.map((p) => {
                const isSelected = p.page_number === selectedPageNumber;
                const ind = statusIndicator(p.review_status);
                return (
                  <li key={p.page_id} style={{ blockSize: `${ROW_HEIGHT}px` }}>
                    <button
                      type="button"
                      className={`page-rail-row ${isSelected ? "selected" : ""}`.trim()}
                      aria-current={isSelected ? "page" : undefined}
                      title={`Page ${p.page_number} — ${formatReviewStatus(p.review_status)}`}
                      onClick={() => onSelectPage(p.page_number)}
                    >
                      <span className={`page-status-dot ${ind.cls}`} aria-hidden="true">
                        {ind.symbol}
                      </span>
                      <span className="page-rail-num">p. {p.page_number}</span>
                      <span className="page-rail-kind">{shortKind(p.page_kind)}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        )}
      </div>
    </aside>
  );
}
