import { useEffect, useId, useRef, useState } from "react";
import type { BookOCRRunSummary, BookSummary } from "../types/api";
import { buildRunTelemetry, formatEngineLabel } from "../utils/formatters";

export type WorkspaceView = "review" | "dictionary" | "memory" | "export";

interface TopNavBarProps {
  books: BookSummary[];
  selectedBook: BookSummary | null;
  runs: BookOCRRunSummary[];
  activeView: WorkspaceView;
  keyboardOpen: boolean;
  onSelectBook: (bookId: string) => void;
  onSelectView: (view: WorkspaceView) => void;
  onOpenImport: () => void;
  onOpenOcrDrawer: () => void;
  onToggleKeyboard: () => void;
  onOpenShortcuts: () => void;
}

const VIEW_TABS: Array<{ key: WorkspaceView; label: string; icon: string }> = [
  { key: "review", label: "Proofread", icon: "📖" },
  { key: "dictionary", label: "Dictionary", icon: "📚" },
  { key: "memory", label: "Memory", icon: "🧠" },
  { key: "export", label: "Export", icon: "📄" },
];

export function TopNavBar({
  books,
  selectedBook,
  runs,
  activeView,
  keyboardOpen,
  onSelectBook,
  onSelectView,
  onOpenImport,
  onOpenOcrDrawer,
  onToggleKeyboard,
  onOpenShortcuts,
}: TopNavBarProps) {
  const [bookMenuOpen, setBookMenuOpen] = useState(false);
  const [bookFilter, setBookFilter] = useState("");
  const menuWrapRef = useRef<HTMLDivElement>(null);
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const menuId = useId();

  useEffect(() => {
    if (!bookMenuOpen) return;
    function onDocPointerDown(e: MouseEvent) {
      if (menuWrapRef.current && !menuWrapRef.current.contains(e.target as Node)) {
        setBookMenuOpen(false);
      }
    }
    function onDocKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setBookMenuOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocPointerDown);
    document.addEventListener("keydown", onDocKeyDown);
    return () => {
      document.removeEventListener("mousedown", onDocPointerDown);
      document.removeEventListener("keydown", onDocKeyDown);
    };
  }, [bookMenuOpen]);

  const filteredBooks = bookFilter.trim()
    ? books.filter((b) => b.title.toLowerCase().includes(bookFilter.trim().toLowerCase()))
    : books;

  // Derive concise OCR button status
  const running = runs.find((r) => r.status === "running");
  const queued = runs.find((r) => r.status === "queued");
  const completedRuns = runs.filter((r) => r.status === "completed");
  const partialOrFailed = runs.filter((r) => r.status === "partial" || r.status === "failed");
  const needsScanOcr = selectedBook
    ? selectedBook.scanned_pages_count + selectedBook.mixed_pages_count > 0
    : false;

  let ocrTone: "neutral" | "active" | "ready" | "warn" = "neutral";
  let ocrLabel = "OCR";
  if (selectedBook) {
    if (running) {
      const tel = buildRunTelemetry(running, selectedBook, Date.now());
      ocrTone = "active";
      ocrLabel =
        tel.total > 0
          ? `OCR ${tel.percent}% (${tel.completed}/${tel.total})`
          : `OCR ${formatEngineLabel(running.engine)}`;
    } else if (queued) {
      ocrTone = "active";
      ocrLabel = `Queued · ${formatEngineLabel(queued.engine)}`;
    } else if (completedRuns.length > 0 || !needsScanOcr) {
      ocrTone = "ready";
      ocrLabel = needsScanOcr ? "OCR Ready" : "Digital PDF";
    } else if (partialOrFailed.length > 0) {
      ocrTone = "warn";
      ocrLabel = "Resume OCR";
    } else {
      ocrTone = "warn";
      ocrLabel = "Run OCR";
    }
  }

  function handleTabKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const enabledTabs = VIEW_TABS.filter((t) => !(t.key === "export" && !selectedBook));
    const currentIdx = enabledTabs.findIndex((t) => t.key === activeView);
    if (currentIdx === -1) return;

    let nextIdx: number | null = null;
    if (e.key === "ArrowRight") {
      nextIdx = (currentIdx + 1) % enabledTabs.length;
    } else if (e.key === "ArrowLeft") {
      nextIdx = (currentIdx - 1 + enabledTabs.length) % enabledTabs.length;
    } else if (e.key === "Home") {
      nextIdx = 0;
    } else if (e.key === "End") {
      nextIdx = enabledTabs.length - 1;
    }
    if (nextIdx === null) return;
    e.preventDefault();
    const targetTab = enabledTabs[nextIdx];
    onSelectView(targetTab.key);
    const fullIdx = VIEW_TABS.findIndex((t) => t.key === targetTab.key);
    tabRefs.current[fullIdx]?.focus();
  }

  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="brand-compact">
          <div className="brand-mark-sm" aria-hidden="true">
            <span lang="te">తె</span>
          </div>
          <h1 className="topbar-title">Telugu Digitizer</h1>
        </div>

        <span className="topbar-divider" aria-hidden="true" />

        <div ref={menuWrapRef} className="book-switcher-wrap">
          {books.length > 0 ? (
            <>
              <button
                type="button"
                className="book-switcher-trigger"
                aria-haspopup="menu"
                aria-expanded={bookMenuOpen}
                aria-controls={menuId}
                title={selectedBook ? `${selectedBook.title} (${selectedBook.page_count} pages)` : "Select book"}
                onClick={() => setBookMenuOpen((v) => !v)}
              >
                <span className="book-switcher-title" lang="te">
                  {selectedBook ? selectedBook.title : "Select Book"}
                </span>
                {selectedBook && (
                  <span className="book-switcher-meta">{selectedBook.page_count}p</span>
                )}
                <span className="book-switcher-caret" aria-hidden="true">
                  ▾
                </span>
              </button>

              {bookMenuOpen && (
                <div id={menuId} className="book-switcher-menu" role="menu" aria-label="Books library">
                  <div className="book-switcher-menu-head">
                    <strong>Books ({books.length})</strong>
                    <button
                      type="button"
                      className="primary btn-compact"
                      onClick={() => {
                        setBookMenuOpen(false);
                        onOpenImport();
                      }}
                    >
                      ＋ Import PDF
                    </button>
                  </div>
                  {books.length > 5 && (
                    <input
                      type="search"
                      lang="te"
                      className="book-switcher-search"
                      aria-label="Filter books"
                      placeholder="Filter books…"
                      value={bookFilter}
                      onChange={(e) => setBookFilter(e.target.value)}
                    />
                  )}
                  <ul className="book-switcher-list" role="none">
                    {filteredBooks.map((book) => {
                      const isSel = book.book_id === selectedBook?.book_id;
                      return (
                        <li key={book.book_id} role="none">
                          <button
                            type="button"
                            role="menuitemradio"
                            aria-checked={isSel}
                            className={`book-switcher-item ${isSel ? "selected" : ""}`.trim()}
                            onClick={() => {
                              onSelectBook(book.book_id);
                              setBookMenuOpen(false);
                              setBookFilter("");
                            }}
                          >
                            <span className="book-switcher-item-title" lang="te">
                              {isSel ? "✓ " : ""}
                              {book.title}
                            </span>
                            <span className="hint-text">
                              {book.page_count}p · {book.scanned_pages_count} scan · {book.digital_text_pages_count} dig
                            </span>
                          </button>
                        </li>
                      );
                    })}
                    {filteredBooks.length === 0 && (
                      <li className="hint-text" style={{ padding: "0.5rem" }}>
                        No books match "{bookFilter}".
                      </li>
                    )}
                  </ul>
                </div>
              )}
            </>
          ) : (
            <button
              type="button"
              className="primary btn-compact"
              onClick={onOpenImport}
            >
              ＋ Import PDF
            </button>
          )}
        </div>
      </div>

      <div
        className="topbar-tabs"
        role="tablist"
        aria-label="Workspace views"
        onKeyDown={handleTabKeyDown}
      >
        {VIEW_TABS.map((tab, idx) => {
          const isSelected = activeView === tab.key;
          const isDisabled = tab.key === "export" && !selectedBook;
          return (
            <button
              key={tab.key}
              ref={(el) => {
                tabRefs.current[idx] = el;
              }}
              type="button"
              role="tab"
              aria-selected={isSelected}
              tabIndex={isSelected ? 0 : -1}
              disabled={isDisabled}
              className={`topbar-tab-btn ${isSelected ? "active" : ""}`.trim()}
              onClick={() => onSelectView(tab.key)}
            >
              <span aria-hidden="true">{tab.icon}</span>
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      <div className="topbar-right">
        {selectedBook && (
          <button
            type="button"
            className={`ocr-pill-btn ${ocrTone}`}
            title="Configure, run, or resume OCR engines"
            onClick={onOpenOcrDrawer}
          >
            {ocrTone === "active" && <span className="status-dot pulse" aria-hidden="true" />}
            {ocrTone === "ready" && <span aria-hidden="true">✓</span>}
            {ocrTone === "warn" && <span aria-hidden="true">⚙</span>}
            <span>{ocrLabel}</span>
            <span aria-hidden="true">▾</span>
          </button>
        )}

        <button
          type="button"
          className="btn-compact icon-label-btn"
          aria-pressed={keyboardOpen}
          aria-label="Toggle Telugu virtual keyboard"
          title="Toggle on-screen Telugu InScript & Phonetic keyboard"
          onClick={onToggleKeyboard}
        >
          <span aria-hidden="true">⌨</span>
          <span className="hide-sm">Keyboard</span>
        </button>

        <button
          type="button"
          className="btn-compact icon-only-btn"
          aria-label="Keyboard shortcuts and studio guarantees"
          title="Keyboard shortcuts (?) & data guarantees"
          onClick={onOpenShortcuts}
        >
          ?
        </button>
      </div>
    </header>
  );
}
