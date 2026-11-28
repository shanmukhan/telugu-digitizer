import { useCallback, useEffect, useId, useState, type FormEvent } from "react";
import { listCorrections, updateCorrectionStatus } from "../api/client";
import type { CorrectionMemoryRecord } from "../types/api";
import { formatCorrectionScope, formatCorrectionType } from "../utils/formatters";

interface CorrectionMemoryPanelProps {
  selectedBookId: string | null;
  onStatusBanner: (kind: "info" | "success" | "error", text: string) => void;
}

const PAGE_SIZE = 50;

export function CorrectionMemoryPanel({
  selectedBookId,
  onStatusBanner,
}: CorrectionMemoryPanelProps) {
  const searchId = useId();
  const statusId = useId();
  const captionId = useId();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [bookOnlyFilter, setBookOnlyFilter] = useState(false);
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<CorrectionMemoryRecord[]>([]);
  const [loading, setLoading] = useState(false);

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
        const data = await listCorrections({
          bookId: bookOnlyFilter ? selectedBookId : null,
          statusFilter,
          query: effectiveQuery || undefined,
          limit: PAGE_SIZE,
          offset: effectiveOffset,
        });
        setItems(data);
      } catch (err) {
        onStatusBanner(
          "error",
          err instanceof Error ? err.message : "Failed to load correction memory.",
        );
      } finally {
        setLoading(false);
      }
    },
    [bookOnlyFilter, debouncedQuery, offset, onStatusBanner, selectedBookId, statusFilter],
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

  async function promoteToGlobal(record: CorrectionMemoryRecord) {
    try {
      await updateCorrectionStatus(record.correction_id, record.status, "global_suggestion");
      onStatusBanner("success", "Promoted correction rule to global suggestion.");
      await load();
    } catch (err) {
      onStatusBanner("error", err instanceof Error ? err.message : "Failed to promote correction.");
    }
  }

  const activeTargetsByIncorrect = new Map<string, Set<string>>();
  for (const item of items) {
    if (item.status !== "active") continue;
    const set = activeTargetsByIncorrect.get(item.incorrect_text) ?? new Set<string>();
    set.add(item.corrected_text);
    activeTargetsByIncorrect.set(item.incorrect_text, set);
  }

  return (
    <section className="panel-card centered-stage-card" aria-label="Correction memory manager">
      <div className="section-head-row">
        <div>
          <h2 className="card-title" style={{ margin: 0 }}>
            <span className="card-icon" aria-hidden="true">
              🧠
            </span>
            Correction Memory ({items.length}
            {offset > 0 ? ` · showing ${offset + 1}–${offset + items.length}` : ""})
          </h2>
          <p className="hint-text" style={{ margin: "0.2rem 0 0" }}>
            Approved corrections appear as contextual suggestions during review and never silently rewrite other pages or books.
          </p>
        </div>
      </div>

      <search>
        <form onSubmit={handleSearchSubmit} className="filter-bar-form">
          <div className="form-field filter-bar-search">
            <label htmlFor={searchId}>Search Telugu word/phrase</label>
            <input
              id={searchId}
              name="q"
              type="search"
              lang="te"
              placeholder="Search incorrect or corrected Telugu…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
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
                  <th scope="col">OCR Form → Corrected</th>
                  <th scope="col">Context</th>
                  <th scope="col">Scope &amp; State</th>
                  <th scope="col">Evidence</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => {
                  const isConflict =
                    item.status === "active" &&
                    (activeTargetsByIncorrect.get(item.incorrect_text)?.size ?? 0) > 1;
                  return (
                    <tr key={item.correction_id}>
                      <th scope="row">
                        <div className="telugu-text" lang="te">
                          <span>{item.incorrect_text}</span> → <strong>{item.corrected_text}</strong>
                        </div>
                        {item.correction_type && (
                          <span className="badge">{formatCorrectionType(item.correction_type)}</span>
                        )}
                      </th>
                      <td>
                        <span className="hint-text" lang="te">
                          {item.left_context || "—"} | {item.right_context || "—"}
                        </span>
                      </td>
                      <td>
                        <div className="badge-row">
                          <span className="badge">{formatCorrectionScope(item.scope)}</span>
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
                          {isConflict && <span className="badge warn">⚠ Conflict</span>}
                        </div>
                      </td>
                      <td>
                        +{item.approved_count} / −{item.rejected_count}
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
                          {item.scope === "book_only" && (
                            <button
                              type="button"
                              className="btn-compact"
                              onClick={() => void promoteToGlobal(item)}
                            >
                              Promote to Global
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {(offset > 0 || items.length === PAGE_SIZE) && (
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
                Showing {offset + 1}–{offset + items.length}
              </span>
              <button
                type="button"
                className="btn-compact"
                disabled={items.length < PAGE_SIZE || loading}
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
