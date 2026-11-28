# 16 — How Book State & Workspace Selection Restore After a Shutdown

When you open `https://lahari.org/telugu/` after a clean shutdown and reboot of the Raspberry Pi, your imported book (**Amuktamalyada Vo.1**), OCR runs (**Tesseract 5 Telugu**), approved pages (`1/406`), and extracted text appear automatically.

**Short answer:** This is **not** a browser cache (`localStorage`, `sessionStorage`, `IndexedDB`, or cookies are not used by the Web Studio for book state). Everything is **persisted on the Raspberry Pi's NVMe SSD** in PostgreSQL and the workspace directory, restarted automatically by `systemd` at boot, and re-selected by the React app on startup.

---

## 1. End-to-End Flow (Shutdown → Boot → Browser Load)

```text
1. During your previous session (persisted immediately on the Pi):
   ├─ PostgreSQL (`telugu_digitizer` DB on `/dev/sda2`)
   │    ├─ `books`                → book metadata, title, `page_count`, `source_sha256`
   │    ├─ `book_pages`           → per-page classification (`scanned_image` / `digital_text`), `review_status` (`approved` / `not_started`), extracted digital text
   │    ├─ `ocr_runs` / `processing_jobs` → engine statuses (`completed` / `partial`), progress (`15/15`, `0/15`), config
   │    ├─ `ocr_blocks` / `review_edits` / `document_text_blocks` → raw OCR text, bounding polygons, human edits, roles
   │    └─ `correction_memory` / `document_exports` → reusable Telugu rules & export records
   └─ Filesystem (`/home/lipi/telugu-digitizer/workspace/` on `/dev/sda2`)
        ├─ `originals/{book_id}/source.pdf`
        ├─ `pages/{book_id}/page-NNNN.png`
        ├─ `ocr/{book_id}/{run_id}/...`
        └─ `exports/{book_id}/...`

2. On Raspberry Pi boot (automatic via systemd):
   ├─ `postgresql.service` starts and mounts the `telugu_digitizer` database from `/dev/sda2`.
   ├─ `telugu-digitizer.service` (`WantedBy=multi-user.target`, `After=postgresql.service`) starts `uvicorn` on `127.0.0.1:8085`.
   ├─ FastAPI `lifespan()` checks `ocr_runs` & `processing_jobs`: any unfinished `running`/`queued` jobs are safely marked `partial`; `completed` runs and approved pages remain intact.
   └─ Apache2 proxies `https://lahari.org/telugu/` → `http://127.0.0.1:8085/`.

3. When you open https://lahari.org/telugu/ in your browser:
   ├─ React mounts (`frontend/src/App.tsx`) with empty in-memory state (`selectedBookId = null`, `selectedPageNumber = 1`).
   ├─ `useEffect()` calls `GET api/v1/books` (`listBooks()`).
   ├─ Backend returns rows from `books` ordered newest-first (`ORDER BY created_at DESC`).
   ├─ Seeing `items.length > 0`, the UI:
   │    1. Auto-collapses the Upload form (`setUploadExpanded(false)`).
   │    2. Auto-selects the first (most recently imported) book (`setSelectedBookId(items[0].book_id)`).
   │    3. Sets `selectedPageNumber` to `1`.
   └─ Selecting `selectedBookId` triggers:
        ├─ `GET api/v1/books/{id}/pages` (populates the 406-page sidebar & `1/406 approved` count)
        ├─ `GET api/v1/books/{id}/ocr-runs` (populates `Tesseract 5 Telugu` Ready + `Resume PaddleOCR 0/15`)
        └─ `GET api/v1/books/{id}/pages/1/review` + `pages/1/image` (populates Page 1 scan & editor)
