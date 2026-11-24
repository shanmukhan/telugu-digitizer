import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../../data/models/api_models.dart';
import '../../../../data/repositories/digitizer_repository.dart';
import '../../../core/app_theme.dart';

class StudioViewModel extends ChangeNotifier {
  StudioViewModel({required this.repository});

  final DigitizerRepository repository;
  DigitizerRepository get _repository => repository;

  bool _initializing = true;
  bool get initializing => _initializing;

  bool _busyUpload = false;
  bool get busyUpload => _busyUpload;

  bool _busyOcrStart = false;
  bool get busyOcrStart => _busyOcrStart;

  bool _busyReviewLoad = false;
  bool get busyReviewLoad => _busyReviewLoad;

  bool _busyExport = false;
  bool get busyExport => _busyExport;

  String? _busyBlockId;
  String? get busyBlockId => _busyBlockId;

  bool _serverConnected = false;
  bool get serverConnected => _serverConnected;

  HostCapabilities? _capabilities;
  HostCapabilities? get capabilities => _capabilities;

  List<BookSummary> _books = const [];
  List<BookSummary> get books => _books;

  String? _selectedBookId;
  String? get selectedBookId => _selectedBookId;

  BookSummary? get selectedBook {
    if (_selectedBookId == null) return null;
    for (final b in _books) {
      if (b.bookId == _selectedBookId) return b;
    }
    return null;
  }

  List<PageSummary> _pages = const [];
  List<PageSummary> get pages => _pages;

  int _selectedPageNumber = 1;
  int get selectedPageNumber => _selectedPageNumber;

  List<BookOcrRunSummary> _runs = const [];
  List<BookOcrRunSummary> get runs => _runs;

  String? _selectedPrimaryRunId;
  String? get selectedPrimaryRunId => _selectedPrimaryRunId;

  PageReviewPayload? _review;
  PageReviewPayload? get review => _review;

  String? _selectedBlockId;
  String? get selectedBlockId => _selectedBlockId;

  List<CorrectionMemoryRecord> _corrections = const [];
  List<CorrectionMemoryRecord> get corrections => _corrections;

  bool _busyCorrections = false;
  bool get busyCorrections => _busyCorrections;

  List<ExportRecord> _exports = const [];
  List<ExportRecord> get exports => _exports;

  bool _usePaddle = true;
  bool get usePaddle => _usePaddle;

  bool _useTesseract = true;
  bool get useTesseract => _useTesseract;

  String? _bannerMessage;
  String? get bannerMessage => _bannerMessage;

  bool _bannerIsError = false;
  bool get bannerIsError => _bannerIsError;

  Timer? _pollTimer;
  bool _disposed = false;

  String get baseUrl => _repository.baseUrl;
  String? get username => _repository.username;
  Map<String, String> get imageHeaders => _repository.imageHeaders;

  String pageImageUrl(String bookId, int pageNumber) =>
      _repository.pageImageUrl(bookId, pageNumber);

  Uri resolveDownloadUri(String path) => _repository.resolveDownloadUri(path);

  bool get isOcrRunning => _runs.any((r) => r.isActive);

  BookOcrRunSummary? get primaryActiveRun {
    for (final r in _runs) {
      if (r.status == 'running') return r;
    }
    for (final r in _runs) {
      if (r.status == 'queued') return r;
    }
    return null;
  }

  int get approvedPagesCount =>
      _pages.where((p) => p.reviewStatus == 'approved').length;

  void setUsePaddle(bool value) {
    _usePaddle = value;
    _safeNotify();
  }

  void setUseTesseract(bool value) {
    _useTesseract = value;
    _safeNotify();
  }

  void clearBanner() {
    _bannerMessage = null;
    _bannerIsError = false;
    _safeNotify();
  }

  void setBanner(String message, {bool isError = false}) {
    _bannerMessage = message;
    _bannerIsError = isError;
    _safeNotify();
  }

  Future<void> initialize() async {
    _initializing = true;
    _safeNotify();
    try {
      await _repository.loadSavedSettings();
      await refreshAll();
    } finally {
      _initializing = false;
      _safeNotify();
    }
  }

