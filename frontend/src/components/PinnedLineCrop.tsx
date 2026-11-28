import { useEffect, useRef, useState } from "react";
import { resolveAppUrl } from "../api/client";
import type { ReviewBlock } from "../types/api";

interface PinnedLineCropProps {
  bookId: string;
  pageNumber: number;
  block: ReviewBlock | null;
  onOpenFullScan?: () => void;
}

/**
 * Renders a crisp cropped strip of the active line's scanned image bounding box
 * so tablet/mobile users can compare scanned Telugu directly above the active textarea.
 */
export function PinnedLineCrop({
  bookId,
  pageNumber,
  block,
  onOpenFullScan,
}: PinnedLineCropProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [imgReadyUrl, setImgReadyUrl] = useState<string>("");
  const [hasCrop, setHasCrop] = useState(false);

  const imageUrl = resolveAppUrl(`/api/v1/books/${bookId}/pages/${pageNumber}/image`);

  useEffect(() => {
    if (typeof Image === "undefined") return;
    let cancelled = false;
    const img = new Image();
    img.onload = () => {
      if (!cancelled) {
        imgRef.current = img;
        setImgReadyUrl(imageUrl);
      }
    };
    img.src = imageUrl;
    return () => {
      cancelled = true;
    };
  }, [imageUrl]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || imgReadyUrl !== imageUrl || !block) {
      setHasCrop(false);
      return;
    }

    let x1 = 0;
    let y1 = 0;
    let x2 = 0;
    let y2 = 0;
    if (block.bbox && block.bbox.length === 4) {
      [x1, y1, x2, y2] = block.bbox;
    } else if (block.polygon && block.polygon.length >= 3) {
      const xs = block.polygon.map((p) => p[0]);
      const ys = block.polygon.map((p) => p[1]);
      x1 = Math.min(...xs);
      x2 = Math.max(...xs);
      y1 = Math.min(...ys);
      y2 = Math.max(...ys);
    } else {
      setHasCrop(false);
      return;
    }

    const padX = 24;
    const padY = 16;
    const sx = Math.max(0, Math.floor(x1 - padX));
    const sy = Math.max(0, Math.floor(y1 - padY));
    const sw = Math.min(img.naturalWidth - sx, Math.ceil(x2 - x1 + padX * 2));
    const sh = Math.min(img.naturalHeight - sy, Math.ceil(y2 - y1 + padY * 2));
    if (sw <= 4 || sh <= 4) {
      setHasCrop(false);
      return;
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const maxDisplayW = 720;
    const scale = Math.min(1.35, maxDisplayW / sw);
    const dw = Math.round(sw * scale);
    const dh = Math.min(110, Math.round(sh * scale));

    canvas.width = dw;
    canvas.height = dh;
    ctx.clearRect(0, 0, dw, dh);
    ctx.drawImage(img, sx, sy, sw, sh, 0, 0, dw, dh);
    setHasCrop(true);
  }, [block, imageUrl, imgReadyUrl]);

  if (!block) return null;

  return (
    <div
      className={`pinned-line-crop${hasCrop ? " has-crop" : ""}`}
      aria-label={`Scanned crop for line ${block.block_index + 1}`}
    >
      <div className="pinned-line-crop-head">
        <span className="hint-text">
          <strong>Scan crop · Line {block.block_index + 1}</strong>
        </span>
        {onOpenFullScan && (
          <button type="button" className="btn-compact" onClick={onOpenFullScan}>
            View Full Scan
          </button>
        )}
      </div>
      <canvas ref={canvasRef} className="pinned-crop-canvas" />
    </div>
  );
}
