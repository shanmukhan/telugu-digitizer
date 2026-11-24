import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import type { ReviewBlock } from "../types/api";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

interface SourcePageViewerProps {
  bookId: string;
  pageNumber: number;
  pageCount: number;
  widthPx: number | null;
  heightPx: number | null;
  blocks: ReviewBlock[];
  selectedBlockId: string | null;
  onSelectBlock: (blockId: string) => void;
  onNavigatePage: (pageNumber: number) => void;
}

export function SourcePageViewer({
  bookId,
  pageNumber,
  pageCount,
  widthPx,
  heightPx,
  blocks,
  selectedBlockId,
  onSelectBlock,
  onNavigatePage,
}: SourcePageViewerProps) {
  const [viewMode, setViewMode] = useState<"overlay" | "pdfjs">("overlay");
  const [zoom, setZoom] = useState(1.0);
  const [pdfStatus, setPdfStatus] = useState<string>("");
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const naturalWidth = widthPx ?? 1200;
  const naturalHeight = heightPx ?? 1600;
  const displayWidth = Math.round(760 * zoom);
  const displayHeight = Math.round((760 * zoom * naturalHeight) / naturalWidth);

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
      <div className="pane-toolbar">
        <button
          type="button"
          aria-label="Previous page"
          disabled={pageNumber <= 1}
          onClick={() => onNavigatePage(pageNumber - 1)}
        >
          ← Prev
        </button>
        <strong style={{ marginInline: "0.25rem" }}>
          Page {pageNumber} / {pageCount}
        </strong>
        <button
          type="button"
          aria-label="Next page"
          disabled={pageNumber >= pageCount}
          onClick={() => onNavigatePage(pageNumber + 1)}
        >
          Next →
        </button>
        <button
          type="button"
          className={viewMode === "overlay" ? "primary" : undefined}
          aria-pressed={viewMode === "overlay"}
          onClick={() => setViewMode("overlay")}
        >
          Raster + OCR Boxes
        </button>
        <button
          type="button"
          className={viewMode === "pdfjs" ? "primary" : undefined}
          aria-pressed={viewMode === "pdfjs"}
          onClick={() => setViewMode("pdfjs")}
        >
          PDF.js Original
        </button>

        <div style={{ marginInlineStart: "auto", display: "flex", gap: "0.35rem", alignItems: "center" }}>
          <button
            type="button"
            aria-label="Zoom out"
            onClick={() => setZoom((z) => Math.max(0.5, Number((z - 0.2).toFixed(2))))}
          >
            −
          </button>
          <span className="hint-text" style={{ minWidth: "3.2rem", textAlign: "center" }}>
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            aria-label="Zoom in"
            onClick={() => setZoom((z) => Math.min(2.5, Number((z + 0.2).toFixed(2))))}
          >
            +
          </button>
          <button type="button" onClick={() => setZoom(1.0)}>
            Reset
          </button>
        </div>
      </div>

      <div className="pane-body">
        {viewMode === "overlay" ? (
          <div
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
                  const isFlagged =
                    block.low_confidence_flag ||
                    block.disagreement_flag ||
                    block.short_or_empty_flag;
                  const classes = [
                    "overlay-poly",
                    isFlagged ? "flagged" : "",
                    isSelected ? "selected" : "",
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