  Future<void> updateServerSettings({
    required String baseUrl,
    String? username,
    String? password,
  }) async {
    await _repository.saveServerSettings(
      baseUrl: baseUrl,
      username: username,
      password: password,
    );
    await refreshAll();
  }

  Future<void> refreshAll() async {
    try {
      await _repository.checkHealth();
      _serverConnected = true;
    } catch (e) {
      _serverConnected = false;
      setBanner('Cannot reach server (${_repository.baseUrl}): $e',
          isError: true);
      return;
    }

    try {
      final caps = await _repository.fetchCapabilities();
      _capabilities = caps;
      if (!caps.isPaddleAvailable) _usePaddle = false;
      if (!caps.isTesseractAvailable) _useTesseract = false;
    } catch (_) {
      // Optional capabilities endpoint
    }

    await refreshBooks();
  }

  Future<void> refreshBooks() async {
    try {
      final fetched = await _repository.listBooks();
      _books = fetched;
      if (fetched.isNotEmpty) {
        final stillExists =
            fetched.any((b) => b.bookId == _selectedBookId);
        if (_selectedBookId == null || !stillExists) {
          _selectedBookId = fetched.first.bookId;
          _selectedPageNumber = 1;
          _selectedPrimaryRunId = null;
        }
        await refreshSelectedBookDetails(loadReview: true);
      } else {
        _selectedBookId = null;
        _pages = const [];
        _runs = const [];
        _review = null;
        _exports = const [];
      }
      _safeNotify();
    } catch (e) {
      setBanner('Failed to load books: $e', isError: true);
    }
  }

  Future<void> selectBook(String bookId) async {
    if (_selectedBookId == bookId) return;
    _selectedBookId = bookId;
    _selectedPageNumber = 1;
    _selectedPrimaryRunId = null;
    _selectedBlockId = null;
    _review = null;
    _safeNotify();
    await refreshSelectedBookDetails(loadReview: true);
  }

  Future<void> refreshSelectedBookDetails({bool loadReview = false}) async {
    final bookId = _selectedBookId;
    if (bookId == null) return;
    try {
      final results = await Future.wait<Object>([
        _repository.listBookPages(bookId),
        _repository.listBookOcrRuns(bookId),
        _repository.listBookExports(bookId),
      ]);
      _pages = results[0] as List<PageSummary>;
      _runs = results[1] as List<BookOcrRunSummary>;
      _exports = results[2] as List<ExportRecord>;
      _schedulePollingIfNeeded();
      _safeNotify();
      if (loadReview) {
        await refreshPageReview();
      }
    } catch (e) {
      setBanner('Failed to load book details: $e', isError: true);
    }
  }

  Future<void> refreshPageReview() async {
    final bookId = _selectedBookId;
    if (bookId == null) return;
    _busyReviewLoad = true;
    _safeNotify();
    try {
      _review = await _repository.getPageReview(
        bookId: bookId,
        pageNumber: _selectedPageNumber,
        primaryRunId: _selectedPrimaryRunId,
      );
    } catch (e) {
      setBanner('Failed to load page review: $e', isError: true);
    } finally {
      _busyReviewLoad = false;
      _safeNotify();
    }
  }

  Future<void> navigatePage(int pageNumber) async {
    final total = selectedBook?.pageCount ?? _review?.pageCount ?? 1;
    if (pageNumber < 1 || pageNumber > total) return;
    _selectedPageNumber = pageNumber;
    _selectedBlockId = null;
    _safeNotify();
    await refreshPageReview();
  }

  Future<void> selectPrimaryRun(String? runId) async {
    _selectedPrimaryRunId = runId;
    _safeNotify();
    await refreshPageReview();
  }

  void selectBlock(String? blockId) {
    _selectedBlockId = blockId;
    _safeNotify();
  }

