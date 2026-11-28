"""Deterministic geometric reading-order sorting and conservative two-column layout helpers."""

from __future__ import annotations

from typing import Any


def _extract_bbox(block: dict[str, Any]) -> tuple[float, float, float, float] | None:
    raw_bbox = block.get("bbox")
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) == 4:
        try:
            x1, y1, x2, y2 = (float(raw_bbox[0]), float(raw_bbox[1]), float(raw_bbox[2]), float(raw_bbox[3]))
            if x2 >= x1 and y2 >= y1:
                return x1, y1, x2, y2
        except (TypeError, ValueError):
            pass

    poly = block.get("polygon")
    if isinstance(poly, (list, tuple)) and poly:
        xs: list[float] = []
        ys: list[float] = []
        for pt in poly:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                try:
                    xs.append(float(pt[0]))
                    ys.append(float(pt[1]))
                except (TypeError, ValueError):
                    continue
        if xs and ys:
            return min(xs), min(ys), max(xs), max(ys)
    return None


def _sort_single_column_lines(
    items: list[tuple[dict[str, Any], tuple[float, float, float, float]]],
) -> list[dict[str, Any]]:
    """Sort blocks top-to-bottom while clustering horizontally adjacent spans on the same baseline."""
    if not items:
        return []
    ordered_by_y = sorted(
        items,
        key=lambda item: (item[1][1], item[1][0], int(item[0].get("block_index", 0))),
    )
    rows: list[list[tuple[dict[str, Any], tuple[float, float, float, float]]]] = []
    for blk, box in ordered_by_y:
        yc = 0.5 * (box[1] + box[3])
        h = max(4.0, box[3] - box[1])
        placed = False
        if rows:
            prev_row = rows[-1]
            prev_yc = sum(0.5 * (b[1] + b[3]) for _, b in prev_row) / len(prev_row)
            prev_h = max(4.0, min(b[3] - b[1] for _, b in prev_row))
            if abs(yc - prev_yc) <= 0.45 * min(h, prev_h):
                prev_row.append((blk, box))
                placed = True
        if not placed:
            rows.append([(blk, box)])

    result: list[dict[str, Any]] = []
    for row in rows:
        row.sort(key=lambda item: (item[1][0], item[1][1], int(item[0].get("block_index", 0))))
        for blk, _ in row:
            result.append(blk)
    return result


def order_ocr_blocks_geometrically(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort OCR line blocks into reading order with conservative two-column split detection.

    Preserves each block's original ``block_index`` while updating ``reading_order``
    and returning the sorted block list.
    """
    if len(blocks) <= 1:
        for idx, blk in enumerate(blocks):
            blk["reading_order"] = idx
        return blocks

    with_boxes: list[tuple[dict[str, Any], tuple[float, float, float, float]]] = []
    without_boxes: list[dict[str, Any]] = []
    for blk in blocks:
        box = _extract_bbox(blk)
        if box is None:
            without_boxes.append(blk)
        else:
            with_boxes.append((blk, box))

    if not with_boxes:
        for idx, blk in enumerate(blocks):
            blk["reading_order"] = idx
        return blocks

    sorted_blocks: list[dict[str, Any]] | None = None

    # Conservative two-column detector: requires >= 6 blocks, crisp vertical gutter near page center,
    # >= 3 lines strictly left and >= 3 strictly right, and minimal (< 15%) lines crossing the gutter.
    if len(with_boxes) >= 6:
        min_x = min(box[0] for _, box in with_boxes)
        max_x = max(box[2] for _, box in with_boxes)
        span_w = max_x - min_x
        if span_w > 120.0:
            best_split_x: float | None = None
            best_score: tuple[int, int] = (999, 0)
            for frac in (0.42, 0.46, 0.50, 0.54, 0.58):
                split_x = min_x + span_w * frac
                margin = span_w * 0.012
                left_cnt = sum(1 for _, box in with_boxes if box[2] <= split_x - margin)
                right_cnt = sum(1 for _, box in with_boxes if box[0] >= split_x + margin)
                cross_cnt = len(with_boxes) - left_cnt - right_cnt
                if (
                    left_cnt >= 3
                    and right_cnt >= 3
                    and cross_cnt <= max(1, int(len(with_boxes) * 0.14))
                ):
                    score = (cross_cnt, -(left_cnt + right_cnt))
                    if score < best_score:
                        best_score = score
                        best_split_x = split_x

            if best_split_x is not None:
                left_col: list[tuple[dict[str, Any], tuple[float, float, float, float]]] = []
                right_col: list[tuple[dict[str, Any], tuple[float, float, float, float]]] = []
                top_headers: list[tuple[dict[str, Any], tuple[float, float, float, float]]] = []
                bottom_footers: list[tuple[dict[str, Any], tuple[float, float, float, float]]] = []
                col_mid_y = (min(b[1] for _, b in with_boxes) + max(b[3] for _, b in with_boxes)) * 0.5
                for blk, box in with_boxes:
                    xc = 0.5 * (box[0] + box[2])
                    yc = 0.5 * (box[1] + box[3])
                    crosses = box[0] < best_split_x < box[2] and (box[2] - box[0]) > span_w * 0.45
                    if crosses:
                        if yc <= col_mid_y:
                            top_headers.append((blk, box))
                        else:
                            bottom_footers.append((blk, box))
                    elif xc <= best_split_x:
                        left_col.append((blk, box))
                    else:
                        right_col.append((blk, box))

                if len(left_col) >= 3 and len(right_col) >= 3:
                    sorted_blocks = (
                        _sort_single_column_lines(top_headers)
                        + _sort_single_column_lines(left_col)
                        + _sort_single_column_lines(right_col)
                        + _sort_single_column_lines(bottom_footers)
                    )

    if sorted_blocks is None:
        sorted_blocks = _sort_single_column_lines(with_boxes)

    ordered = sorted_blocks + sorted(
        without_boxes,
        key=lambda blk: int(blk.get("block_index", 0)),
    )
    for order_idx, blk in enumerate(ordered):
        blk["reading_order"] = order_idx
    return ordered
