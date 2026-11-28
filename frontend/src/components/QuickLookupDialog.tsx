import { useEffect, useId, useRef, useState } from "react";
import { ApiClientError, getDictionaryWord, searchDictionary } from "../api/client";
import type { DictionarySearchResponse, DictionaryWordDetail } from "../types/api";

interface QuickLookupDialogProps {
  word: string | null;
  onClose: () => void;
  onOpenFullDictionary: (word: string) => void;
}

export function QuickLookupDialog({
  word,
  onClose,
  onOpenFullDictionary,
}: QuickLookupDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const [query, setQuery] = useState(word ?? "");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<DictionaryWordDetail | null>(null);
  const [searchRes, setSearchRes] = useState<DictionarySearchResponse | null>(null);

  const open = Boolean(word);

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
      if (pressedOutside && outside(e)) {
        dialog.close();
      }
    };
    dialog.addEventListener("pointerdown", onDown);
    dialog.addEventListener("pointerup", onUp);
    return () => {
      dialog.removeEventListener("pointerdown", onDown);
      dialog.removeEventListener("pointerup", onUp);
    };
  }, []);

  async function lookupWord(target: string) {
    const cleaned = target.trim();
    if (!cleaned) return;
    setLoading(true);
    setError(null);
    try {
      const [wRes, sRes] = await Promise.all([
        getDictionaryWord(cleaned),
        searchDictionary(cleaned, { mode: "auto", limit: 8 }),
      ]);
      setDetail(wRes);
      setSearchRes(sRes);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "Dictionary lookup failed.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (word && word.trim()) {
      setQuery(word.trim());
      void lookupWord(word.trim());
    }
  }, [word]);

  return (
    <dialog
      ref={dialogRef}
      className="quick-lookup-dialog"
      {...({ closedby: "any" } as Record<string, unknown>)}
      aria-labelledby={titleId}
      onClose={() => {
        const dialog = dialogRef.current;
        if (dialog) dialog.returnValue = "";
        onClose();
      }}
    >
      <div className="quick-lookup-head">
        <h1 id={titleId} style={{ margin: 0, fontSize: "1.12rem" }}>
          Quick Telugu Dictionary Lookup
        </h1>
        <form method="dialog">
          <button type="submit" value="close" className="btn-compact" aria-label="Close dictionary lookup">
            ✕ Close
          </button>
        </form>
      </div>

      <form
        className="dict-search-bar"
        style={{ marginBlock: "0.65rem" }}
        onSubmit={(e) => {
          e.preventDefault();
          void lookupWord(query);
        }}
      >
        <input
          type="search"
          lang="te"
          autoFocus
          aria-label="Word to look up"
          className="dict-search-input"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button type="submit" className="primary btn-compact" disabled={loading || !query.trim()}>
          {loading ? "Looking up…" : "Look Up"}
        </button>
      </form>

      {error && <p className="status-banner error">{error}</p>}

      {!loading && detail && (
        <div className="quick-lookup-body">
          <div className="badge-row" style={{ justifyContent: "space-between", marginBottom: "0.45rem" }}>
            <div>
              <strong className="telugu-text" lang="te" style={{ fontSize: "1.35rem" }}>
                {detail.word}
              </strong>
              {detail.translit && <span className="hint-text"> ({detail.translit})</span>}
            </div>
            <span className={detail.is_valid_word ? "badge ok" : "badge warn"}>
              {detail.is_valid_word ? "✓ Valid Telugu Word" : "Unlisted"}
            </span>
          </div>

          {detail.did_you_mean.length > 0 && (
            <div className="autocorrect-preview-box" style={{ marginBottom: "0.6rem" }}>
              <strong style={{ fontSize: "0.8rem" }}>Did you mean?</strong>
              <div className="badge-row">
                {detail.did_you_mean.map((sug) => (
                  <button
                    key={sug.word}
                    type="button"
                    className="btn-compact"
                    onClick={() => {
                      setQuery(sug.word);
                      void lookupWord(sug.word);
                    }}
                  >
                    <span lang="te">{sug.word}</span> ({Math.round(sug.confidence * 100)}%)
                  </button>
                ))}
              </div>
            </div>
          )}

          {detail.definitions.length > 0 ? (
            <div className="dict-defs-list">
              {detail.definitions.slice(0, 5).map((d, i) => (
                <div key={`${d.source}-${i}`} className="dict-def-block">
                  <div className="badge-row" style={{ marginBottom: "0.2rem" }}>
                    <span className="badge dict-source-tag">{d.source}</span>
                  </div>
                  <pre className={d.lang === "te" ? "telugu-text dict-def-text" : "dict-def-text"} lang={d.lang}>
                    {d.definition}
                  </pre>
                </div>
              ))}
            </div>
          ) : (
            <p className="hint-text">
              {detail.found
                ? "Verified headword in Telugu lexicon (no extended definition text)."
                : "No exact definition found for this word."}
            </p>
          )}

          {searchRes && searchRes.items.length > 1 && (
            <div style={{ marginTop: "0.65rem" }}>
              <strong style={{ fontSize: "0.82rem" }}>Related / Prefix Matches:</strong>
              <div className="badge-row" style={{ marginTop: "0.3rem" }}>
                {searchRes.items.slice(0, 6).map((item) => (
                  <button
                    key={item.word}
                    type="button"
                    className="btn-compact"
                    onClick={() => {
                      setQuery(item.word);
                      void lookupWord(item.word);
                    }}
                  >
                    <span lang="te">{item.word}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className="dialog-actions" style={{ marginTop: "0.85rem", justifyContent: "space-between" }}>
        <button
          type="button"
          className="btn-compact"
          onClick={() => {
            onOpenFullDictionary(query.trim() || word || "");
            onClose();
          }}
        >
          Open in Full Dictionary Tab →
        </button>
        <form method="dialog">
          <button type="submit" value="done" className="primary btn-compact">
            Back to Proofreading
          </button>
        </form>
      </div>
    </dialog>
  );
}