  Future<bool> uploadPdfBook({
    required Uint8List pdfBytes,
    required String filename,
    required String title,
    String? author,
    String orthographyProfile = 'unspecified',
    bool trainingConsent = false,
  }) async {
    _busyUpload = true;
    _safeNotify();
    try {
      final res = await _repository.uploadBook(
        pdfBytes: pdfBytes,
        filename: filename,
        title: title,
        author: author,
        orthographyProfile: orthographyProfile,
        trainingConsent: trainingConsent,
      );
      _selectedBookId = res.bookId;
      _selectedPageNumber = 1;
      _selectedPrimaryRunId = null;
      await refreshBooks();
      setBanner(
        res.duplicate
            ? 'Matched existing SHA-256 for "${res.title}" (${res.pageCount} pages).'
            : 'Imported "${res.title}" (${res.pageCount} pages at 300 DPI).',
      );
      return true;
    } catch (e) {
      setBanner('Upload failed: $e', isError: true);
      return false;
    } finally {
      _busyUpload = false;
      _safeNotify();
    }
  }

  Future<void> deleteSelectedBook() async {
    final book = selectedBook;
    if (book == null) return;
    try {
      await _repository.deleteBook(book.bookId);
      setBanner('Deleted "${book.title}".');
      _selectedBookId = null;
      await refreshBooks();
    } catch (e) {
      setBanner('Delete failed: $e', isError: true);
    }
  }

  Future<void> startOcr({int? startPage, int? endPage}) async {
    final bookId = _selectedBookId;
    if (bookId == null) return;
    final engines = <String>[];
    if (_usePaddle) engines.add('paddle_ppocrv5_te');
    if (_useTesseract) engines.add('tesseract_tel_best');
    if (engines.isEmpty) {
      setBanner('Select at least one OCR engine.', isError: true);
      return;
    }

    _busyOcrStart = true;
    _safeNotify();
    try {
      final created = await _repository.startOcrRun(
        bookId: bookId,
        engines: engines,
        startPage: startPage,
        endPage: endPage,
      );
      await refreshSelectedBookDetails(loadReview: created.reusedExisting);
      if (created.reusedExisting) {
        setBanner('Reused existing completed OCR run.');
      } else {
        final labels = engines.map(formatEngineLabel).join(' + ');
        setBanner('Started OCR ($labels) for ${created.pagesTotal} page(s).');
      }
    } catch (e) {
      setBanner('Failed to start OCR: $e', isError: true);
    } finally {
      _busyOcrStart = false;
      _safeNotify();
    }
  }

  Future<void> resumeOcrRun(String runId) async {
    try {
      final resumed = await _repository.resumeOcrRun(runId);
      await refreshSelectedBookDetails(loadReview: false);
      setBanner(
        'Resumed ${formatEngineLabel(resumed.engine)} (${resumed.progressCurrent}/${resumed.progressTotal}).',
      );
    } catch (e) {
      setBanner('Failed to resume OCR: $e', isError: true);
    }
  }

  void _schedulePollingIfNeeded() {
    _pollTimer?.cancel();
    final activeIds =
        _runs.where((r) => r.isActive).map((r) => r.ocrRunId).toList();
    if (activeIds.isEmpty || _selectedBookId == null) return;

    _pollTimer = Timer(const Duration(milliseconds: 1800), () async {
      if (_disposed || _selectedBookId == null) return;
      try {
        final statuses = await Future.wait(
          activeIds.map(_repository.getOcrRunStatus),
        );
        final becameTerminal = statuses.any(
          (s) =>
              s.status == 'completed' ||
              s.status == 'partial' ||
              s.status == 'failed',
        );
        final reviewEmpty = (_review?.blocks.isEmpty ?? true);
        await refreshSelectedBookDetails(
          loadReview: becameTerminal || reviewEmpty,
        );
      } catch (_) {
        _schedulePollingIfNeeded();
      }
    });
  }

  Future<void> saveBlockEdit({
    required String blockId,
    required String editedText,
    required String action,
    String? reviewNote,
    bool addToMemory = false,
    String memoryScope = 'book_only',
    String? correctionType,
  }) async {
    _busyBlockId = blockId;
    _safeNotify();
    try {
      final res = await _repository.submitBlockEdit(
        blockId: blockId,
        editedText: editedText,
        action: action,
        reviewNote: reviewNote,
        addToCorrectionMemory: addToMemory,
        memoryScope: memoryScope,
        correctionType: correctionType,
      );
      await refreshSelectedBookDetails(loadReview: true);
      final hasMem = res['correction_memory_id'] != null;
      setBanner(
        hasMem
            ? 'Saved "$action" event and recorded correction memory candidate.'
            : 'Saved "$action" event (raw OCR preserved).',
      );
    } catch (e) {
      setBanner('Failed to save edit: $e', isError: true);
    } finally {
      _busyBlockId = null;
      _safeNotify();
    }
  }

