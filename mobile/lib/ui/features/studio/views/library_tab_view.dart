import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';

import '../../../../data/models/api_models.dart';
import '../../../core/app_theme.dart';
import '../view_models/studio_view_model.dart';

class LibraryTabView extends StatelessWidget {
  const LibraryTabView({
    super.key,
    required this.viewModel,
    required this.onOpenReview,
    required this.onOpenExport,
  });

  final StudioViewModel viewModel;
  final VoidCallback onOpenReview;
  final VoidCallback onOpenExport;

  Future<void> _showUploadSheet(BuildContext context) async {
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => _PdfUploadSheet(viewModel: viewModel),
    );
  }

  Future<void> _confirmDeleteBook(
    BuildContext context,
    BookSummary book,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete book and OCR artifacts?'),
        content: Text(
          'This permanently removes "${book.title}", its source PDF, rendered page PNGs, OCR runs, and review edits from the server.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: AppTheme.dangerBorder,
            ),
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Delete Book'),
          ),
        ],
      ),
    );
    if (confirmed == true) {
      await viewModel.deleteSelectedBook();
    }
  }

  @override
  Widget build(BuildContext context) {
    final selectedBook = viewModel.selectedBook;
    final activeRun = viewModel.primaryActiveRun;
    final resumableRuns =
        viewModel.runs.where((r) => r.isResumable).toList();

    return RefreshIndicator(
      onRefresh: viewModel.refreshBooks,
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 960),
          child: ListView(
            padding: const EdgeInsets.all(16),
            children: [
              // Welcome / Import header card
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Container(
                            padding: const EdgeInsets.all(10),
                            decoration: BoxDecoration(
                              color: AppTheme.primarySoft,
                              borderRadius: BorderRadius.circular(10),
                            ),
                            child: const Icon(
                              Icons.menu_book_rounded,
                              color: AppTheme.primary,
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Text(
                                  'Telugu Book Library (${viewModel.books.length})',
                                  style: Theme.of(context)
                                      .textTheme
                                      .titleMedium
                                      ?.copyWith(fontWeight: FontWeight.w700),
                                ),
                                const Text(
                                  'Dual-engine OCR · Immutable raw text · Human review',
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: AppTheme.inkMuted,
                                  ),
                                ),
                              ],
                            ),
                          ),
                          FilledButton.icon(
                            onPressed: viewModel.busyUpload
                                ? null
                                : () => _showUploadSheet(context),
                            icon: const Icon(Icons.upload_file),
                            label: const Text('Import PDF'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 12),

              if (viewModel.books.isEmpty)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      children: [
                        const Icon(
                          Icons.library_books_outlined,
                          size: 48,
                          color: AppTheme.primary,
                        ),
                        const SizedBox(height: 12),
                        Text(
                          'No Telugu books imported yet',
                          style: Theme.of(context).textTheme.titleMedium,
                        ),
                        const SizedBox(height: 6),
                        const Text(
                          'Import a scanned Telugu PDF to classify pages, run PaddleOCR PP-OCRv5 and Tesseract 5, proofread lines against the scan, and export DOCX/TXT.',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: AppTheme.inkMuted),
                        ),
                      ],
                    ),
                  ),
                )
              else ...[
                // Book list
                ...viewModel.books.map((book) {
                  final isSelected = book.bookId == viewModel.selectedBookId;
                  return Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Card(
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(14),
                        side: BorderSide(
                          color: isSelected
                              ? AppTheme.primary
                              : AppTheme.border,
                          width: isSelected ? 2 : 1,
                        ),
                      ),
                      color: isSelected
                          ? AppTheme.primarySoft
                          : AppTheme.surface,
                      child: InkWell(
                        borderRadius: BorderRadius.circular(14),
                        onTap: () => viewModel.selectBook(book.bookId),
                        child: Padding(
                          padding: const EdgeInsets.all(14),
                          child: Row(
                            children: [
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      book.title,
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w700,
                                        fontSize: 16,
                                        fontFamilyFallback:
                                            AppTheme.teluguFontFallback,
                                      ),
                                    ),
                                    const SizedBox(height: 4),
                                    Text(
                                      '${book.pageCount} pages · ${book.scannedPagesCount} scanned · ${book.digitalTextPagesCount} digital${book.mixedPagesCount > 0 ? ' · ${book.mixedPagesCount} mixed' : ''}',
                                      style: const TextStyle(
                                        fontSize: 12.5,
                                        color: AppTheme.inkMuted,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              if (isSelected) ...[
                                IconButton(
                                  tooltip: 'Open Page Review',
                                  onPressed: onOpenReview,
                                  icon: const Icon(
                                    Icons.rate_review_outlined,
                                    color: AppTheme.primary,
                                  ),
                                ),
                                IconButton(
                                  tooltip: 'Delete Book',
                                  onPressed: () =>
                                      _confirmDeleteBook(context, book),
                                  icon: const Icon(
                                    Icons.delete_outline,
                                    color: AppTheme.dangerBorder,
                                  ),
                                ),
                              ],
                            ],
                          ),
                        ),
                      ),
                    ),
                  );
                }),
              ],

              // Selected book OCR controls & progress strip
              if (selectedBook != null) ...[
                const SizedBox(height: 8),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Text(
                              'OCR Engines & Progress',
                              style: Theme.of(context)
                                  .textTheme
                                  .titleMedium
                                  ?.copyWith(fontWeight: FontWeight.w700),
                            ),
                            Text(
                              '${viewModel.approvedPagesCount}/${selectedBook.pageCount} approved',
                              style: const TextStyle(
                                fontSize: 12.5,
                                fontWeight: FontWeight.w600,
                                color: AppTheme.primary,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        if (activeRun != null) ...[
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: AppTheme.primarySoft,
                              borderRadius: BorderRadius.circular(10),
                              border:
                                  Border.all(color: AppTheme.primary),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  mainAxisAlignment:
                                      MainAxisAlignment.spaceBetween,
                                  children: [
                                    Text(
                                      '${formatEngineLabel(activeRun.engine)} (${activeRun.status})',
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w700,
                                      ),
                                    ),
                                    Text(
                                      '${activeRun.progressCurrent}/${activeRun.progressTotal} pages',
                                      style: const TextStyle(
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 8),
                                LinearProgressIndicator(
                                  value: activeRun.progressTotal > 0
                                      ? activeRun.progressCurrent /
                                          activeRun.progressTotal
                                      : null,
                                  minHeight: 8,
                                  borderRadius: BorderRadius.circular(99),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(height: 12),
                        ],
                        CheckboxListTile(
                          dense: true,
                          contentPadding: EdgeInsets.zero,
                          value: viewModel.usePaddle,
                          onChanged: (viewModel.capabilities
                                      ?.isPaddleAvailable ??
                                  true)
                              ? (val) =>
                                  viewModel.setUsePaddle(val ?? false)
                              : null,
                          title: const Text('PaddleOCR PP-OCRv5 Telugu'),
                          subtitle: const Text('Primary model (~90s/page CPU)'),
                        ),
                        CheckboxListTile(
                          dense: true,
                          contentPadding: EdgeInsets.zero,
                          value: viewModel.useTesseract,
                          onChanged: (viewModel.capabilities
                                      ?.isTesseractAvailable ??
                                  true)
                              ? (val) =>
                                  viewModel.setUseTesseract(val ?? false)
                              : null,
                          title: const Text('Tesseract 5 Telugu (tessdata_best)'),
                          subtitle: const Text('Fast LSTM baseline (~0.4s/page CPU)'),
                        ),
                        const SizedBox(height: 10),
                        Wrap(
                          spacing: 10,
                          runSpacing: 10,
                          children: [
                            FilledButton.icon(
                              onPressed: viewModel.isOcrRunning ||
                                      viewModel.busyOcrStart
                                  ? null
                                  : () => viewModel.startOcr(
                                        startPage: 1,
                                        endPage: selectedBook.pageCount < 5
                                            ? selectedBook.pageCount
                                            : 5,
                                      ),
                              icon: const Icon(Icons.bolt),
                              label: const Text('Test Pages 1–5'),
                            ),
                            OutlinedButton.icon(
                              onPressed: viewModel.isOcrRunning ||
                                      viewModel.busyOcrStart
                                  ? null
                                  : () => viewModel.startOcr(),
                              icon: const Icon(Icons.play_arrow_rounded),
                              label: Text(
                                'Run Full Book (${selectedBook.pageCount}p)',
                              ),
                            ),
                            OutlinedButton.icon(
                              onPressed: onOpenReview,
                              icon: const Icon(Icons.fact_check_outlined),
                              label: const Text('Review Pages'),
                            ),
                            OutlinedButton.icon(
                              onPressed: onOpenExport,
                              icon: const Icon(Icons.download_outlined),
                              label: const Text('Export DOCX/TXT'),
                            ),
                          ],
                        ),
                        if (resumableRuns.isNotEmpty) ...[
                          const SizedBox(height: 12),
                          Wrap(
                            spacing: 8,
                            runSpacing: 8,
                            children: resumableRuns
                                .map(
                                  (run) => ActionChip(
                                    avatar: const Icon(Icons.replay, size: 16),
                                    label: Text(
                                      'Resume ${formatEngineLabel(run.engine)} (${run.progressCurrent}/${run.progressTotal})',
                                    ),
                                    onPressed: () =>
                                        viewModel.resumeOcrRun(run.ocrRunId),
                                  ),
                                )
                                .toList(),
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

class _PdfUploadSheet extends StatefulWidget {
  const _PdfUploadSheet({required this.viewModel});

  final StudioViewModel viewModel;

  @override
  State<_PdfUploadSheet> createState() => _PdfUploadSheetState();
}

class _PdfUploadSheetState extends State<_PdfUploadSheet> {
  final TextEditingController _titleController = TextEditingController();
  final TextEditingController _authorController = TextEditingController();
  String _orthographyProfile = 'unspecified';
  bool _trainingConsent = false;
  String? _pickedFilename;
  Uint8List? _pickedBytes;
  String? _localError;

  @override
  void dispose() {
    _titleController.dispose();
    _authorController.dispose();
    super.dispose();
  }

  Future<void> _pickPdf() async {
    final files = await FilePicker.pickFiles(
      type: FileType.custom,
      allowedExtensions: const ['pdf'],
    );
    if (files.isEmpty) return;
    final file = files.first;
    Uint8List? bytes;
    try {
      bytes = await file.readAsBytes();
    } catch (_) {
      bytes = null;
    }
    if (bytes == null) {
      setState(() => _localError = 'Could not read selected PDF file.');
      return;
    }
    setState(() {
      _pickedFilename = file.name;
      _pickedBytes = bytes;
      _localError = null;
      if (_titleController.text.trim().isEmpty) {
        _titleController.text =
            file.name.replaceAll(RegExp(r'\.pdf$', caseSensitive: false), '');
      }
    });
  }

  Future<void> _submit() async {
    if (_pickedBytes == null || _pickedFilename == null) {
      setState(() => _localError = 'Please choose a PDF file to upload.');
      return;
    }
    if (_titleController.text.trim().isEmpty) {
      setState(() => _localError = 'Please enter a book title.');
      return;
    }
    final ok = await widget.viewModel.uploadPdfBook(
      pdfBytes: _pickedBytes!,
      filename: _pickedFilename!,
      title: _titleController.text.trim(),
      author: _authorController.text.trim(),
      orthographyProfile: _orthographyProfile,
      trainingConsent: _trainingConsent,
    );
    if (ok && mounted) {
      Navigator.of(context).pop();
    }
  }

  @override
  Widget build(BuildContext context) {
    final busy = widget.viewModel.busyUpload;
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.viewInsetsOf(context).bottom + 24,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Import Printed Telugu PDF',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: busy ? null : _pickPdf,
              icon: const Icon(Icons.picture_as_pdf_outlined),
              label: Text(
                _pickedFilename ?? 'Choose Telugu PDF File (.pdf)',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _titleController,
              decoration: const InputDecoration(
                labelText: 'Book Title *',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _authorController,
              decoration: const InputDecoration(
                labelText: 'Author (optional)',
              ),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              initialValue: _orthographyProfile,
              decoration: const InputDecoration(
                labelText: 'Orthography Profile',
              ),
              items: const [
                DropdownMenuItem(
                  value: 'unspecified',
                  child: Text('Unspecified'),
                ),
                DropdownMenuItem(
                  value: 'modern_standard',
                  child: Text('Modern standard Telugu'),
                ),
                DropdownMenuItem(
                  value: 'classical_literary',
                  child: Text('Classical / literary Telugu'),
                ),
                DropdownMenuItem(
                  value: 'pre_1950_print',
                  child: Text('Pre-1950 print conventions'),
                ),
              ],
              onChanged: (val) {
                if (val != null) setState(() => _orthographyProfile = val);
              },
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: _trainingConsent,
              onChanged: (val) => setState(() => _trainingConsent = val),
              title: const Text(
                'Allow verified crops for future OCR training',
                style: TextStyle(fontSize: 13.5),
              ),
            ),
            if (_localError != null) ...[
              Text(
                _localError!,
                style: const TextStyle(
                  color: AppTheme.dangerBorder,
                  fontSize: 13,
                ),
              ),
              const SizedBox(height: 8),
            ],
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: busy ? null : () => Navigator.of(context).pop(),
                  child: const Text('Cancel'),
                ),
                const SizedBox(width: 8),
                FilledButton.icon(
                  onPressed: busy ? null : _submit,
                  icon: const Icon(Icons.cloud_upload_outlined),
                  label: Text(busy ? 'Importing...' : 'Import PDF'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
