import { useCallback, useEffect, useState } from "react";
import {
  ApiClientError,
  checkTeluguText,
  createCustomDictionaryWord,
  deleteCustomDictionaryWord,
  getDictionaryStats,
  getDictionaryWord,
  listCustomDictionaryWords,
  searchDictionary,
} from "../api/client";
import type {
  CustomDictionaryWordRecord,
  DictionarySearchItem,
  DictionarySearchResponse,
  DictionaryStats,
  DictionaryTextCheckResponse,
  DictionaryWordDetail,
} from "../types/api";

function formatSourceLabel(source: string): string {
  switch (source) {
    case "cp_brown":
      return "C.P. Brown (Classical)";
    case "wiktionary_te":
      return "Telugu Wiktionary";
    case "janapada":
      return "Janapada";
    case "custom":
      return "Custom Dictionary";
    default:
      return source;
  }
}

interface DictionaryPanelProps {
  initialQuery?: string | null;
  keyboardOpen?: boolean;
  onToggleKeyboard?: () => void;
  onStatusBanner: (kind: "info" | "success" | "error", text: string) => void;
}

export function DictionaryPanel({
  initialQuery = null,
  keyboardOpen = false,
  onToggleKeyboard,
  onStatusBanner,
}: DictionaryPanelProps) {
  const [subTab, setSubTab] = useState<"search" | "spellcheck" | "custom">("search");
  const [stats, setStats] = useState<DictionaryStats | null>(null);

  // Search state
  const [query, setQuery] = useState(initialQuery ?? "");
  const [searchMode, setSearchMode] = useState<"auto" | "telugu" | "english">("auto");
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<DictionarySearchResponse | null>(null);
  const [selectedWord, setSelectedWord] = useState<DictionaryWordDetail | null>(null);
  const [loadingWord, setLoadingWord] = useState(false);

  // Spellcheck state
  const [checkInput, setCheckInput] = useState("");
  const [checkingText, setCheckingText] = useState(false);
  const [checkResult, setCheckResult] = useState<DictionaryTextCheckResponse | null>(null);

  // Custom words state
  const [customWords, setCustomWords] = useState<CustomDictionaryWordRecord[]>([]);
  const [customFilter, setCustomFilter] = useState("");
  const [newWord, setNewWord] = useState("");
  const [newTranslit, setNewTranslit] = useState("");
  const [newMeaningEn, setNewMeaningEn] = useState("");
  const [newMeaningTe, setNewMeaningTe] = useState("");
  const [newNotes, setNewNotes] = useState("");
  const [savingCustom, setSavingCustom] = useState(false);
  const [liveStatus, setLiveStatus] = useState("");

  const refreshStats = useCallback(async () => {
    try {
      const s = await getDictionaryStats();
      setStats(s);
    } catch {
      // Non-fatal
    }
  }, []);

  const refreshCustomWords = useCallback(async (q?: string) => {
    try {
      const items = await listCustomDictionaryWords(q);
      setCustomWords(items);
    } catch (err) {
      onStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to load custom words.",
      );
    }
  }, [onStatusBanner]);

  const loadWordDetail = useCallback(
    async (word: string) => {
      setLoadingWord(true);
      try {
        const detail = await getDictionaryWord(word);
        setSelectedWord(detail);
      } catch (err) {
        onStatusBanner(
          "error",
          err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to load word details.",
        );
      } finally {
        setLoadingWord(false);
      }
    },
    [onStatusBanner],
  );

  const runSearch = useCallback(
    async (rawQuery: string, modeOverride?: "auto" | "telugu" | "english") => {
      const trimmed = rawQuery.trim();
      if (!trimmed) {
        setResults(null);
        setSelectedWord(null);
        return;
      }
      setSearching(true);
      try {
        const res = await searchDictionary(trimmed, {
          mode: modeOverride ?? searchMode,
          limit: 30,
        });
        setResults(res);
        setLiveStatus(
          res.items.length > 0
            ? `Found ${res.items.length} dictionary match(es) for "${trimmed}".`
            : `No exact dictionary entries for "${trimmed}".`,
        );
        if (res.items.length > 0) {
          await loadWordDetail(res.items[0].word);
        } else {
          setSelectedWord(null);
        }
      } catch (err) {
        onStatusBanner(
          "error",
          err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Dictionary search failed.",
        );
      } finally {
        setSearching(false);
      }
    },
    [searchMode, loadWordDetail, onStatusBanner],
  );

  useEffect(() => {
    void refreshStats();
    void refreshCustomWords();
  }, [refreshStats, refreshCustomWords]);

  useEffect(() => {
    if (initialQuery && initialQuery.trim()) {
      setSubTab("search");
      setQuery(initialQuery.trim());
      void runSearch(initialQuery.trim(), "auto");
    }
  }, [initialQuery, runSearch]);

  async function handleSpellcheckSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!checkInput.trim()) return;
    setCheckingText(true);
    try {
      const res = await checkTeluguText(checkInput);
      setCheckResult(res);
      setLiveStatus(
        res.unknown_words_count === 0
          ? `All ${res.total_telugu_words} Telugu word(s) recognized in the dictionary.`
          : `Found ${res.unknown_words_count} unrecognized word(s) out of ${res.total_telugu_words}.`,
      );
    } catch (err) {
      onStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Spell check failed.",
      );
    } finally {
      setCheckingText(false);
    }
  }

  function handleApplySpellFix(token: string, replacement: string) {
    setCheckInput((prev) => prev.replace(token, replacement));
    setCheckResult((prev) =>
      prev
        ? {
            ...prev,
            known_words_count: prev.known_words_count + 1,
            unknown_words_count: Math.max(0, prev.unknown_words_count - 1),
            issues: prev.issues.filter((i) => i.token !== token),
          }
        : null,
    );
    setLiveStatus(`Replaced "${token}" with "${replacement}".`);
  }

  async function handleSaveCustomWord(e: React.FormEvent) {
    e.preventDefault();
    if (!newWord.trim()) return;
    setSavingCustom(true);
    try {
      const saved = await createCustomDictionaryWord({
        word: newWord.trim(),
        translit: newTranslit.trim() || undefined,
        meaning_en: newMeaningEn.trim() || undefined,
        meaning_te: newMeaningTe.trim() || undefined,
        notes: newNotes.trim() || undefined,
      });
      setNewWord("");
      setNewTranslit("");
      setNewMeaningEn("");
      setNewMeaningTe("");
      setNewNotes("");
      await Promise.all([refreshCustomWords(customFilter), refreshStats()]);
      onStatusBanner(
        "success",
        `Saved "${saved.word}" to Custom Telugu Dictionary (immediately available to Auto-Correct).`,
      );
    } catch (err) {
      onStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to add custom word.",
      );
    } finally {
      setSavingCustom(false);
    }
  }

  async function handleDeleteCustomWord(wordId: string, word: string) {
    try {
      await deleteCustomDictionaryWord(wordId);
      await Promise.all([refreshCustomWords(customFilter), refreshStats()]);
      if (selectedWord?.custom_word_id === wordId) {
        await loadWordDetail(word);
      }
      onStatusBanner("info", `Removed "${word}" from Custom Dictionary.`);
    } catch (err) {
      onStatusBanner(
        "error",
        err instanceof ApiClientError ? `${err.code}: ${err.message}` : "Failed to delete custom word.",
      );
    }
  }

  function jumpToAddCustomWord(prefillWord: string) {
    setNewWord(prefillWord);
    setSubTab("custom");
  }

  function renderResultItem(item: DictionarySearchItem) {
    const isSelected = selectedWord?.word === item.word;
    const previewDef = item.definitions[0]?.definition ?? "";
    return (
      <li key={item.word}>
        <button
          type="button"
          className={`dict-result-btn ${isSelected ? "selected" : ""}`.trim()}
          onClick={() => void loadWordDetail(item.word)}
        >
          <div className="badge-row" style={{ justifyContent: "space-between", width: "100%" }}>
            <strong className="telugu-text" lang="te" style={{ fontSize: "1.08rem" }}>
              {item.word}
            </strong>
            <div className="badge-row">
              {item.is_custom && <span className="badge ok">Custom</span>}
              {item.has_definition && <span className="badge">Def</span>}
            </div>
          </div>
          {item.translit && <div className="hint-text">{item.translit}</div>}
          {previewDef && (
            <div className="dict-preview-snippet">
              {previewDef.length > 110 ? `${previewDef.slice(0, 110)}…` : previewDef}
            </div>
          )}
        </button>
      </li>
    );
  }

  return (
    <section className="panel-card dict-panel" aria-label="Standalone Telugu Dictionary">
      <div className="dict-header">
        <div>
          <h2 className="card-title" style={{ margin: 0 }}>
            <span className="card-icon" aria-hidden="true">
              📚
            </span>
            Telugu Dictionary &amp; Spelling Workbench
          </h2>
          <p className="hint-text" style={{ margin: "0.25rem 0 0" }}>
            Search classical &amp; modern Telugu words (C.P. Brown, Telugu Wiktionary, Janapada, LibreOffice te_IN), look up English meanings, check spelling, or add custom vocabulary for OCR Auto-Correct.
          </p>
        </div>
        {stats && (
          <div className="badge-row" aria-label="Dictionary corpus statistics">
            <span className="badge ok">{stats.total_words.toLocaleString()} Telugu words</span>
            {stats.words_with_definitions > 0 && (
              <span className="badge">
                {stats.words_with_definitions.toLocaleString()} with definitions
              </span>
            )}
            <span className="badge">{stats.custom_words_count} custom</span>
          </div>
        )}
      </div>

      <div className="badge-row dict-subnav" role="group" aria-label="Dictionary modes">
        <button
          type="button"
          className={`btn-compact ${subTab === "search" ? "primary" : ""}`.trim()}
          aria-pressed={subTab === "search"}
          onClick={() => setSubTab("search")}
        >
          🔍 Search Dictionary
        </button>
        <button
          type="button"
          className={`btn-compact ${subTab === "spellcheck" ? "primary" : ""}`.trim()}
          aria-pressed={subTab === "spellcheck"}
          onClick={() => setSubTab("spellcheck")}
        >
          ✓ Check Telugu Text
        </button>
        <button
          type="button"
          className={`btn-compact ${subTab === "custom" ? "primary" : ""}`.trim()}
          aria-pressed={subTab === "custom"}
          onClick={() => setSubTab("custom")}
        >
          ⭐ Custom Words ({stats?.custom_words_count ?? customWords.length})
        </button>
      </div>

      <p className="visually-hidden" role="status" aria-live="polite">
        {liveStatus}
      </p>

      {subTab === "search" && (
        <div className="dict-section">
          <search>
            <form
              className="dict-search-bar"
              onSubmit={(e) => {
                e.preventDefault();
                void runSearch(query);
              }}
            >
              <label htmlFor="dict-search-input" className="visually-hidden">
                Search Telugu word, English meaning, or phonetic transliteration
              </label>
              <input
                id="dict-search-input"
                type="search"
                lang="te"
                className="dict-search-input"
                placeholder="Type Telugu (పుస్తకము, వర్ణన) or English (book, lotus)…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <label htmlFor="dict-mode-select" className="visually-hidden">
                Search mode
              </label>
              <select
                id="dict-mode-select"
                className="toolbar-select"
                value={searchMode}
                onChange={(e) => setSearchMode(e.target.value as "auto" | "telugu" | "english")}
              >
                <option value="auto">Auto (Telugu / English)</option>
                <option value="telugu">Telugu → Meaning</option>
                <option value="english">English / Phonetic → Telugu</option>
              </select>
              <button type="submit" className="primary btn-compact" disabled={searching || !query.trim()}>
                {searching ? "Searching…" : "Search"}
              </button>
              {onToggleKeyboard && (
                <button
                  type="button"
                  className="btn-compact"
                  aria-pressed={keyboardOpen}
                  onClick={onToggleKeyboard}
                >
                  ⌨ Keyboard
                </button>
              )}
            </form>
          </search>

          {!results && (
            <div className="dict-examples">
              <span className="hint-text">Try quick lookups:</span>
              {["ఆముక్తమాల్యద", "పుస్తకము", "వర్ణన", "lotus", "poetry", "అష్టాదశవర్ధనలు"].map((ex) => (
                <button
                  key={ex}
                  type="button"
                  className="btn-compact"
                  onClick={() => {
                    setQuery(ex);
                    void runSearch(ex, "auto");
                  }}
                >
                  <span lang={/[\u0C00-\u0C7F]/.test(ex) ? "te" : "en"}>{ex}</span>
                </button>
              ))}
            </div>
          )}

          {results && results.did_you_mean.length > 0 && (
            <div className="autocorrect-preview-box" role="region" aria-label="Spelling suggestions">
              <strong style={{ fontSize: "0.84rem" }}>
                Did you mean (Telugu spelling / OCR suggestions)?
              </strong>
              <div className="badge-row">
                {results.did_you_mean.map((sug) => (
                  <button
                    key={sug.word}
                    type="button"
                    className="btn-compact"
                    title={sug.reason}
                    onClick={() => {
                      setQuery(sug.word);
                      void runSearch(sug.word, "telugu");
                    }}
                  >
                    <span className="telugu-text" lang="te">
                      {sug.word}
                    </span>{" "}
                    <span className="hint-text">({Math.round(sug.confidence * 100)}%)</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {results && (
            <div className="dict-layout">
              <div className="dict-results-col">
                <div className="badge-row" style={{ justifyContent: "space-between", marginBottom: "0.4rem" }}>
                  <strong style={{ fontSize: "0.88rem" }}>
                    Matches ({results.items.length})
                  </strong>
                  <span className="hint-text">Mode: {results.detected_mode}</span>
                </div>
                {results.items.length === 0 ? (
                  <div className="panel-card">
                    <p style={{ marginTop: 0 }}>
                      No dictionary entries matched <strong>{results.query}</strong>.
                    </p>
                    {/[\u0C00-\u0C7F]/.test(results.query) && (
                      <button
                        type="button"
                        className="primary btn-compact"
                        onClick={() => jumpToAddCustomWord(results.query)}
                      >
                        ＋ Add “{results.query}” to Custom Dictionary
                      </button>
                    )}
                  </div>
                ) : (
                  <ul className="dict-result-list">{results.items.map(renderResultItem)}</ul>
                )}
              </div>

              <div className="dict-detail-col">
                {loadingWord ? (
                  <div className="panel-card">Loading entry…</div>
                ) : selectedWord ? (
                  <article className="panel-card dict-detail-card">
                    <div className="badge-row" style={{ justifyContent: "space-between" }}>
                      <div>
                        <h3 className="telugu-text" lang="te" style={{ margin: 0, fontSize: "1.55rem" }}>
                          {selectedWord.word}
                        </h3>
                        {selectedWord.translit && (
                          <div className="hint-text" style={{ marginTop: "0.15rem" }}>
                            Transliteration: {selectedWord.translit}
                          </div>
                        )}
                      </div>
                      <div className="badge-row">
                        <span className={selectedWord.is_valid_word ? "badge ok" : "badge warn"}>
                          {selectedWord.is_valid_word ? "✓ Valid Telugu Word" : "Unlisted"}
                        </span>
                        {!selectedWord.is_custom && (
                          <button
                            type="button"
                            className="btn-compact"
                            onClick={() => jumpToAddCustomWord(selectedWord.word)}
                          >
                            ＋ Add Note / Custom
                          </button>
                        )}
                      </div>
                    </div>

                    {selectedWord.sources.length > 0 && (
                      <div className="badge-row">
                        {selectedWord.sources.map((src) => (
                          <span key={src} className="badge">
                            {src}
                          </span>
                        ))}
                      </div>
                    )}

                    {selectedWord.definitions.length > 0 ? (
                      <div className="dict-defs-list">
                        {selectedWord.definitions.map((def, idx) => (
                          <div key={`${def.source}-${idx}`} className="dict-def-block">
                            <div className="badge-row" style={{ marginBottom: "0.3rem" }}>
                              <span className="badge dict-source-tag">
                                {formatSourceLabel(def.source)}
                              </span>
                              <span className="hint-text">
                                {def.lang === "en" ? "English" : "తెలుగు"}
                              </span>
                            </div>
                            <pre
                              className={def.lang === "te" ? "telugu-text dict-def-text" : "dict-def-text"}
                              lang={def.lang}
                            >
                              {def.definition}
                            </pre>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="hint-text">
                        Verified headword in the Telugu lexicon (no extended definition text in C.P. Brown / Wiktionary). You can add your own English or Telugu meaning via Custom Words.
                      </p>
                    )}
                  </article>
                ) : (
                  <div className="panel-card hint-text">
                    Select a word from the list to inspect its full C.P. Brown, Janapada, and Telugu Wiktionary definitions.
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {subTab === "spellcheck" && (
        <div className="dict-section">
          <form onSubmit={(e) => void handleSpellcheckSubmit(e)}>
            <label htmlFor="dict-spellcheck-input" style={{ display: "block", fontWeight: 600, marginBottom: "0.35rem" }}>
              Paste or type Telugu text to check against the 195k+ Telugu dictionary
            </label>
            <textarea
              id="dict-spellcheck-input"
              lang="te"
              className="block-textarea"
              rows={5}
              placeholder="ఉదా: అష్టాదశవర్ధనలు తెలుగు పస్తకం ఆముక్తమాల్యద"
              value={checkInput}
              onChange={(e) => setCheckInput(e.target.value)}
            />
            <div className="badge-row" style={{ marginTop: "0.5rem" }}>
              <button type="submit" className="primary btn-compact" disabled={checkingText || !checkInput.trim()}>
                {checkingText ? "Checking…" : "✓ Check Spelling"}
              </button>
              <button
                type="button"
                className="btn-compact"
                onClick={() => {
                  setCheckInput("");
                  setCheckResult(null);
                }}
              >
                Clear
              </button>
            </div>
          </form>

          {checkResult && (
            <div className="panel-card" style={{ marginTop: "0.75rem" }}>
              <div className="badge-row" style={{ marginBottom: "0.5rem" }}>
                <span className="badge">Total Telugu words: {checkResult.total_telugu_words}</span>
                <span className="badge ok">Known: {checkResult.known_words_count}</span>
                <span className={checkResult.unknown_words_count > 0 ? "badge warn" : "badge ok"}>
                  Flagged: {checkResult.unknown_words_count}
                </span>
              </div>

              {checkResult.issues.length === 0 ? (
                <p style={{ margin: 0 }}>
                  <strong>All Telugu words look valid!</strong>
                </p>
              ) : (
                <ul className="dict-issues-list">
                  {checkResult.issues.map((issue, idx) => (
                    <li key={`${issue.token}-${idx}`} className="dict-issue-item">
                      <div>
                        <strong className="telugu-text" lang="te">
                          {issue.token}
                        </strong>{" "}
                        <span className="hint-text">— {issue.reason}</span>
                      </div>
                      <div className="badge-row">
                        {issue.suggestions.map((sug) => (
                          <button
                            key={sug}
                            type="button"
                            className="btn-compact primary"
                            onClick={() => handleApplySpellFix(issue.token, sug)}
                          >
                            → <span lang="te">{sug}</span>
                          </button>
                        ))}
                        <button
                          type="button"
                          className="btn-compact"
                          onClick={() => jumpToAddCustomWord(issue.token)}
                        >
                          ＋ Add as Valid Word
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {subTab === "custom" && (
        <div className="dict-section dict-custom-grid">
          <form className="panel-card dict-custom-form" onSubmit={(e) => void handleSaveCustomWord(e)}>
            <h3 style={{ marginTop: 0, fontSize: "1rem" }}>Add Custom Telugu Word</h3>
            <p className="hint-text" style={{ marginTop: 0 }}>
              Saved to PostgreSQL (backed up every 4 hours) and automatically recognized by{" "}
              <strong>Auto-Correct Page</strong>.
            </p>
            <div className="dict-field">
              <label htmlFor="custom-word-te">Telugu Word *</label>
              <input
                id="custom-word-te"
                type="text"
                lang="te"
                required
                placeholder="ఉదా: ఆముక్తమాల్యద"
                value={newWord}
                onChange={(e) => setNewWord(e.target.value)}
              />
            </div>
            <div className="dict-field">
              <label htmlFor="custom-word-translit">Transliteration (optional)</label>
              <input
                id="custom-word-translit"
                type="text"
                placeholder="e.g., amuktamalyada"
                value={newTranslit}
                onChange={(e) => setNewTranslit(e.target.value)}
              />
            </div>
            <div className="dict-field">
              <label htmlFor="custom-word-en">English Meaning (optional)</label>
              <textarea
                id="custom-word-en"
                rows={2}
                placeholder="Classical Telugu epic poem by Sri Krishnadevaraya"
                value={newMeaningEn}
                onChange={(e) => setNewMeaningEn(e.target.value)}
              />
            </div>
            <div className="dict-field">
              <label htmlFor="custom-word-te-def">Telugu Meaning / Notes (optional)</label>
              <textarea
                id="custom-word-te-def"
                lang="te"
                rows={2}
                placeholder="శ్రీకృష్ణదేవరాయలు రచించిన ప్రబంధము"
                value={newMeaningTe}
                onChange={(e) => setNewMeaningTe(e.target.value)}
              />
            </div>
            <div className="dict-field">
              <label htmlFor="custom-word-notes">Book / Usage Reference (optional)</label>
              <input
                id="custom-word-notes"
                type="text"
                placeholder="e.g., Amuktamalyada Vol. 1"
                value={newNotes}
                onChange={(e) => setNewNotes(e.target.value)}
              />
            </div>
            <button type="submit" className="primary" disabled={savingCustom || !newWord.trim()}>
              {savingCustom ? "Saving…" : "Save Custom Word"}
            </button>
          </form>

          <div className="panel-card">
            <div className="badge-row" style={{ justifyContent: "space-between", marginBottom: "0.5rem" }}>
              <h3 style={{ margin: 0, fontSize: "1rem" }}>
                Your Custom Words ({customWords.length})
              </h3>
              <input
                type="search"
                aria-label="Filter custom Telugu words"
                placeholder="Filter custom words…"
                className="editor-search-input"
                value={customFilter}
                onChange={(e) => {
                  setCustomFilter(e.target.value);
                  void refreshCustomWords(e.target.value);
                }}
              />
            </div>
            {customWords.length === 0 ? (
              <p className="hint-text">
                No custom Telugu words saved yet. Add rare literary words, author names, or regional vocabulary on the left.
              </p>
            ) : (
              <ul className="dict-custom-list">
                {customWords.map((cw) => (
                  <li key={cw.word_id} className="dict-custom-item">
                    <div>
                      <strong className="telugu-text" lang="te" style={{ fontSize: "1.1rem" }}>
                        {cw.word}
                      </strong>
                      {cw.translit && <span className="hint-text"> ({cw.translit})</span>}
                      {cw.meaning_en && <div style={{ fontSize: "0.88rem" }}>{cw.meaning_en}</div>}
                      {cw.meaning_te && (
                        <div className="telugu-text" lang="te" style={{ fontSize: "0.9rem" }}>
                          {cw.meaning_te}
                        </div>
                      )}
                      {cw.notes && <div className="hint-text">{cw.notes}</div>}
                    </div>
                    <div className="badge-row">
                      <button
                        type="button"
                        className="btn-compact"
                        onClick={() => {
                          setSubTab("search");
                          setQuery(cw.word);
                          void runSearch(cw.word, "telugu");
                        }}
                      >
                        Look Up
                      </button>
                      <button
                        type="button"
                        className="btn-compact"
                        onClick={() => void handleDeleteCustomWord(cw.word_id, cw.word)}
                      >
                        Delete
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
