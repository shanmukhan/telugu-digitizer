import 'dart:typed_data';

import 'package:shared_preferences/shared_preferences.dart';

import '../models/api_models.dart';
import '../services/digitizer_api_service.dart';

class DigitizerRepository {
  DigitizerRepository({required this.apiService});

  static const String _prefBaseUrlKey = 'digitizer_base_url';
  static const String _prefUsernameKey = 'digitizer_auth_username';

  final DigitizerApiService apiService;
  DigitizerApiService get _apiService => apiService;

  String get baseUrl => _apiService.baseUrl;
  String? get username => _apiService.username;
  Map<String, String> get imageHeaders => _apiService.buildHeaders();

  String pageImageUrl(String bookId, int pageNumber) =>
      _apiService.pageImageUrl(bookId, pageNumber);

  Uri resolveDownloadUri(String path) => _apiService.resolveUri(path);

  Future<void> loadSavedSettings() async {
    final prefs = await SharedPreferences.getInstance();
    final savedUrl =
        prefs.getString(_prefBaseUrlKey) ?? DigitizerApiService.defaultBaseUrl;
    final savedUser = prefs.getString(_prefUsernameKey);
    _apiService.updateConfig(baseUrl: savedUrl, username: savedUser);
  }

  Future<void> saveServerSettings({
    required String baseUrl,
    String? username,
    String? password,
  }) async {
    _apiService.updateConfig(
      baseUrl: baseUrl,
      username: username,
      password: password,
    );
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_prefBaseUrlKey, _apiService.baseUrl);
    if (_apiService.username != null) {
      await prefs.setString(_prefUsernameKey, _apiService.username!);
    } else {
      await prefs.remove(_prefUsernameKey);
    }
  }

  Future<Map<String, dynamic>> checkHealth() => _apiService.checkHealth();
  Future<HostCapabilities> fetchCapabilities() =>
      _apiService.fetchCapabilities();
  Future<List<BookSummary>> listBooks() => _apiService.listBooks();

  Future<BookUploadResult> uploadBook({
    required Uint8List pdfBytes,
    required String filename,
    required String title,
    String? author,
    String orthographyProfile = 'unspecified',
    bool trainingConsent = false,
  }) =>
      _apiService.uploadBook(
        pdfBytes: pdfBytes,
        filename: filename,
        title: title,
        author: author,
        orthographyProfile: orthographyProfile,
        trainingConsent: trainingConsent,
      );

  Future<void> deleteBook(String bookId) => _apiService.deleteBook(bookId);
  Future<List<PageSummary>> listBookPages(String bookId) =>
      _apiService.listBookPages(bookId);
  Future<List<BookOcrRunSummary>> listBookOcrRuns(String bookId) =>
      _apiService.listBookOcrRuns(bookId);

  Future<OcrRunCreateResult> startOcrRun({
    required String bookId,
    required List<String> engines,
    int? startPage,
    int? endPage,
    bool forceRerun = false,
  }) =>
      _apiService.startOcrRun(
        bookId: bookId,
        engines: engines,
        startPage: startPage,
        endPage: endPage,
        forceRerun: forceRerun,
      );

  Future<BookOcrRunSummary> getOcrRunStatus(String runId) =>
      _apiService.getOcrRunStatus(runId);

  Future<BookOcrRunSummary> resumeOcrRun(String runId) =>
      _apiService.resumeOcrRun(runId);

  Future<PageReviewPayload> getPageReview({
    required String bookId,
    required int pageNumber,
    String? primaryRunId,
  }) =>
      _apiService.getPageReview(
        bookId: bookId,
        pageNumber: pageNumber,
        primaryRunId: primaryRunId,
      );

  Future<Map<String, dynamic>> submitBlockEdit({
    required String blockId,
    required String editedText,
    required String action,
    String? reviewNote,
    bool addToCorrectionMemory = false,
    String memoryScope = 'book_only',
    String? correctionType,
  }) =>
      _apiService.submitBlockEdit(
        blockId: blockId,
        editedText: editedText,
        action: action,
        reviewNote: reviewNote,
        addToCorrectionMemory: addToCorrectionMemory,
        memoryScope: memoryScope,
        correctionType: correctionType,
      );

  Future<void> updatePageReviewStatus({
    required String bookId,
    required int pageNumber,
    required String reviewStatus,
    String? primaryRunId,
  }) =>
      _apiService.updatePageReviewStatus(
        bookId: bookId,
        pageNumber: pageNumber,
        reviewStatus: reviewStatus,
        primaryRunId: primaryRunId,
      );

  Future<List<CorrectionMemoryRecord>> listCorrections({
    String? bookId,
    String? statusFilter,
    String? query,
  }) =>
      _apiService.listCorrections(
        bookId: bookId,
        statusFilter: statusFilter,
        query: query,
      );

  Future<CorrectionMemoryRecord> approveCorrection(String correctionId) =>
      _apiService.approveCorrection(correctionId);

  Future<CorrectionMemoryRecord> rejectCorrection(
    String correctionId, {
    bool disable = false,
  }) =>
      _apiService.rejectCorrection(correctionId, disable: disable);

  Future<CorrectionMemoryRecord> updateCorrectionStatus({
    required String correctionId,
    required String status,
  }) =>
      _apiService.updateCorrectionStatus(
        correctionId: correctionId,
        status: status,
      );

  Future<List<ExportRecord>> listBookExports(String bookId) =>
      _apiService.listBookExports(bookId);

  Future<ExportRecord> createBookExport({
    required String bookId,
    required String format,
    required String layoutMode,
    required String textVersion,
    String? primaryRunId,
    String fontFamily = 'Noto Serif Telugu',
    bool includePageNumbers = true,
    bool includeTableOfContents = false,
  }) =>
      _apiService.createBookExport(
        bookId: bookId,
        format: format,
        layoutMode: layoutMode,
        textVersion: textVersion,
        primaryRunId: primaryRunId,
        fontFamily: fontFamily,
        includePageNumbers: includePageNumbers,
        includeTableOfContents: includeTableOfContents,
      );
}
