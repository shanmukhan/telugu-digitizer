/** Grapheme-cluster and word-level diff helpers tailored for Telugu aksharas. */

export interface GraphemeDiffPart {
  kind: "equal" | "del" | "ins";
  text: string;
}

export interface ComparatorWordToken {
  word: string;
  trailingSpace: string;
  changed: boolean;
}

let cachedSegmenter: Intl.Segmenter | null | undefined;

function getSegmenter(): Intl.Segmenter | null {
  if (cachedSegmenter !== undefined) return cachedSegmenter;
  if (typeof Intl !== "undefined" && typeof Intl.Segmenter === "function") {
    try {
      cachedSegmenter = new Intl.Segmenter("te", { granularity: "grapheme" });
      return cachedSegmenter;
    } catch {
      cachedSegmenter = null;
      return null;
    }
  }
  cachedSegmenter = null;
  return null;
}

/** Segment Telugu text into extended grapheme clusters (akshara proxy). */
export function segmentTeluguGraphemes(text: string): string[] {
  if (!text) return [];
  const seg = getSegmenter();
  if (seg) {
    return Array.from(seg.segment(text), (item) => item.segment);
  }
  // Fallback: keep base characters joined with following Telugu vowel signs/virama/combining marks
  const out: string[] = [];
  for (const ch of Array.from(text)) {
    const code = ch.codePointAt(0) ?? 0;
    const isCombining =
      (code >= 0x0c00 && code <= 0x0c04) ||
      (code >= 0x0c3e && code <= 0x0c56) ||
      code === 0x0c62 ||
      code === 0x0c63 ||
      code === 0x200c ||
      code === 0x200d ||
      (code >= 0x0300 && code <= 0x036f);
    if (out.length > 0 && (isCombining || out[out.length - 1].endsWith("\u0c4d"))) {
      out[out.length - 1] += ch;
    } else {
      out.push(ch);
    }
  }
  return out;
}

/** Compute an inline grapheme-cluster diff between baseText (raw) and targetText (edited/comparator). */
export function diffTeluguGraphemes(baseText: string, targetText: string): GraphemeDiffPart[] {
  const a = segmentTeluguGraphemes(baseText);
  const b = segmentTeluguGraphemes(targetText);
  if (a.length === 0 && b.length === 0) return [];
  if (baseText === targetText) return [{ kind: "equal", text: baseText }];

  // Guard quadratic DP for very long blocks (>260 graphemes) by falling back to whole-string diff
  if (a.length * b.length > 70_000) {
    return [
      ...(baseText ? [{ kind: "del" as const, text: baseText }] : []),
      ...(targetText ? [{ kind: "ins" as const, text: targetText }] : []),
    ];
  }

  const m = a.length;
  const n = b.length;
  const dp = new Uint16Array((m + 1) * (n + 1));
  const cols = n + 1;

  for (let i = m - 1; i >= 0; i -= 1) {
    for (let j = n - 1; j >= 0; j -= 1) {
      if (a[i] === b[j]) {
        dp[i * cols + j] = dp[(i + 1) * cols + (j + 1)] + 1;
      } else {
        const down = dp[(i + 1) * cols + j];
        const right = dp[i * cols + (j + 1)];
        dp[i * cols + j] = down >= right ? down : right;
      }
    }
  }

  const rawParts: GraphemeDiffPart[] = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (a[i] === b[j]) {
      rawParts.push({ kind: "equal", text: a[i] });
      i += 1;
      j += 1;
    } else if (dp[(i + 1) * cols + j] >= dp[i * cols + (j + 1)]) {
      rawParts.push({ kind: "del", text: a[i] });
      i += 1;
    } else {
      rawParts.push({ kind: "ins", text: b[j] });
      j += 1;
    }
  }
  while (i < m) {
    rawParts.push({ kind: "del", text: a[i] });
    i += 1;
  }
  while (j < n) {
    rawParts.push({ kind: "ins", text: b[j] });
    j += 1;
  }

  // Coalesce adjacent parts of the same kind
  const merged: GraphemeDiffPart[] = [];
  for (const part of rawParts) {
    const prev = merged[merged.length - 1];
    if (prev && prev.kind === part.kind) {
      prev.text += part.text;
    } else {
      merged.push({ ...part });
    }
  }
  return merged;
}

/** Identify comparator words that differ from the current draft for one-click splicing. */
export function diffComparatorWords(
  currentDraft: string,
  comparatorText: string,
): ComparatorWordToken[] {
  const draftWords = new Set(
    currentDraft
      .normalize("NFC")
      .split(/\s+/)
      .map((w) => w.trim())
      .filter(Boolean),
  );
  const matches = Array.from(comparatorText.matchAll(/(\S+)(\s*)/g));
  return matches.map((m) => {
    const word = m[1] ?? "";
    const trailingSpace = m[2] ?? "";
    const normalized = word.normalize("NFC").trim();
    return {
      word,
      trailingSpace,
      changed: normalized.length > 0 && !draftWords.has(normalized),
    };
  });
}
