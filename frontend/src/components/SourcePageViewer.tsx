import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import type { ReviewBlock } from "../types/api";
import { scrollContainerToAsync } from "../utils/scrollSync";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

interface SourcePageViewerProps {
  bookId: string;
  pageNumber: number;
  pageCount: number;
  widthPx: number | null;
  heightPx: number | null;
  blocks: ReviewBlock[];
  selectedBlockId: string | null;
  syncTarget?: { blockId: string; seq: number } | null;
  autoSync?: boolean;
  onSelectBlock: (blockId: string) => void;
  onNavigatePage: (pageNumber: number) => void;
  onSyncToEditor?: () => void;
  onToggleAutoSync?: () => void;
}

export function SourcePageViewer({
  bookId,
  pageNumber,
  pageCount,
  widthPx,
  heightPx,
  blocks,
  selectedBlockId,
  syncTarget = null,
  autoSync = false,
  onSelectBlock,
  onNavigatePage,
  onSyncToEditor,
  onToggleAutoSync,
}: SourcePageViewerProps) {
  const [viewMode, setViewMode] = useState<"overlay" | "pdfjs">("overlay");
  const [zoom, setZoom] = useState(1.0);
  const [pageJumpInput, setPageJumpInput] = useState(String(pageNumber));
  const [pdfStatus, setPdfStatus] = useState<string>("");
  const [flashingBlockId, setFlashingBlockId] = useState<string | null>(null);
  const [syncNotice, setSyncNotice] = useState<string>("");
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const paneBodyRef = useRef<HTMLDivElement>(null);
  const canvasWrapRef = useRef<HTMLDivElement>(null);
  const syncSeqRef = useRef(0);
  const lastHandledSyncSeqRef = useRef<number | null>(null);

  useEffect(() => {
    setPageJumpInput(String(pageNumber));
  }, [pageNumber]);

  function commitPageJump() {
    const target = Number(pageJumpInput.trim());
    if (Number.isInteger(target) && target >= 1 && target <= pageCount) {
      if (target !== pageNumber) {
        onNavigatePage(target);
      }
    } else {
      setPageJumpInput(String(pageNumber));
    }
  }

  const naturalWidth = widthPx ?? 1200;
  const naturalHeight = heightPx ?? 1600;
  const displayWidth = Math.round(760 * zoom);
  const displayHeight = Math.round((760 * zoom * naturalHeight) / naturalWidth);

  useEffect(() => {
    if (!syncTarget) return;
    if (viewMode !== "overlay") {
      setViewMode("overlay");
      return;
    }
    if (lastHandledSyncSeqRef.current === syncTarget.seq) return;
    const targetBlock = blocks.find((b) => b.block_id === syncTarget.blockId);
    const scroller = paneBodyRef.current;
    if (!targetBlock || !scroller) return;

    lastHandledSyncSeqRef.current = syncTarget.seq;
    let centerX = displayWidth / 2;
    let centerY = displayHeight / 2;
    const pts = targetBlock.polygon;
    const bbox = targetBlock.bbox;
    if (pts && pts.length > 0) {
      const xs = pts.map((p) => p[0]);
      const ys = pts.map((p) => p[1]);
      centerX = (((Math.min(...xs) + Math.max(...xs)) / 2) * displayWidth) / naturalWidth;
      centerY = (((Math.min(...ys) + Math.max(...ys)) / 2) * displayHeight) / naturalHeight;
    } else if (bbox && bbox.length === 4) {
      centerX = (((bbox[0] + bbox[2]) / 2) * displayWidth) / naturalWidth;
      centerY = (((bbox[1] + bbox[3]) / 2) * displayHeight) / naturalHeight;
    }

    const wrapLeft = canvasWrapRef.current?.offsetLeft ?? 0;
    const wrapTop = canvasWrapRef.current?.offsetTop ?? 0;
    const targetLeft = wrapLeft + centerX - scroller.clientWidth / 2;
    const targetTop = wrapTop + centerY - scroller.clientHeight / 2;

    const token = ++syncSeqRef.current;
    setFlashingBlockId(null);
    void scrollContainerToAsync(scroller, targetLeft, targetTop).then(() => {
      if (syncSeqRef.current !== token) return;
      setFlashingBlockId(targetBlock.block_id);
      setSyncNotice(`Synced scan view to line ${targetBlock.block_index + 1}.`);
    });
  }, [syncTarget, viewMode, blocks, displayWidth, displayHeight, naturalWidth, naturalHeight]);

  useEffect(() => {
    if (!flashingBlockId) return;
    const timer = window.setTimeout(() => setFlashingBlockId(null), 1600);
    return () => window.clearTimeout(timer);
  }, [flashingBlockId]);

  useEffect(() => {
    if (viewMode !== "pdfjs") return;
    let cancelled = false;
    let activeTask: { cancel: () => void } | null = null;
    let loadedDoc: { destroy: () => Promise<void> } | null = null;

    async function renderPdfPage() {
      const canvas = canvasRef.current;
      if (!canvas) return;
      setPdfStatus("Rendering PDF via PDF.js...");
      try {
        const loadingTask = pdfjsLib.getDocument(`/api/v1/books/${bookId}/pdf`);
        const pdfDoc = await loadingTask.promise;
        loadedDoc = pdfDoc;
        if (cancelled) return;

        const page = await pdfDoc.getPage(pageNumber);
        if (cancelled) return;

        const baseViewport = page.getViewport({ scale: 1.0 });
        const targetScale = (760 * zoom) / baseViewport.width;
        const viewport = page.getViewport({ scale: targetScale });
        const dpr = window.devicePixelRatio || 1;

        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${Math.floor(viewport.width)}px`;
        canvas.style.height = `${Math.floor(viewport.height)}px`;

        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

        const task = page.render({ canvasContext: ctx, viewport });
        activeTask = task;
        await task.promise;
        if (!cancelled) {
          setPdfStatus("");
        }
      } catch (err) {
        if (!cancelled) {
          setPdfStatus(err instanceof Error ? err.message : "Failed to render PDF page.");
        }
      }
    }

    renderPdfPage();
    return () => {
      cancelled = true;
      if (activeTask) {
        activeTask.cancel();
      }
      if (loadedDoc) {
        loadedDoc.destroy().catch(() => {});
      }
    };
  }, [bookId, pageNumber, viewMode, zoom]);

  return (
    <section className="pane" aria-label="Source page viewer">
      <div className="pane-toolbar" role="toolbar" aria-label="Source page navigation and zoom controls">
        <div className="toolbar-group" role="group" aria-label="Page navigation">
          <button
            type="button"
            className="btn-compact"
            aria-label="Previous page"
            disabled={pageNumber <= 1}
            onClick={() => onNavigatePage(pageNumber - 1)}
          >
            ← Prev
          </button>
          <form
            className="page-jump-form"
            onSubmit={(e) => {
              e.preventDefault();
              commitPageJump();
            }}
          >
            <label htmlFor="viewer-page-jump" className="hint-text">
              Page
            </label>
            <input
              id="viewer-page-jump"
              type="number"
              className="page-jump-input"
              aria-label="Jump to page number"
              min={1}
              max={pageCount}
              value={pageJumpInput}
              onChange={(e) => setPageJumpInput(e.target.value)}
              onBlur={commitPageJump}
            />
            <span className="hint-text">/ {pageCount}</span>
          </form>
          <button
            type="button"
            className="btn-compact"
            aria-label="Next page"
            disabled={pageNumber >= pageCount}
            onClick={() => onNavigatePage(pageNumber + 1)}
          >
            Next →
          </button>
        </div>

        <div className="segmented-control" role="group" aria-label="Viewer mode">
          <button
            type="button"
            className={`btn-compact ${viewMode === "overlay" ? "primary" : ""}`.trim()}
            aria-pressed={viewMode === "overlay"}
            onClick={() => setViewMode("overlay")}
          >
            Scan + Boxes
          </button>
          <button
            type="button"
            className={`btn-compact ${viewMode === "pdfjs" ? "primary" : ""}`.trim()}
            aria-pressed={viewMode === "pdfjs"}
            onClick={() => setViewMode("pdfjs")}
          >
            PDF.js
          </button>
        </div>

        {onSyncToEditor && (
          <div className="toolbar-group" role="group" aria-label="Block sync controls">
            <button
              type="button"
              className="btn-compact sync-trigger-btn"
              disabled={!selectedBlockId}
              title="Scroll proofreading editor to the selected box"
              aria-label="Sync to selected block in editor"
              onClick={onSyncToEditor}
            >
              ⌖ Sync → Editor
            </button>
            {onToggleAutoSync && (
              <button
                type="button"
                className="btn-compact"
                aria-pressed={autoSync}
                title="Automatically scroll opposite pane when selecting a block"
                onClick={onToggleAutoSync}
              >
                Auto-Sync
              </button>
            )}
          </div>
        )}

        <div className="toolbar-group" role="group" aria-label="Zoom controls" style={{ marginInlineStart: "auto" }}>
          <button
            type="button"
            className="btn-compact"
            aria-label="Zoom out"
            onClick={() => setZoom((z) => Math.max(0.5, Number((z - 0.2).toFixed(2))))}
          >
            −
          </button>
          <span className="hint-text" style={{ minWidth: "3rem", textAlign: "center", fontWeight: 600 }}>
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            className="btn-compact"
            aria-label="Zoom in"
            onClick={() => setZoom((z) => Math.min(2.5, Number((z + 0.2).toFixed(2))))}
          >
            +
          </button>
          <button type="button" className="btn-compact" onClick={() => setZoom(1.0)}>
            Reset
          </button>
        </div>
      </div>

      <p className="visually-hidden" role="status" aria-live="polite">
        {syncNotice}
      </p>

      <div ref={paneBodyRef} className="pane-body">
        {viewMode === "overlay" ? (
          <div
            ref={canvasWrapRef}
            className="page-canvas-wrap"
            style={{ width: `${displayWidth}px`, height: `${displayHeight}px` }}
          >
            <img
              src={`/api/v1/books/${bookId}/pages/${pageNumber}/image`}
              alt={`Scanned source page ${pageNumber}`}
              style={{ width: `${displayWidth}px`, height: `${displayHeight}px` }}
            />
            {blocks.length > 0 && (
              <svg
                className="overlay-svg"
                viewBox={`0 0 ${naturalWidth} ${naturalHeight}`}
                aria-label="OCR text region overlays"
              >
                {blocks.map((block) => {
                  const pts = block.polygon;
                  if (!pts || pts.length < 3) return null;
                  const pointsAttr = pts.map((p) => `${p[0]},${p[1]}`).join(" ");
                  const isSelected = block.block_id === selectedBlockId;
                  const isFlashing = block.block_id === flashingBlockId;
                  const isFlagged =
                    block.low_confidence_flag ||
                    block.disagreement_flag ||
                    block.short_or_empty_flag;
                  const classes = [
                    "overlay-poly",
                    isFlagged ? "flagged" : "",
                    isSelected ? "selected" : "",
                    isFlashing ? "sync-flash" : "",
                  ]
                    .filter(Boolean)
                    .join(" ");

                  return (
                    <polygon
                      key={block.block_id}
                      points={pointsAttr}
                      className={classes}
                      tabIndex={0}
                      role="button"
                      aria-label={`Select OCR block ${block.block_index + 1}`}
                      onClick={() => onSelectBlock(block.block_id)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onSelectBlock(block.block_id);
                        }
                      }}
                    />
                  );
                })}
              </svg>
            )}
          </div>
        ) : (
          <div className="page-canvas-wrap">
            {pdfStatus && (
              <p className="hint-text" role="status">
                {pdfStatus}
              </p>
            )}
            <canvas ref={canvasRef} aria-label={`PDF.js rendered page ${pageNumber}`} />
          </div>
        )}
      </div>
    </section>
  );
}