```

---

## 2. Step-by-Step Code & System Breakdown

### Layer 1: Browser (`frontend/src/`) — Ephemeral In-Memory React State Only
In [frontend/src/App.tsx](file:///Users/shanmukhan/Developer/repo/telugu-digitizer/frontend/src/App.tsx#L58-L66), the Web Studio holds only React `useState` variables in memory (zero `localStorage`, `sessionStorage`, or cookies):

```tsx
const [books, setBooks] = useState<BookSummary[]>([]);
const [selectedBookId, setSelectedBookId] = useState<string | null>(null);
const [pages, setPages] = useState<PageSummary[]>([]);
const [selectedPageNumber, setSelectedPageNumber] = useState<number>(1);
```

When the page loads (`useEffect` at [App.tsx](file:///Users/shanmukhan/Developer/repo/telugu-digitizer/frontend/src/App.tsx#L167-L184)), it calls `refreshBooks()`, which executes:

```tsx
const items = await listBooks(); // GET api/v1/books
setBooks(items);
if (!initializedCollapseRef.current) {
  initializedCollapseRef.current = true;
  if (items.length > 0) {
    setUploadExpanded(false);
  }
}
if (items.length > 0 && (!selectedBookId || !items.some((b) => b.book_id === selectedBookId))) {
  setSelectedBookId(items[0].book_id);
  setSelectedPageNumber(1);
}
```
([App.tsx](file:///Users/shanmukhan/Developer/repo/telugu-digitizer/frontend/src/App.tsx#L132-L151))

Once `selectedBookId` changes from `null` to `items[0].book_id`, two follow-up effects run automatically ([App.tsx](file:///Users/shanmukhan/Developer/repo/telugu-digitizer/frontend/src/App.tsx#L186-L201)):
1. `refreshBookDetail(selectedBookId)` fetches all page summaries (`GET api/v1/books/{id}/pages`) and OCR run histories (`GET api/v1/books/{id}/ocr-runs`).
2. `refreshReview(selectedBookId, selectedPageNumber, selectedPrimaryRunId)` loads Page 1's scan metadata, digital text (or OCR blocks), and review status (`GET api/v1/books/{id}/pages/1/review`).

### Layer 2: Backend Database Ordering & Crash Recovery (`src/`)
- **Server-side book ordering:** `list_books_with_counts(db)` in [src/services/book_service.py](file:///Users/shanmukhan/Developer/repo/telugu-digitizer/src/services/book_service.py#L187-L194) queries PostgreSQL with:
  ```python
  books = list(db.scalars(select(Book).order_by(Book.created_at.desc())).all())
  ```
  So `items[0]` is always the **most recently imported book** on the server.
- **Page-level primary run selection:** When `get_page_review_payload()` runs ([src/services/review_service.py](file:///Users/shanmukhan/Developer/repo/telugu-digitizer/src/services/review_service.py#L194-L246)), it inspects all `"completed"` / `"partial"` runs in `ocr_runs`, prioritizes runs that actually have blocks or completed progress for the page (`Tesseract 5 Telugu` completed `15/15`), and displays that run in the **Engine** dropdown.
- **Startup recovery guard:** In [src/api/app.py](file:///Users/shanmukhan/Developer/repo/telugu-digitizer/src/api/app.py#L45-L78), the FastAPI `lifespan` handler checks on every boot whether any `ocr_runs` or `processing_jobs` were caught in `"running"` or `"queued"` during a shutdown/crash and marks them `"partial"` (`"Interrupted before completion; ready to resume."`) without disturbing finished work.

### Layer 3: Systemd & Disk Storage on Raspberry Pi (`/dev/sda2`)
- PostgreSQL stores all relational tables under `/var/lib/postgresql/17/main` on `/dev/sda2` (flushed to NVMe disk on transaction `commit()`).
- Binary files (source PDFs, 300-DPI PNG renders, raw OCR JSON/TSV artifacts, exports, and logs) live under `/home/lipi/telugu-digitizer/workspace/` (`WORKSPACE_DIR` configured in `/etc/telugu-digitizer/env`).
- [deploy/raspberry-pi/telugu-digitizer.service](file:///Users/shanmukhan/Developer/repo/telugu-digitizer/deploy/raspberry-pi/telugu-digitizer.service) is enabled (`WantedBy=multi-user.target`, `After=network-online.target postgresql.service`), so after any clean shutdown and power-on, PostgreSQL and FastAPI/Uvicorn come back online automatically before you even open the browser.

---

## 3. Why Your Screenshot Shows Exactly What It Does (Important Nuance)

1. **Why *Amuktamalyada Vo.1* came back automatically:**
   It is persisted in PostgreSQL (`Books (1)`), and on page load `App.tsx` automatically picks `items[0]` (the newest book in the DB). Even if you opened `https://lahari.org/telugu/` from a **brand-new incognito window or another device (such as the mobile app)**, you would still see this exact same book, `1/406 approved` count, and `Tesseract 5 Telugu` run.
2. **Why it opened on `Page 1` instead of `Page 7`:**
   Because the browser is **not** caching your last open UI tab/page locally (`localStorage` / URL `?book=...&page=...`), every fresh load resets `selectedPageNumber` to `1` and `selectedPrimaryRunId` to `null` (default backend selection). In your screenshot:
   - **Page 1** is `"Born-Digital Text Path (Not OCR)"` (the archive metadata cover sheet) and was previously marked **Approved** (`1/406 approved`).
   - Clicking Page 7 in the left **Pages** list (or typing `7` into the `Page [ 1 ] / 406` box) will immediately load Page 7 and its 24 Tesseract OCR lines from PostgreSQL.

*(Note: If multiple books are uploaded later and you want the browser to remember **which** book and **which** page number you were last editing across refreshes, that can be added easily via URL query params like `?book=<id>&page=7` or `localStorage`.)*
