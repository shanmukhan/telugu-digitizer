import { useEffect, useRef, useState } from "react";
import type { PDFDocumentProxy } from "pdfjs-dist";
import { resolveAppUrl } from "../api/client";
import type { ReviewBlock } from "../types/api";
import { scrollContainerToAsync } from "../utils/scrollSync";

let pdfjsModulePromise: Promise<typeof import("pdfjs-dist")> | null = null;

async function loadPdfJs() {
  if (!pdfjsModulePromise) {
    pdfjsModulePromise = Promise.all([
      import("pdfjs-dist"),
      import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
    ]).then(([pdfjs, workerUrlMod]) => {
      pdfjs.GlobalWorkerOptions.workerSrc = workerUrlMod.default;
      return pdfjs;
    });
  }
  return pdfjsModulePromise;
}

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
  /** When page navigation lives in the unified workspace sub-toolbar, hide duplicate Prev/Next here. */
  hidePageNav?: boolean;
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
  hidePageNav = false,
  onSelectBlock,
  onNavigatePage,
  onSyncToEditor,
  onToggleAutoSync,
}: SourcePageViewerProps) {
  const [viewMode, setViewMode] = useState<"overlay" | "pdfjs">("overlay");
  const [fitMode, setFitMode] = useState(true);
  const [containerWidth, setContainerWidth] = useState(640);
  const [manualZoom, setManualZoom] = useState(1.0);
  const [pageJumpInput, setPageJumpInput] = useState(String(pageNumber));
  const [pdfStatus, setPdfStatus] = useState<string>("");
  const pageKey = `${bookId}:${pageNumber}`;
  const [loadedImageKey, setLoadedImageKey] = useState<string>("");
  const [flashingBlockId, setFlashingBlockId] = useState<string | null>(null);
  const [syncNotice, setSyncNotice] = useState<string>("");
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const paneBodyRef = useRef<HTMLDivElement>(null);
  const canvasWrapRef = useRef<HTMLDivElement>(null);
  const syncSeqRef = useRef(0);
  const lastHandledSyncSeqRef = useRef<number | null>(null);
  const cachedPdfDocRef = useRef<{ bookId: string; doc: PDFDocumentProxy } | null>(null);

  const imageLoading = loadedImageKey !== pageKey;

  useEffect(() => {
    return () => {
      if (cachedPdfDocRef.current) {
        cachedPdfDocRef.current.doc.destroy().catch(() => {});
        cachedPdfDocRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    setPageJumpInput(String(pageNumber));
  }, [bookId, pageNumber]);

  useEffect(() => {
    const el = paneBodyRef.current;
    if (!el) return;
    const measure = () => {
      if (el.clientWidth > 0) {
        setContainerWidth(Math.max(260, el.clientWidth - 28));
      }
    };
    measure();
    if (typeof ResizeObserver === "function") {
      const obs = new ResizeObserver(measure);
      obs.observe(el);
      return () => obs.disconnect();
    }
    return undefined;
  }, []);

  const computedFitZoom = Math.min(2.2, Math.max(0.4, Number((containerWidth / 760).toFixed(2))));
  const effectiveZoom = fitMode ? computedFitZoom : manualZoom;

  function handleFitToPane() {
    setFitMode(true);
    setManualZoom(computedFitZoom);
  }

  function stepZoom(delta: number) {
    const next = Math.min(2.5, Math.max(0.4, Number((effectiveZoom + delta).toFixed(2))));
    setFitMode(false);
    setManualZoom(next);
  }

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
  const displayWidth = Math.round(760 * effectiveZoom);
  const displayHeight = Math.round((760 * effectiveZoom * naturalHeight) / naturalWidth);

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
    let loadingTask: { destroy?: () => Promise<void> } | null = null;

    async function renderPdfPage() {
      const canvas = canvasRef.current;
      if (!canvas) return;
      setPdfStatus("Rendering PDF via PDF.js...");
      try {
        const pdfjsLib = await loadPdfJs();
        if (cancelled) return;

        let pdfDoc: PDFDocumentProxy;
        if (cachedPdfDocRef.current && cachedPdfDocRef.current.bookId === bookId) {
          pdfDoc = cachedPdfDocRef.current.doc;
        } else {
          if (cachedPdfDocRef.current) {
            cachedPdfDocRef.current.doc.destroy().catch(() => {});
            cachedPdfDocRef.current = null;
          }
          const task = pdfjsLib.getDocument({
            url: resolveAppUrl(`/api/v1/books/${bookId}/pdf`),
            disableAutoFetch: true,
            disableStream: false,
            rangeChunkSize: 65536,
          });
          loadingTask = task;
          pdfDoc = await task.promise;
          if (cancelled) {
            pdfDoc.destroy().catch(() => {});
            return;
          }
          cachedPdfDocRef.current = { bookId, doc: pdfDoc };
        }

        const page = await pdfDoc.getPage(pageNumber);
        if (cancelled) return;

        const baseViewport = page.getViewport({ scale: 1.0 });
        const targetScale = (760 * effectiveZoom) / baseViewport.width;
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
      if (loadingTask && typeof loadingTask.destroy === "function" && !cachedPdfDocRef.current) {
        loadingTask.destroy().catch(() => {});
      }
    };
  }, [bookId, pageNumber, viewMode, effectiveZoom]);

  // Roving arrow-key navigation inside the single-tab-stop SVG overlay (fixes P0 30+ invisible Tab stops)
  function handleOverlayKeyDown(e: React.KeyboardEvent<SVGSVGElement>) {
    if (blocks.length === 0) return;
    const currentIdx = blocks.findIndex((b) => b.block_id === selectedBlockId);
    let nextIdx: number | null = null;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") {
      nextIdx = currentIdx < 0 ? 0 : (currentIdx + 1) % blocks.length;
    } else if (e.key === "ArrowUp" || e.key === "ArrowLeft") {
      nextIdx = currentIdx <= 0 ? blocks.length - 1 : currentIdx - 1;
    } else if (e.key === "Home") {
      nextIdx = 0;
    } else if (e.key === "End") {
      nextIdx = blocks.length - 1;
    }
    if (nextIdx === null) return;
    e.preventDefault();
    const target = blocks[nextIdx];
    onSelectBlock(target.block_id);
    setSyncNotice(`Selected scan box for line ${target.block_index + 1}.`);
  }

  return (
    <section className="pane" aria-label="Source page viewer">
      <div className="pane-toolbar" role="toolbar" aria-label="Source page controls">
        {!hidePageNav && (
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
        )}

        <div className="segmented-control" role="group" aria-label="Viewer mode">
          <button
            type="button"
            className="btn-compact"
            aria-pressed={viewMode === "overlay"}
            onClick={() => setViewMode("overlay")}
          >
            Scan + Boxes
          </button>
          <button
            type="button"
            className="btn-compact"
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
              ⌖ Sync
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

        <div className="toolbar-group toolbar-end" role="group" aria-label="Zoom controls">
          <button
            type="button"
            className="btn-compact icon-only-btn"
            aria-label="Zoom out"
            onClick={() => stepZoom(-0.15)}
          >
            −
          </button>
          <span className="zoom-readout">{Math.round(effectiveZoom * 100)}%</span>
          <button
            type="button"
            className="btn-compact icon-only-btn"
            aria-label="Zoom in"
            onClick={() => stepZoom(0.15)}
          >
            +
          </button>
          <button
            type="button"
            className="btn-compact"
            aria-pressed={fitMode}
            title="Fit page scan to viewer width"
            onClick={handleFitToPane}
          >
            Fit
          </button>
        </div>
      </div>

      <p className="visually-hidden" role="status" aria-live="polite">
        {syncNotice}
      </p>

      <div ref={paneBodyRef} className="pane-body scan-pane-body">
        {viewMode === "overlay" ? (
          <div
            ref={canvasWrapRef}
            className={`page-canvas-wrap${imageLoading ? " is-loading" : ""}`}
            style={{ width: `${displayWidth}px`, height: `${displayHeight}px` }}
          >
            {imageLoading && (
              <div className="scan-loading-skeleton" role="status" aria-label={`Loading page ${pageNumber} scan`}>
                <span>Rendering page {pageNumber} scan…</span>
              </div>
            )}
            <img
              key={pageKey}
              src={resolveAppUrl(`/api/v1/books/${bookId}/pages/${pageNumber}/image`)}
              alt={`Scanned source page ${pageNumber}`}
              style={{
                width: `${displayWidth}px`,
                height: `${displayHeight}px`,
                opacity: imageLoading ? 0 : 1,
              }}
              onLoad={() => setLoadedImageKey(pageKey)}
              onError={() => setLoadedImageKey(pageKey)}
            />
            {blocks.length > 0 && !imageLoading && (
              <svg
                className="overlay-svg"
                viewBox={`0 0 ${naturalWidth} ${naturalHeight}`}
                tabIndex={0}
                role="listbox"
                aria-label="OCR text region overlays (use Arrow Up/Down to cycle lines)"
                onKeyDown={handleOverlayKeyDown}
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
                      role="option"
                      aria-selected={isSelected}
                      aria-label={`Select OCR block ${block.block_index + 1}`}
                      onClick={() => onSelectBlock(block.block_id)}
                    >
                      <title>{`Line ${block.block_index + 1}: ${block.current_text}`}</title>
                    </polygon>
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
