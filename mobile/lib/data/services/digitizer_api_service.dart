import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../models/api_models.dart';

/// Top-level isolate parser for large PageReviewPayload JSON responses.
PageReviewPayload parsePageReviewJson(String body) {
  final map = jsonDecode(body) as Map<String, dynamic>;
  return PageReviewPayload.fromJson(map);
}

/// Top-level isolate parser for PageSummary lists.
List<PageSummary> parsePageSummariesJson(String body) {
  final map = jsonDecode(body) as Map<String, dynamic>;
  final items = (map['items'] as List<dynamic>?) ?? const [];
  return items
      .whereType<Map<String, dynamic>>()
      .map(PageSummary.fromJson)
      .toList();
}

class DigitizerApiService {
  DigitizerApiService({
    http.Client? client,
    String baseUrl = defaultBaseUrl,
    String? username,
    String? password,
  })  : _client = client ?? http.Client(),
        _baseUrl = normalizeBaseUrl(baseUrl) {
    _username = username;
    _password = password;
  }

  static const String defaultBaseUrl = 'https://lahari.org/telugu';

  final http.Client _client;
  String _baseUrl;
  String? _username;
  String? _password;

  String get baseUrl => _baseUrl;
  String? get username => _username;
  bool get hasCredentials =>
      (_username?.isNotEmpty ?? false) && (_password?.isNotEmpty ?? false);

  static String normalizeBaseUrl(String raw) {
    final trimmed = raw.trim();
    if (trimmed.isEmpty) return defaultBaseUrl;
    return trimmed.endsWith('/')
        ? trimmed.substring(0, trimmed.length - 1)
        : trimmed;
  }

  void updateConfig({
    required String baseUrl,
    String? username,
    String? password,
  }) {
    _baseUrl = normalizeBaseUrl(baseUrl);
    _username = (username?.trim().isEmpty ?? true) ? null : username!.trim();
    _password = (password?.isEmpty ?? true) ? null : password;
  }

  Uri resolveUri(String path, [Map<String, String>? queryParameters]) {
    final cleanPath = path.startsWith('/') ? path : '/$path';
    final rawUri = Uri.parse('$_baseUrl$cleanPath');
    if (queryParameters == null || queryParameters.isEmpty) {
      return rawUri;
    }
    return rawUri.replace(queryParameters: queryParameters);
  }

  Map<String, String> buildHeaders({bool jsonBody = false}) {
    final headers = <String, String>{
      HttpHeaders.acceptHeader: 'application/json',
    };
    if (jsonBody) {
      headers[HttpHeaders.contentTypeHeader] = 'application/json; charset=UTF-8';
    }
    if (hasCredentials) {
      final token = base64Encode(utf8.encode('$_username:$_password'));
      headers[HttpHeaders.authorizationHeader] = 'Basic $token';
    }
    return headers;
  }

