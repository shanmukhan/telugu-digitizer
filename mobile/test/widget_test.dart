import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:telugu_digitizer_mobile/data/models/api_models.dart';
import 'package:telugu_digitizer_mobile/data/repositories/digitizer_repository.dart';
import 'package:telugu_digitizer_mobile/data/services/digitizer_api_service.dart';
import 'package:telugu_digitizer_mobile/main.dart';
import 'package:telugu_digitizer_mobile/ui/features/studio/view_models/studio_view_model.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
  });

  test('BookSummary and PageReviewPayload serialize and deserialize cleanly', () {
    final sampleBookJson = <String, dynamic>{
      'book_id': 'b-1',
      'title': 'తెలుగు పుస్తకం',
      'author': 'Test Author',
      'publisher': null,
      'publication_year': 2026,
      'language_code': 'te',
      'orthography_profile': 'modern_standard',
      'original_filename': 'telugu.pdf',
      'source_sha256': 'sha256-abc',
      'page_count': 4,
      'rights_status': 'unknown',
      'training_consent': true,
      'created_at': '2026-11-24T00:00:00Z',
      'updated_at': '2026-11-24T00:00:00Z',
      'scanned_pages_count': 3,
      'digital_text_pages_count': 1,
      'mixed_pages_count': 0,
    };

    final book = BookSummary.fromJson(sampleBookJson);
    expect(book.bookId, 'b-1');
    expect(book.title, 'తెలుగు పుస్తకం');
    expect(book.ocrTargetPagesCount, 3);
    expect(book.toJson()['title'], 'తెలుగు పుస్తకం');
  });

  testWidgets(
    'Mobile app loads library, navigates to Page Review, edits Telugu block, and views Export tab',
    (WidgetTester tester) async {
      String currentLineText = 'తెలుగు పస్తకం';

      final mockClient = MockClient((http.Request request) async {
        final path = request.url.path;
        if (path.endsWith('/api/v1/health')) {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'status': 'ok',
                'database': 'connected',
                'workspace_dir': '/workspace',
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (path.endsWith('/api/v1/capabilities')) {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'platform_machine': 'aarch64',
                'auth_enabled': false,
                'max_upload_mb': 200,
                'max_pdf_pages': 1000,
                'engines': {
                  'paddle_ppocrv5_te': {
                    'available': true,
                    'reason': null,
                    'model_id': 'PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec',
                  },
                  'tesseract_tel_best': {
                    'available': true,
                    'reason': null,
                    'model_id': 'tesseract-5-tel-best',
                  },
                },
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (path.endsWith('/api/v1/books')) {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'items': [
                  {
                    'book_id': 'b-1',
                    'title': 'యువ సంపుటి',
                    'author': 'Author',
                    'publisher': null,
                    'publication_year': 2026,
                    'language_code': 'te',
                    'orthography_profile': 'unspecified',
                    'original_filename': 'yuva.pdf',
                    'source_sha256': 'abc',
                    'page_count': 2,
                    'rights_status': 'unknown',
                    'training_consent': false,
                    'created_at': '2026-11-24T00:00:00Z',
                    'updated_at': '2026-11-24T00:00:00Z',
                    'scanned_pages_count': 2,
                    'digital_text_pages_count': 0,
                    'mixed_pages_count': 0,
                  }
                ],
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (path.endsWith('/api/v1/books/b-1/pages')) {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'book_id': 'b-1',
                'page_count': 2,
                'items': [
                  {
                    'page_id': 'p-1',
                    'page_number': 1,
                    'page_kind': 'scanned_image',
                    'width_px': 900,
                    'height_px': 330,
                    'render_dpi': 300,
                    'extracted_text_char_count': 0,
                    'image_coverage_ratio': 1.0,
                    'review_status': 'in_review',
                    'has_image': true,
                  }
                ],
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (path.endsWith('/api/v1/books/b-1/ocr-runs')) {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'book_id': 'b-1',
                'items': [
                  {
                    'ocr_run_id': 'run-1',
                    'engine': 'paddleocr',
                    'model_id': 'PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec',
                    'status': 'completed',
                    'progress_current': 2,
                    'progress_total': 2,
                    'config': {'start_page': 1, 'end_page': 2},
                    'created_at': '2026-11-24T00:00:00Z',
                    'completed_at': '2026-11-24T00:01:00Z',
                  }
                ],
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (path.endsWith('/api/v1/books/b-1/exports')) {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'book_id': 'b-1',
                'items': [
                  {
                    'export_id': 'exp-1',
                    'book_id': 'b-1',
                    'transcript_version_id': null,
                    'format': 'docx',
                    'layout_mode': 'page_preserving',
                    'text_version': 'human_approved',
                    'font_family': 'Noto Serif Telugu',
                    'filename': 'yuva_page-preserving.docx',
                    'status': 'completed',
                    'is_fully_reviewed': true,
                    'validation': {'passed': true},
                    'download_url': '/api/v1/exports/exp-1/download',
                    'manifest_url': '/api/v1/exports/exp-1/manifest',
                    'created_at': '2026-11-24T00:02:00Z',
                  }
                ],
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (path.endsWith('/api/v1/books/b-1/pages/1/review')) {
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'book_id': 'b-1',
                'book_title': 'యువ సంపుటి',
                'page_id': 'p-1',
                'page_number': 1,
                'page_count': 2,
                'page_kind': 'scanned_image',
                'width_px': 900,
                'height_px': 330,
                'render_dpi': 300,
                'review_status': 'in_review',
                'digital_text_content': null,
                'available_runs': [
                  {
                    'ocr_run_id': 'run-1',
                    'engine': 'paddleocr',
                    'model_id': 'PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec',
                    'status': 'completed',
                    'progress_current': 2,
                    'progress_total': 2,
                    'config': <String, dynamic>{},
                    'created_at': '2026-11-24T00:00:00Z',
                    'completed_at': '2026-11-24T00:01:00Z',
                  }
                ],
                'primary_run_id': 'run-1',
                'primary_engine': 'paddleocr',
                'primary_model_id':
                    'PP-OCRv5_server_det+te_PP-OCRv5_mobile_rec',
                'comparator_run_id': null,
                'comparator_engine': null,
                'blocks': [
                  {
                    'block_id': 'blk-1',
                    'block_index': 0,
                    'reading_order': 0,
                    'block_type': 'text_line',
                    'raw_text': 'తెలుగు పస్తకం',
                    'normalized_text': 'తెలుగు పస్తకం',
                    'current_text': currentLineText,
                    'is_edited': currentLineText != 'తెలుగు పస్తకం',
                    'latest_action': null,
                    'confidence': 0.72,
                    'low_confidence_flag': true,
                    'disagreement_flag': false,
                    'short_or_empty_flag': false,
                    'comparator_text': null,
                    'polygon': [
                      [10.0, 10.0],
                      [200.0, 10.0],
                      [200.0, 50.0],
                      [10.0, 50.0],
                    ],
                    'bbox': [10.0, 10.0, 200.0, 50.0],
                    'suggestions': <Object>[],
                    'edit_history': <Object>[],
                  }
                ],
              }),
            ),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        if (path.endsWith('/api/v1/ocr-blocks/blk-1/edits') &&
            request.method == 'POST') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          currentLineText = body['edited_text'] as String;
          return http.Response.bytes(
            utf8.encode(
              jsonEncode({
                'edit_id': 'ed-1',
                'block_id': 'blk-1',
                'raw_text': 'తెలుగు పస్తకం',
                'previous_text': 'తెలుగు పస్తకం',
                'current_text': currentLineText,
                'action': body['action'],
                'page_review_status': 'in_review',
                'correction_memory_id': null,
                'created_at': '2026-11-24T00:03:00Z',
              }),
            ),
            201,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('Not Found', 404);
      });

      final apiService = DigitizerApiService(client: mockClient);
      final repository = DigitizerRepository(apiService: apiService);
      final viewModel = StudioViewModel(repository: repository);
      await viewModel.initialize();

      await tester.pumpWidget(TeluguDigitizerMobileApp(viewModel: viewModel));
      await tester.pumpAndSettle();

      // 1. Library tab displays loaded book and Online status pill
      expect(find.text('Online'), findsOneWidget);
      expect(find.text('యువ సంపుటి'), findsAtLeastNWidgets(1));
      expect(find.text('Test Pages 1–5'), findsOneWidget);

      // 2. Navigate to Page Review tab via bottom NavigationBar
      await tester.tap(find.text('Page Review'));
      await tester.pumpAndSettle();

      expect(find.text('Raw OCR: తెలుగు పస్తకం'), findsOneWidget);

      // 3. Edit Telugu line text and tap Save Correction
      final lineField = find.widgetWithText(TextField, 'తెలుగు పస్తకం');
      expect(lineField, findsOneWidget);
      await tester.enterText(lineField, 'తెలుగు పుస్తకం');
      await tester.pumpAndSettle();

      final saveBtn = find.text('Save Correction');
      await tester.drag(find.byType(ListView), const Offset(0, -140));
      await tester.pumpAndSettle();
      await tester.tap(saveBtn);
      await tester.pumpAndSettle();

      expect(viewModel.review?.blocks.first.currentText, 'తెలుగు పుస్తకం');
    },
  );
}