  Future<void> acceptSuggestion({
    required ReviewBlock block,
    required CorrectionSuggestionItem suggestion,
  }) async {
    final proposed = suggestion.proposedBlockText;
    if (proposed == null || proposed.isEmpty) return;
    _busyBlockId = block.blockId;
    _safeNotify();
    try {
      await _repository.approveCorrection(suggestion.correctionId);
      await _repository.submitBlockEdit(
        blockId: block.blockId,
        editedText: proposed,
        action: 'corrected',
        reviewNote:
            'Accepted correction memory suggestion ${suggestion.correctionId}',
      );
      await refreshSelectedBookDetails(loadReview: true);
      setBanner('Applied suggestion to block and incremented approved count.');
    } catch (e) {
      setBanner('Failed to apply suggestion: $e', isError: true);
    } finally {
      _busyBlockId = null;
      _safeNotify();
    }
  }

  Future<void> rejectSuggestion(String correctionId) async {
    try {
      await _repository.rejectCorrection(correctionId);
      await refreshPageReview();
      setBanner('Recorded suggestion rejection evidence.');
    } catch (e) {
      setBanner('Failed to reject suggestion: $e', isError: true);
    }
  }

  Future<void> updatePageStatus(String reviewStatus) async {
    final bookId = _selectedBookId;
    if (bookId == null) return;
    try {
      await _repository.updatePageReviewStatus(
        bookId: bookId,
        pageNumber: _selectedPageNumber,
        reviewStatus: reviewStatus,
        primaryRunId: _review?.primaryRunId,
      );
      await refreshSelectedBookDetails(loadReview: true);
      setBanner(
        'Page $_selectedPageNumber marked "${formatReviewStatus(reviewStatus)}".',
      );
    } catch (e) {
      setBanner('Failed to update page status: $e', isError: true);
    }
  }

  Future<void> loadCorrections({
    bool bookOnly = false,
    String statusFilter = 'all',
    String? query,
  }) async {
    _busyCorrections = true;
    _safeNotify();
    try {
      _corrections = await _repository.listCorrections(
        bookId: bookOnly ? _selectedBookId : null,
        statusFilter: statusFilter,
        query: query,
      );
    } catch (e) {
      setBanner('Failed to load correction memory: $e', isError: true);
    } finally {
      _busyCorrections = false;
      _safeNotify();
    }
  }

  Future<void> toggleCorrectionStatus(CorrectionMemoryRecord record) async {
    final nextStatus = record.status == 'active' ? 'disabled' : 'active';
    try {
      await _repository.updateCorrectionStatus(
        correctionId: record.correctionId,
        status: nextStatus,
      );
      setBanner('Correction marked "$nextStatus".');
      await loadCorrections();
    } catch (e) {
      setBanner('Failed to update correction status: $e', isError: true);
    }
  }

  Future<ExportRecord?> createExport({
    required String format,
    required String layoutMode,
    required String textVersion,
    String? primaryRunId,
    String fontFamily = 'Noto Serif Telugu',
    bool includePageNumbers = true,
    bool includeTableOfContents = false,
  }) async {
    final bookId = _selectedBookId;
    if (bookId == null) return null;
    _busyExport = true;
    _safeNotify();
    try {
      final created = await _repository.createBookExport(
        bookId: bookId,
        format: format,
        layoutMode: layoutMode,
        textVersion: textVersion,
        primaryRunId: primaryRunId,
        fontFamily: fontFamily,
        includePageNumbers: includePageNumbers,
        includeTableOfContents: includeTableOfContents,
      );
      _exports = await _repository.listBookExports(bookId);
      setBanner('Export ready: ${created.filename}');
      return created;
    } catch (e) {
      setBanner('Export failed: $e', isError: true);
      return null;
    } finally {
      _busyExport = false;
      _safeNotify();
    }
  }

  void _safeNotify() {
    if (!_disposed) {
      notifyListeners();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _pollTimer?.cancel();
    super.dispose();
  }
}
