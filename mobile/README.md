# Telugu Book Digitizer — Mobile App (Flutter)

Native Android, iOS, and macOS companion app for **Telugu Book Digitizer**, built with Flutter (`mobile/`).

By default, the app connects to **`https://lahari.org/telugu`** and allows switching to any local Raspberry Pi (`http://192.168.1.13:8085`) or desktop (`http://127.0.0.1:8000`) server from the in-app **Server Settings** sheet.

---

## Features

1. **Book Library & PDF Upload (`LibraryTabView`)**:
   - Browse imported Telugu books with page counts (`scanned`, `digital`, `mixed`).
   - Upload printed Telugu PDFs from the device via `file_picker` with SHA-256 deduplication, orthography profile, and training consent.
   - Start or resume dual-engine OCR runs (`PaddleOCR PP-OCRv5` and `Tesseract 5 Telugu`) on Pages 1–5 or the full book with live progress polling.
2. **Adaptive Side-by-Side / Split Page Review (`PageReviewTabView`)**:
   - **Interactive Scan + Boxes (`InteractiveViewer` + `CustomPainter`)**: Pinch-to-zoom and pan the 300-DPI page scan with color-coded OCR polygons; tap any polygon to select the corresponding Telugu line.
   - **Proofreading Editor**:
     - Immutable Raw OCR display and engine disagreement comparator (`Use` button).
     - Contextual Correction Memory suggestions with 1-tap `Apply` and `Reject`.
     - Inline line filter search, `Flagged (N)` filter, `Next Issue ▾` jump, and `A−` / `A+` Telugu script size controls.
     - Quick Telugu combining signs (*గుణింతాలు*) bar that inserts vowel signs and *virama* directly at the active cursor position.
     - Append-only `Save Correction` (with optional `Save to correction memory` and `book_only` / `global_suggestion` scope), `Approve Block`, `Revert to Raw OCR`, collapsible revision history, and `Approve Page`.
3. **Correction Memory Manager (`CorrectionMemoryTabView`)**:
   - Search and filter stored Telugu corrections by status (`ALL`, `ACTIVE`, `DISABLED`, `REJECTED`) and book scope, view conflict badges and `+approved / -rejected` evidence counters, and toggle `Disable` / `Re-enable`.
4. **Document Export (`ExportTabView`)**:
   - Generate and download validated `Page-preserving DOCX`, `Editable-flow DOCX`, or `UTF-8 TXT` exports (`Human-reviewed` or `Raw OCR`) and inspect sidecar JSON manifests.

---

## Commands

```bash
cd mobile

# Install dependencies
flutter pub get

# Static analysis (strict casts, inference, and raw types)
dart analyze --fatal-infos

# Run unit & widget tests
flutter test

# Run on a connected Android / iOS device or simulator
flutter run

# Build release Android APK
flutter build apk --release
```
