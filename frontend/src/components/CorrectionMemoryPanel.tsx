import { useCallback, useEffect, useId, useState, type FormEvent } from "react";
import {
  deleteCorrectionEntry,
  listCorrectionsWithMeta,
  updateCorrectionEntry,
  updateCorrectionStatus,
} from "../api/client";
import type { CorrectionMemoryRecord } from "../types/api";
import { formatCorrectionScope, formatCorrectionType, formatUnitType } from "../utils/formatters";

interface CorrectionMemoryPanelProps {
  selectedBookId: string | null;
  onStatusBanner: (kind: "info" | "success" | "error", text: string) => void;
}

const PAGE_SIZE = 50;

function formatShortDate(iso: string | null | undefined): string {
  if (!iso) return "Never";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "—";
  return dt.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function CorrectionMemoryPanel({
  selectedBookId,
  onStatusBanner,
}: CorrectionMemoryPanelProps) {
  const searchId = useId();
  const statusId = useId();
  const scopeId = useId();
  const unitId = useId();
  const captionId = useId();

  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [scopeFilter, setScopeFilter] = useState("all");
  const [unitFilter, setUnitFilter] = useState("all");
  const [conflictOnly, setConflictOnly] = useState(false);
  const [bookOnlyFilter, setBookOnlyFilter] = useState(false);
  const [offset, setOffset] = useState(0);

  const [items, setItems] = useState<CorrectionMemoryRecord[]>([]);
  const [totalCount, setTotalCount] = useState(0);
  const [globalCount, setGlobalCount] = useState(0);
  const [bookSpecificCount, setBookSpecificCount] = useState(0);
  const [conflictsCount, setConflictsCount] = useState(0);
  const [loading, setLoading] = useState(false);

  // Inline edit state
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editCorrected, setEditCorrected] = useState("");
  const [editScope, setEditScope] = useState<"global_suggestion" | "book_only">("global_suggestion");
  const [editLeftCtx, setEditLeftCtx] = useState("");
  const [editRightCtx, setEditRightCtx] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
      setOffset(0);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  const load = useCallback(
    async (explicitQuery?: string, offsetOverride?: number) => {
      setLoading(true);
      const effectiveQuery = explicitQuery !== undefined ? explicitQuery.trim() : debouncedQuery;
      const effectiveOffset = offsetOverride !== undefined ? offsetOverride : offset;
      try {
        const data = await listCorrectionsWithMeta({
          bookId: bookOnlyFilter ? selectedBookId : null,
          statusFilter,
          scopeFilter,
          unitType: unitFilter,
          conflictOnly,
          query: effectiveQuery || undefined,
          limit: PAGE_SIZE,
          offset: effectiveOffset,
        });
        setItems(data.items);
        setTotalCount(data.total_count);
        setGlobalCount(data.global_count);
        setBookSpecificCount(data.book_specific_count);
        setConflictsCount(data.conflicts_count);
      } catch (err) {
        onStatusBanner(
          "error",
          err instanceof Error ? err.message : "Failed to load correction memory.",
        );
      } finally {
        setLoading(false);
      }
    },
    [
      bookOnlyFilter,
      conflictOnly,
      debouncedQuery,
      offset,
      onStatusBanner,
      scopeFilter,
      selectedBookId,
      statusFilter,
      unitFilter,
    ],
  );

  useEffect(() => {
    void load();
  }, [load]);

  function handleSearchSubmit(e: FormEvent) {
    e.preventDefault();
    setDebouncedQuery(query.trim());
    setOffset(0);
    void load(query, 0);
  }

  async function toggleStatus(
    record: CorrectionMemoryRecord,
    nextStatus: "active" | "disabled",
  ) {
    try {
      await updateCorrectionStatus(record.correction_id, nextStatus);
      onStatusBanner("success", `Correction marked "${nextStatus}".`);
      await load();
    } catch (err) {
      onStatusBanner("error", err instanceof Error ? err.message : "Status update failed.");
    }
  }

  async function toggleScope(
    record: CorrectionMemoryRecord,
    nextScope: "global_suggestion" | "book_only",
  ) {
    try {
      await updateCorrectionStatus(record.correction_id, record.status, nextScope);
      onStatusBanner(
        "success",
        nextScope === "global_suggestion"
          ? "Promoted correction rule to Global."
          : "Scoped correction rule to This Book only.",
      );
      await load();
    } catch (err) {
      onStatusBanner("error", err instanceof Error ? err.message : "Failed to change scope.");
    }
  }

  function startEditing(record: CorrectionMemoryRecord) {
    setEditingId(record.correction_id);
    setEditCorrected(record.corrected_text);
    setEditScope(record.scope);
    setEditLeftCtx(record.left_context ?? "");
    setEditRightCtx(record.right_context ?? "");
  }

  async function handleSaveEdit(record: CorrectionMemoryRecord) {
    if (!editCorrected.trim()) {
      onStatusBanner("error", "Corrected Telugu text cannot be empty.");
      return;
    }
    setSavingEdit(true);
    try {
      await updateCorrectionEntry(record.correction_id, {
        corrected_text: editCorrected.trim(),
        scope: editScope,
        left_context: editLeftCtx.trim(),
        right_context: editRightCtx.trim(),
        clear_context: !editLeftCtx.trim() && !editRightCtx.trim(),
      });
      setEditingId(null);
      onStatusBanner("success", "Updated correction memory entry.");
      await load();
    } catch (err) {
      onStatusBanner("error", err instanceof Error ? err.message : "Failed to update correction.");
    } finally {
      setSavingEdit(false);
    }
  }

  async function handleDelete(record: CorrectionMemoryRecord) {
    const confirmed = window.confirm(
      `Remove correction "${record.incorrect_text} → ${record.corrected_text}" from Correction Memory?`,
    );
    if (!confirmed) return;
    try {
      await deleteCorrectionEntry(record.correction_id);
      onStatusBanner("success", "Removed correction memory entry.");
      await load();
    } catch (err) {
      onStatusBanner("error", err instanceof Error ? err.message : "Failed to remove correction.");
    }
  }

  const activeTargetsByIncorrect = new Map<string, Set<string>>();
  for (const item of items) {
    if (item.status !== "active") continue;
    const key = item.normalized_incorrect || item.incorrect_text;
    const set = activeTargetsByIncorrect.get(key) ?? new Set<string>();
    set.add(item.corrected_text);
    activeTargetsByIncorrect.set(key, set);
  }

  return (
    <section className="panel-card centered-stage-card" aria-label="Correction memory manager">
      <div className="section-head-row cm-header-row">
        <div>
          <h2 className="card-title" style={{ margin: 0 }}>
            <span className="card-icon" aria-hidden="true">
              🧠
            </span>
            Correction Memory ({totalCount}
            {totalCount > items.length
              ? ` · showing ${offset + 1}–${offset + items.length}`
              : ""}
            )
          </h2>
          <p className="hint-text" style={{ margin: "0.2rem 0 0" }}>
            Word-level Telugu OCR corrections learned from your reviews and calibration batches.
            Book-specific rules take precedence within their book; conflicting rules require
            matching context before applying.
          </p>
        </div>
        <div className="badge-row cm-summary-badges">
          <button
            type="button"
            className={`badge cm-filter-chip${scopeFilter === "global_suggestion" ? " active" : ""}`}
            onClick={() => {
              setScopeFilter((prev) => (prev === "global_suggestion" ? "all" : "global_suggestion"));
              setOffset(0);
            }}
          >
            🌐 Global: {globalCount}
          </button>
          <button
            type="button"
            className={`badge cm-filter-chip${scopeFilter === "book_only" ? " active" : ""}`}
            onClick={() => {
              setScopeFilter((prev) => (prev === "book_only" ? "all" : "book_only"));
              setOffset(0);
            }}
          >
            📘 Book-Specific: {bookSpecificCount}
          </button>
          {conflictsCount > 0 && (
            <button
              type="button"
              className={`badge warn cm-filter-chip${conflictOnly ? " active" : ""}`}
              onClick={() => {
                setConflictOnly((v) => !v);
                setOffset(0);
              }}
            >
              ⚠ {conflictsCount} Conflict{conflictsCount === 1 ? "" : "s"}
            </button>
          )}
        </div>
      </div>

      <search>
        <form onSubmit={handleSearchSubmit} className="filter-bar-form cm-filter-form">
          <div className="form-field filter-bar-search">
            <label htmlFor={searchId}>Search Telugu word/phrase</label>
            <input
              id={searchId}
              name="q"
              type="search"
              lang="te"
              placeholder="Search OCR word, corrected Telugu, or context…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <div className="form-field">
            <label htmlFor={scopeId}>Scope</label>
            <select
              id={scopeId}
              name="scope"
              value={scopeFilter}
              onChange={(e) => {
                setScopeFilter(e.target.value);
                setOffset(0);
              }}
            >
              <option value="all">All scopes</option>
              <option value="global_suggestion">🌐 Global only</option>
              <option value="book_only">📘 Book-specific only</option>
            </select>
          </div>

          <div className="form-field">
            <label htmlFor={statusId}>Status</label>
            <select
              id={statusId}
              name="status"
              value={statusFilter}
              onChange={(e) => {
                setStatusFilter(e.target.value);
                setOffset(0);
              }}
            >
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="disabled">Disabled</option>
              <option value="rejected">Rejected</option>
              <option value="superseded">Superseded</option>
            </select>
          </div>

          <div className="form-field">
            <label htmlFor={unitId}>Unit</label>
            <select
              id={unitId}
              name="unit_type"
              value={unitFilter}
              onChange={(e) => {
                setUnitFilter(e.target.value);
                setOffset(0);
              }}
            >
              <option value="all">All units</option>
              <option value="word">Word</option>
              <option value="char_pattern">Char pattern</option>
              <option value="phrase">Phrase</option>
            </select>
          </div>

          <div className="cm-filter-checks">
            {selectedBookId && (
              <div className="checkbox-row">
                <input
                  id="cm-book-filter"
                  type="checkbox"
                  checked={bookOnlyFilter}
                  onChange={(e) => {
                    setBookOnlyFilter(e.target.checked);
                    setOffset(0);
                  }}
                />
                <label htmlFor="cm-book-filter">Selected book only</label>
              </div>
            )}
            <div className="checkbox-row">
              <input
                id="cm-conflict-filter"
                type="checkbox"
                checked={conflictOnly}
                onChange={(e) => {
                  setConflictOnly(e.target.checked);
                  setOffset(0);
                }}
              />
              <label htmlFor="cm-conflict-filter">Conflicts only</label>
            </div>
          </div>

          <button type="submit" className="primary" disabled={loading}>
            {loading ? "Loading…" : "Search"}
          </button>
        </form>
      </search>

      {items.length === 0 ? (
        <p className="hint-text">No correction memory entries found for this filter.</p>
      ) : (
        <>
          <div tabIndex={0} role="region" aria-labelledby={captionId} className="table-wrapper">
            <table className="cm-table">
              <caption id={captionId} className="visually-hidden">
                Stored Telugu OCR correction memory records
              </caption>
              <thead>
                <tr>
                  <th scope="col">OCR Word → Corrected</th>
                  <th scope="col">Context</th>
                  <th scope="col">Scope &amp; Reliability</th>
                  <th scope="col">Evidence</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const normKey = item.normalized_incorrect || item.incorrect_text;
                  const isConflict =
                    Boolean(item.has_conflict) ||
                    (item.status === "active" &&
                      (activeTargetsByIncorrect.get(normKey)?.size ?? 0) > 1);
                  const reliabilityPct = Math.round((item.reliability_score ?? 0.75) * 100);
                  const isLowConfidence = reliabilityPct < 65 || item.rejected_count > 0;
                  const hasContext = Boolean(item.left_context || item.right_context);
                  const isEditing = editingId === item.correction_id;

                  return (
                    <tr
                      key={item.correction_id}
                      className={isConflict ? "cm-row-conflict" : isLowConfidence ? "cm-row-lowconf" : undefined}
                    >
                      <th scope="row">
                        {isEditing ? (
                          <div className="cm-inline-edit-box">
                            <div className="telugu-text hint-text" lang="te">
                              OCR: <span>{item.incorrect_text}</span>
                            </div>
                            <label className="form-field">
                              <span className="hint-text">Corrected Telugu</span>
                              <input
                                type="text"
                                lang="te"
                                value={editCorrected}
                                onChange={(e) => setEditCorrected(e.target.value)}
                              />
                            </label>
                            <div className="cm-inline-ctx-grid">
                              <input
                                type="text"
                                lang="te"
                                aria-label="Left context"
                                placeholder="Left context (optional)"
                                value={editLeftCtx}
                                onChange={(e) => setEditLeftCtx(e.target.value)}
                              />
                              <input
                                type="text"
                                lang="te"
                                aria-label="Right context"
                                placeholder="Right context (optional)"
                                value={editRightCtx}
                                onChange={(e) => setEditRightCtx(e.target.value)}
                              />
                            </div>
                            <div className="badge-row">
                              <select
                                aria-label="Edit scope"
                                className="toolbar-select"
                                value={editScope}
                                onChange={(e) =>
                                  setEditScope(e.target.value as "global_suggestion" | "book_only")
                                }
                              >
                                <option value="global_suggestion">🌐 Global</option>
                                {item.book_id && <option value="book_only">📘 This Book</option>}
                              </select>
                              <button
                                type="button"
                                className="primary btn-compact"
                                disabled={savingEdit}
                                onClick={() => void handleSaveEdit(item)}
                              >
                                {savingEdit ? "Saving…" : "Save"}
                              </button>
                              <button
                                type="button"
                                className="btn-compact"
                                disabled={savingEdit}
                                onClick={() => setEditingId(null)}
                              >
                                Cancel
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <div className="telugu-text cm-word-pair" lang="te">
                              <span className="cm-ocr-wrong">{item.incorrect_text}</span>
                              <span className="cm-arrow" aria-hidden="true">
                                {" "}
                                →{" "}
                              </span>
                              <strong className="cm-ocr-right">{item.corrected_text}</strong>
                            </div>
                            <div className="badge-row" style={{ marginTop: "0.22rem" }}>
                              <span className="badge cm-unit-badge">
                                {formatUnitType(item.unit_type)}
                              </span>
                              {item.correction_type && (
                                <span className="badge">
                                  {formatCorrectionType(item.correction_type)}
                                </span>
                              )}
                            </div>
                          </>
                        )}
                      </th>
                      <td>
                        {hasContext ? (
                          <div className="cm-context-snippet" lang="te">
                            {item.left_context && (
                              <span className="hint-text">{item.left_context} </span>
                            )}
                            <span className="cm-context-slot">[word]</span>
                            {item.right_context && (
                              <span className="hint-text"> {item.right_context}</span>
                            )}
                          </div>
                        ) : (
                          <span className="hint-text">General (any context)</span>
                        )}
                      </td>
                      <td>
                        <div className="badge-row">
                          <span
                            className={`badge ${
                              item.scope === "global_suggestion"
                                ? "cm-scope-global"
                                : "cm-scope-book"
                            }`}
                          >
                            {item.scope === "global_suggestion" ? "🌐 " : "📘 "}
                            {formatCorrectionScope(item.scope)}
                          </span>
                          <span
                            className={`badge ${
                              item.status === "active"
                                ? "ok"
                                : item.status === "rejected"
                                  ? "danger"
                                  : "warn"
                            }`}
                          >
                            {item.status}
                          </span>
                          <span
                            className={`badge ${isLowConfidence ? "warn" : "ok"}`}
                            title="Reliability score derived from approvals, rejections, and conflicts"
                          >
                            {reliabilityPct}%{isLowConfidence ? " · Low" : ""}
                          </span>
                          {isConflict && (
                            <span
                              className="badge warn"
                              title="Multiple active corrections exist for this OCR word; context is required to disambiguate"
                            >
                              ⚠ Conflict
                              {item.conflict_count && item.conflict_count > 1
                                ? ` (${item.conflict_count})`
                                : ""}
                            </span>
                          )}
                        </div>
                      </td>
                      <td>
                        <details className="cm-evidence-details">
                          <summary className="cm-evidence-summary">
                            <strong>+{item.approved_count}</strong> / −{item.rejected_count}
                            {item.source_page_number ? ` · p.${item.source_page_number}` : ""}
                          </summary>
                          <div className="cm-evidence-body hint-text">
                            {item.source_book_title && (
                              <div>
                                Book: <span lang="te">{item.source_book_title}</span>
                              </div>
                            )}
                            {item.source_page_number && (
                              <div>Source PDF page: {item.source_page_number}</div>
                            )}
                            <div>Created: {formatShortDate(item.created_at)}</div>
                            <div>Last used: {formatShortDate(item.last_used_at)}</div>
                          </div>
                        </details>
                      </td>
                      <td>
                        <div className="badge-row">
                          {item.status === "active" ? (
                            <button
                              type="button"
                              className="btn-compact"
                              onClick={() => void toggleStatus(item, "disabled")}
                            >
                              Disable
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="btn-compact"
                              onClick={() => void toggleStatus(item, "active")}
                            >
                              Re-enable
                            </button>
                          )}
                          <button
                            type="button"
                            className="btn-compact"
                            onClick={() => startEditing(item)}
                          >
                            Edit
                          </button>
                          {item.scope === "book_only" ? (
                            <button
                              type="button"
                              className="btn-compact"
                              onClick={() => void toggleScope(item, "global_suggestion")}
                            >
                              Promote to Global
                            </button>
                          ) : (
                            item.book_id && (
                              <button
                                type="button"
                                className="btn-compact"
                                onClick={() => void toggleScope(item, "book_only")}
                              >
                                Book Only
                              </button>
                            )
                          )}
                          <button
                            type="button"
                            className="btn-compact danger"
                            onClick={() => void handleDelete(item)}
                          >
                            Remove
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {(offset > 0 || offset + items.length < totalCount) && (
            <div className="pagination-row">
              <button
                type="button"
                className="btn-compact"
                disabled={offset === 0 || loading}
                onClick={() => setOffset((prev) => Math.max(0, prev - PAGE_SIZE))}
              >
                ← Previous {PAGE_SIZE}
              </button>
              <span className="hint-text">
                Showing {offset + 1}–{offset + items.length} of {totalCount}
              </span>
              <button
                type="button"
                className="btn-compact"
                disabled={offset + items.length >= totalCount || loading}
                onClick={() => setOffset((prev) => prev + PAGE_SIZE)}
              >
                Next {PAGE_SIZE} →
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