  Never _throwError(http.Response response) {
    String code = 'HTTP_${response.statusCode}';
    String message = response.reasonPhrase ?? 'Request failed';
    if (response.body.isNotEmpty) {
      try {
        final decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic> &&
            decoded['error'] is Map<String, dynamic>) {
          final err = decoded['error'] as Map<String, dynamic>;
          code = err['code'] as String? ?? code;
          message = err['message'] as String? ?? message;
        } else {
          message = response.body;
        }
      } catch (_) {
        message = response.body;
      }
    }
    throw ApiException(
      statusCode: response.statusCode,
      code: code,
      message: message,
    );
  }

  Future<Map<String, dynamic>> checkHealth() async {
    final res = await _client.get(
      resolveUri('/api/v1/health'),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200) {
      return jsonDecode(res.body) as Map<String, dynamic>;
    }
    _throwError(res);
  }

  Future<HostCapabilities> fetchCapabilities() async {
    final res = await _client.get(
      resolveUri('/api/v1/capabilities'),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200) {
      return HostCapabilities.fromJson(
        jsonDecode(res.body) as Map<String, dynamic>,
      );
    }
    _throwError(res);
  }

  Future<List<BookSummary>> listBooks() async {
    final res = await _client.get(
      resolveUri('/api/v1/books'),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200) {
      final map = jsonDecode(res.body) as Map<String, dynamic>;
      final items = (map['items'] as List<dynamic>?) ?? const [];
      return items
          .whereType<Map<String, dynamic>>()
          .map(BookSummary.fromJson)
          .toList();
    }
    _throwError(res);
  }

  Future<BookUploadResult> uploadBook({
    required Uint8List pdfBytes,
    required String filename,
    required String title,
    String? author,
    String orthographyProfile = 'unspecified',
    bool trainingConsent = false,
  }) async {
    final req = http.MultipartRequest('POST', resolveUri('/api/v1/books'));
    req.headers.addAll(buildHeaders());
    req.fields['title'] = title;
    if (author != null && author.trim().isNotEmpty) {
      req.fields['author'] = author.trim();
    }
    req.fields['orthography_profile'] = orthographyProfile;
    req.fields['training_consent'] = trainingConsent.toString();
    req.files.add(
      http.MultipartFile.fromBytes(
        'file',
        pdfBytes,
        filename: filename,
      ),
    );
    final streamed = await _client.send(req);
    final res = await http.Response.fromStream(streamed);
    if (res.statusCode == 200 || res.statusCode == 201) {
      return BookUploadResult.fromJson(
        jsonDecode(res.body) as Map<String, dynamic>,
      );
    }
    _throwError(res);
  }

  Future<void> deleteBook(String bookId) async {
    final res = await _client.delete(
      resolveUri('/api/v1/books/$bookId'),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200 || res.statusCode == 204) {
      return;
    }
    _throwError(res);
  }

  Future<List<PageSummary>> listBookPages(String bookId) async {
    final res = await _client.get(
      resolveUri('/api/v1/books/$bookId/pages'),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200) {
      if (res.body.length > 16384) {
        return compute(parsePageSummariesJson, res.body);
      }
      return parsePageSummariesJson(res.body);
    }
    _throwError(res);
  }

  Future<List<BookOcrRunSummary>> listBookOcrRuns(String bookId) async {
    final res = await _client.get(
      resolveUri('/api/v1/books/$bookId/ocr-runs'),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200) {
      final map = jsonDecode(res.body) as Map<String, dynamic>;
      final items = (map['items'] as List<dynamic>?) ?? const [];
      return items
          .whereType<Map<String, dynamic>>()
          .map(BookOcrRunSummary.fromJson)
          .toList();
    }
    _throwError(res);
  }

  Future<OcrRunCreateResult> startOcrRun({
    required String bookId,
    required List<String> engines,
    int? startPage,
    int? endPage,
    bool forceRerun = false,
    String preprocessingProfile = 'none',
  }) async {
    final payload = <String, dynamic>{
      'engines': engines,
      'page_range': (startPage != null && endPage != null)
          ? {'start': startPage, 'end': endPage}
          : null,
      'render_dpi': 300,
      'preprocessing_profile': preprocessingProfile,
      'force_rerun': forceRerun,
    };
    final res = await _client.post(
      resolveUri('/api/v1/books/$bookId/ocr-runs'),
      headers: buildHeaders(jsonBody: true),
      body: jsonEncode(payload),
    );
    if (res.statusCode == 200 || res.statusCode == 202) {
      return OcrRunCreateResult.fromJson(
        jsonDecode(res.body) as Map<String, dynamic>,
      );
    }
    _throwError(res);
  }

  Future<BookOcrRunSummary> getOcrRunStatus(String runId) async {
    final res = await _client.get(
      resolveUri('/api/v1/ocr-runs/$runId'),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200) {
      return BookOcrRunSummary.fromJson(
        jsonDecode(res.body) as Map<String, dynamic>,
      );
    }
    _throwError(res);
  }

  Future<BookOcrRunSummary> resumeOcrRun(String runId) async {
    final res = await _client.post(
      resolveUri('/api/v1/ocr-runs/$runId/resume'),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200 || res.statusCode == 202) {
      return BookOcrRunSummary.fromJson(
        jsonDecode(res.body) as Map<String, dynamic>,
      );
    }
    _throwError(res);
  }

  Future<BookOcrRunSummary> cancelOcrRun(String runId) async {
    final res = await _client.post(
      resolveUri('/api/v1/ocr-runs/$runId/cancel'),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200 || res.statusCode == 202) {
      return BookOcrRunSummary.fromJson(
        jsonDecode(res.body) as Map<String, dynamic>,
      );
    }
    _throwError(res);
  }

  Future<PageReviewPayload> getPageReview({
    required String bookId,
    required int pageNumber,
    String? primaryRunId,
  }) async {
    final query = <String, String>{};
    if (primaryRunId != null && primaryRunId.isNotEmpty) {
      query['primary_run_id'] = primaryRunId;
    }
    final res = await _client.get(
      resolveUri('/api/v1/books/$bookId/pages/$pageNumber/review', query),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200) {
      if (res.body.length > 16384) {
        return compute(parsePageReviewJson, res.body);
      }
      return parsePageReviewJson(res.body);
    }
    _throwError(res);
  }

  Future<Map<String, dynamic>> submitBlockEdit({
    required String blockId,
    required String editedText,
    required String action,
    String? blockRole,
    String? reviewNote,
    bool addToCorrectionMemory = false,
    String memoryScope = 'book_only',
    String? correctionType,
  }) async {
    final payload = <String, dynamic>{
      'edited_text': editedText,
      'action': action,
      if (blockRole != null && blockRole.isNotEmpty) 'block_role': blockRole,
      'review_note': ?reviewNote,
      'add_to_correction_memory': addToCorrectionMemory,
      'memory_scope': memoryScope,
      if (correctionType != null && correctionType.isNotEmpty)
        'correction_type': correctionType,
    };
    final res = await _client.post(
      resolveUri('/api/v1/ocr-blocks/$blockId/edits'),
      headers: buildHeaders(jsonBody: true),
      body: jsonEncode(payload),
    );
    if (res.statusCode == 200 || res.statusCode == 201) {
      return jsonDecode(res.body) as Map<String, dynamic>;
    }
    _throwError(res);
  }

  Future<void> updatePageReviewStatus({
    required String bookId,
    required int pageNumber,
    required String reviewStatus,
    String? primaryRunId,
  }) async {
    final res = await _client.patch(
      resolveUri('/api/v1/books/$bookId/pages/$pageNumber/review-status'),
      headers: buildHeaders(jsonBody: true),
      body: jsonEncode({
        'review_status': reviewStatus,
        'primary_run_id': primaryRunId,
      }),
    );
    if (res.statusCode == 200) {
      return;
    }
    _throwError(res);
  }

  Future<List<CorrectionMemoryRecord>> listCorrections({
    String? bookId,
    String? statusFilter,
    String? query,
  }) async {
    final params = <String, String>{};
    if (bookId != null && bookId.isNotEmpty) {
      params['book_id'] = bookId;
    }
    if (statusFilter != null &&
        statusFilter.isNotEmpty &&
        statusFilter != 'all') {
      params['status_filter'] = statusFilter;
    }
    if (query != null && query.trim().isNotEmpty) {
      params['q'] = query.trim();
    }
    final res = await _client.get(
      resolveUri('/api/v1/corrections', params),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200) {
      final map = jsonDecode(res.body) as Map<String, dynamic>;
      final items = (map['items'] as List<dynamic>?) ?? const [];
      return items
          .whereType<Map<String, dynamic>>()
          .map(CorrectionMemoryRecord.fromJson)
          .toList();
    }
    _throwError(res);
  }

  Future<CorrectionMemoryRecord> approveCorrection(String correctionId) async {
    final res = await _client.post(
      resolveUri('/api/v1/corrections/$correctionId/approve'),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200) {
      return CorrectionMemoryRecord.fromJson(
        jsonDecode(res.body) as Map<String, dynamic>,
      );
    }
    _throwError(res);
  }

  Future<CorrectionMemoryRecord> rejectCorrection(
    String correctionId, {
    bool disable = false,
  }) async {
    final res = await _client.post(
      resolveUri('/api/v1/corrections/$correctionId/reject'),
      headers: buildHeaders(jsonBody: true),
      body: jsonEncode({'disable': disable}),
    );
    if (res.statusCode == 200) {
      return CorrectionMemoryRecord.fromJson(
        jsonDecode(res.body) as Map<String, dynamic>,
      );
    }
    _throwError(res);
  }

  Future<CorrectionMemoryRecord> updateCorrectionStatus({
    required String correctionId,
    required String status,
    String? scope,
  }) async {
    final res = await _client.patch(
      resolveUri('/api/v1/corrections/$correctionId/status'),
      headers: buildHeaders(jsonBody: true),
      body: jsonEncode({
        'status': status,
        if (scope != null && scope.isNotEmpty) 'scope': scope,
      }),
    );
    if (res.statusCode == 200) {
      return CorrectionMemoryRecord.fromJson(
        jsonDecode(res.body) as Map<String, dynamic>,
      );
    }
    _throwError(res);
  }

  Future<List<ExportRecord>> listBookExports(String bookId) async {
    final res = await _client.get(
      resolveUri('/api/v1/books/$bookId/exports'),
      headers: buildHeaders(),
    );
    if (res.statusCode == 200) {
      final map = jsonDecode(res.body) as Map<String, dynamic>;
      final items = (map['items'] as List<dynamic>?) ?? const [];
      return items
          .whereType<Map<String, dynamic>>()
          .map(ExportRecord.fromJson)
          .toList();
    }
    _throwError(res);
  }

  Future<ExportRecord> createBookExport({
    required String bookId,
    required String format,
    required String layoutMode,
    required String textVersion,
    String? primaryRunId,
    String fontFamily = 'Noto Serif Telugu',
    bool includePageNumbers = true,
    bool includeTableOfContents = false,
  }) async {
    final res = await _client.post(
      resolveUri('/api/v1/books/$bookId/exports'),
      headers: buildHeaders(jsonBody: true),
      body: jsonEncode({
        'format': format,
        'layout_mode': layoutMode,
        'text_version': textVersion,
        'primary_run_id': primaryRunId,
        'font_family': fontFamily,
        'body_font_size': 12,
        'include_page_numbers': includePageNumbers,
        'include_table_of_contents': includeTableOfContents,
      }),
    );
    if (res.statusCode == 200 || res.statusCode == 201) {
      return ExportRecord.fromJson(
        jsonDecode(res.body) as Map<String, dynamic>,
      );
    }
    _throwError(res);
  }

  String pageImageUrl(String bookId, int pageNumber) =>
      resolveUri('/api/v1/books/$bookId/pages/$pageNumber/image').toString();
}
