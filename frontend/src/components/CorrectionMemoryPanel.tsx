import { useCallback, useEffect, useId, useState, type FormEvent } from "react";
import { listCorrections, updateCorrectionStatus } from "../api/client";
import type { CorrectionMemoryRecord } from "../types/api";

interface CorrectionMemoryPanelProps {
  selectedBookId: string | null;
  onStatusBanner: (kind: "info" | "success" | "error", text: string) => void;
}

export function CorrectionMemoryPanel({
  selectedBookId,
  onStatusBanner,
}: CorrectionMemoryPanelProps) {
  const searchId = useId();
  const statusId = useId();
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [bookOnlyFilter, setBookOnlyFilter] = useState(false);
  const [items, setItems] = useState<CorrectionMemoryRecord[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listCorrections({
        bookId: bookOnlyFilter ? selectedBookId : null,
        statusFilter,
        query: query.trim() || undefined,
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
  }, [bookOnlyFilter, onStatusBanner, query, selectedBookId, statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  function handleSearchSubmit(e: FormEvent) {
    e.preventDefault();
    void load();
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

  // Flag conflicting mappings among active entries sharing the same incorrect_text
  const activeTargetsByIncorrect = new Map<string, Set<string>>();
  for (const item of items) {
    if (item.status !== "active") continue;
    const set = activeTargetsByIncorrect.get(item.incorrect_text) ?? new Set<string>();
    set.add(item.corrected_text);
    activeTargetsByIncorrect.set(item.incorrect_text, set);
  }

  return (
    <section className="panel-card" aria-label="Correction memory manager">
      <h2>Correction Memory ({items.length})</h2>
      <p className="hint-text">
        Approved corrections appear as contextual suggestions during review and never silently rewrite
        other pages or books.
      </p>

      <search>
        <form
          onSubmit={handleSearchSubmit}
          style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "flex-end", marginBottom: "1rem" }}
        >
          <div className="form-field" style={{ marginBottom: 0, minWidth: "220px" }}>
            <label htmlFor={searchId}>Search Telugu word/phrase</label>
            <input
              id={searchId}
              name="q"
              type="search"
              lang="te"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          <div className="form-field" style={{ marginBottom: 0 }}>
            <label htmlFor={statusId}>Status</label>
            <select
              id={statusId}
              name="status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="disabled">Disabled</option>
              <option value="rejected">Rejected</option>
              <option value="superseded">Superseded</option>
            </select>
          </div>

          {selectedBookId && (
            <div className="checkbox-row" style={{ marginBlock: "0.4rem" }}>
              <input
                id="cm-book-filter"
                type="checkbox"
                checked={bookOnlyFilter}
                onChange={(e) => setBookOnlyFilter(e.target.checked)}
              />
              <label htmlFor="cm-book-filter">Selected book only</label>
            </div>
          )}

          <button type="submit" className="primary" disabled={loading}>
            {loading ? "Loading..." : "Search"}
          </button>
        </form>
      </search>

      {items.length === 0 ? (
        <p className="hint-text">No correction memory entries found yet.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", textAlign: "start" }}>
            <caption className="visually-hidden">Stored Telugu OCR correction memory records</caption>
            <thead>
              <tr style={{ borderBlockEnd: "2px solid var(--border)" }}>
                <th scope="col" style={{ padding: "0.5rem" }}>OCR Form → Corrected</th>
                <th scope="col" style={{ padding: "0.5rem" }}>Context</th>
                <th scope="col" style={{ padding: "0.5rem" }}>Scope & State</th>
                <th scope="col" style={{ padding: "0.5rem" }}>Evidence</th>
                <th scope="col" style={{ padding: "0.5rem" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const isConflict =
                  item.status === "active" &&
                  (activeTargetsByIncorrect.get(item.incorrect_text)?.size ?? 0) > 1;
                return (
                  <tr key={item.correction_id} style={{ borderBlockEnd: "1px solid var(--border)" }}>
                    <td style={{ padding: "0.55rem" }}>
                      <div className="telugu-text" lang="te">
                        <span>{item.incorrect_text}</span> → <strong>{item.corrected_text}</strong>
                      </div>
                      {item.correction_type && (
                        <span className="badge">{item.correction_type}</span>
                      )}
                    </td>
                    <td style={{ padding: "0.55rem" }}>
                      <span className="hint-text" lang="te">
                        {item.left_context || "—"} | {item.right_context || "—"}
                      </span>
                    </td>
                    <td style={{ padding: "0.55rem" }}>
                      <div className="badge-row">
                        <span className="badge">{item.scope}</span>
                        <span
                          className={`badge ${item.status === "active" ? "ok" : item.status === "rejected" ? "danger" : "warn"}`}
                        >
                          {item.status}
                        </span>
                        {isConflict && <span className="badge warn">⚠ Conflict</span>}
                      </div>
                    </td>
                    <td style={{ padding: "0.55rem" }}>
                      +{item.approved_count} / −{item.rejected_count}
                    </td>
                    <td style={{ padding: "0.55rem" }}>
                      {item.status === "active" ? (
                        <button
                          type="button"
                          onClick={() => void toggleStatus(item, "disabled")}
                        >
                          Disable
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => void toggleStatus(item, "active")}
                        >
                          Re-enable
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
