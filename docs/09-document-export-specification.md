# 09 — DOCX and TXT Export Specification

## 1. Output principle

Generate files from the selected transcript version, preferably `human_approved`. If exported from raw OCR, clearly label the document as unreviewed machine output.

All Telugu content must be genuine Unicode text. Do not transliterate Telugu into Latin characters.

### Multi-range OCR run stitching (Auto-select mode)
When exporting without an explicit `primary_run_id` (`primary_run_id=None`, the UI default), `_collect_export_pages` resolves blocks **per page** across all usable (`completed` / `partial`) OCR runs for the book:
- For `human_approved` exports, any run containing human-reviewed `DocumentTextBlock` or `ReviewEdit` entries for a page takes precedence on that page.
- Otherwise, the highest-priority populated run for that page is selected.
- This allows reviewers to run a fast sample range (e.g., Pages `1–5`), approve those pages, and later run the remaining range (`6–406`) without losing approved edits or dropping Pages `1–5` from the final `.docx`/`.txt` export. Passing an explicit `primary_run_id` restricts export strictly to that single run.

## 2. Export modes

### A. Editable-flow DOCX

Purpose: a readable, editable book document.

- Text flows naturally from page to page.
- Use document title and author metadata.
- Use Heading styles for chapter/section headings when identified or approved by the user.
- Preserve paragraph boundaries and logical reading order.
- Use page margins and font sizes suitable for print.
- Optionally generate a table of contents from heading styles.
- Page numbering is based on the new Word document, not the original scan.

This mode will not preserve the original page breaks or exact page count.

### B. Page-preserving DOCX

Purpose: keep the original PDF's page sequence and approximate per-page text grouping.

- Create one Word page section/page break per source page.
- Retain page-level boundaries and text order.
- Use the source page size where feasible.
- Retain page numbers and headings when present in the transcript.
- Optionally retain page images as visual references in a separate review export.

**Important limitation:** Editable text in Word reflows. A page-preserving DOCX can preserve page boundaries and approximate page grouping, but cannot promise pixel-perfect placement of every glyph relative to the original scan. Exact facsimile reproduction is a different mode: it would place page images in Word and optionally overlay hidden OCR text, which is less editable and should be a separate future option.

### C. TXT

- UTF-8 encoding.
- Preserve chapter and paragraph boundaries.
- Use form-feed (`\f`) or a clearly documented page delimiter for source page boundaries in page-aware TXT export.
- Do not add OCR confidence or JSON metadata to the text file.
- Optionally export a separate metadata JSON sidecar.

## 3. Formatting defaults

| Setting | Default |
|---|---|
| Language | Telugu |
| Suggested font | Noto Serif Telugu for literary books; Noto Sans Telugu as fallback |
| Body font size | 12 pt (configurable) |
| Chapter title | 18–22 pt, bold |
| Line spacing | 1.15–1.3 |
| Paragraph spacing | 6 pt after (configurable) |
| Margins | 1 inch / 2.54 cm (configurable) |
| Alignment | Left by default; book-specific configuration may use justified |
| Page size | A4 default; allow source/custom page dimensions |

The chosen font must be installed on the system that opens/renders the DOCX. DOCX generally references fonts rather than embedding them automatically.

## 4. Book structure metadata

Support:

- title;
- subtitle;
- author;
- publisher;
- publication year;
- chapter titles;
- section headings;
- paragraph text;
- source page number;
- optional footnotes/endnotes.

Do not infer chapter structure solely from font size or OCR confidence. Allow the reviewer to classify headings before final export.

## 5. Quality validation

For every export:

1. Validate UTF-8/Unicode text.
2. Re-open generated DOCX with `python-docx` and verify paragraph text.
3. Verify page breaks and section metadata where applicable.
4. Render DOCX through LibreOffice in a test environment if available and visually inspect Telugu shaping.
5. Check that no text blocks were dropped or duplicated.
6. Compare extracted DOCX text with the approved transcript after the defined normalization policy.

## 6. Export naming

Use deterministic, filesystem-safe names, for example:

- `book-title_editable-flow.docx`
- `book-title_page-preserving.docx`
- `book-title.txt`

Keep title separately in metadata; sanitize filename characters.

## 7. Export metadata sidecar

Optionally write `export-manifest.json` containing:

- book ID and title;
- transcript version ID;
- export mode and options;
- font family;
- export library/version;
- creation timestamp;
- source PDF hash;
- list of included source pages;
- whether text was reviewed.
