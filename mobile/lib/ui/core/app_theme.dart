import 'package:flutter/material.dart';

class AppTheme {
  static const Color primary = Color(0xFF0F6B5C);
  static const Color primaryDark = Color(0xFF0A4A40);
  static const Color primarySoft = Color(0xFFE5F3EF);
  static const Color background = Color(0xFFF6F2E8);
  static const Color surface = Color(0xFFFFFFFF);
  static const Color surfaceMuted = Color(0xFFEFE9DA);
  static const Color ink = Color(0xFF1B2B28);
  static const Color inkMuted = Color(0xFF52625E);
  static const Color border = Color(0xFFDDD6C3);
  static const Color warnBg = Color(0xFFFEF3C7);
  static const Color warnBorder = Color(0xFFD97706);
  static const Color warnInk = Color(0xFF92400E);
  static const Color okBg = Color(0xFFDCFCE7);
  static const Color okBorder = Color(0xFF16A34A);
  static const Color okInk = Color(0xFF166534);
  static const Color dangerBg = Color(0xFFFEE2E2);
  static const Color dangerBorder = Color(0xFFDC2626);
  static const Color dangerInk = Color(0xFF991B1B);

  static const List<String> teluguFontFallback = <String>[
    'Kohinoor Telugu',
    'Noto Serif Telugu',
    'Noto Sans Telugu',
    'Telugu Sangam MN',
  ];

  static ThemeData lightTheme() {
    final colorScheme = ColorScheme.fromSeed(
      seedColor: primary,
      primary: primary,
      surface: surface,
      brightness: Brightness.light,
    );
    return ThemeData(
      useMaterial3: true,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: background,
      appBarTheme: const AppBarTheme(
        backgroundColor: primaryDark,
        foregroundColor: Colors.white,
        elevation: 0,
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        color: surface,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: const BorderSide(color: border),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: surface,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: 12,
          vertical: 10,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: primary, width: 2),
        ),
      ),
    );
  }
}

String formatEngineLabel(String? engine) {
  switch ((engine ?? '').toLowerCase()) {
    case 'paddleocr':
    case 'paddle_ppocrv5_te':
      return 'PaddleOCR PP-OCRv5';
    case 'tesseract':
    case 'tesseract_tel_best':
      return 'Tesseract 5 Telugu';
    default:
      return (engine == null || engine.isEmpty) ? 'OCR Engine' : engine;
  }
}

String formatPageKind(String kind) {
  switch (kind) {
    case 'scanned_image':
      return 'Scanned';
    case 'digital_text':
      return 'Digital Text';
    case 'mixed':
      return 'Mixed';
    default:
      return kind.replaceAll('_', ' ');
  }
}

String formatReviewStatus(String status) {
  switch (status) {
    case 'not_started':
      return 'Pending Review';
    case 'in_review':
      return 'In Review';
    case 'approved':
      return 'Approved';
    case 'needs_attention':
      return 'Needs Attention';
    default:
      return status.replaceAll('_', ' ');
  }
}

String formatLayoutMode(String mode) {
  switch (mode) {
    case 'page_preserving':
      return 'Page-Preserving';
    case 'editable_flow':
      return 'Editable Flow';
    case 'raw_ocr':
      return 'Raw OCR';
    case 'human_approved':
      return 'Human-Reviewed';
    default:
      return mode.replaceAll('_', ' ');
  }
}

const List<({String glyph, String label})> teluguQuickCombiningSigns = [
  (glyph: 'ా', label: 'aa'),
  (glyph: 'ి', label: 'i'),
  (glyph: 'ీ', label: 'ii'),
  (glyph: 'ు', label: 'u'),
  (glyph: 'ూ', label: 'uu'),
  (glyph: 'ృ', label: 'ru'),
  (glyph: 'ె', label: 'e'),
  (glyph: 'ే', label: 'ee'),
  (glyph: 'ై', label: 'ai'),
  (glyph: 'ొ', label: 'o'),
  (glyph: 'ో', label: 'oo'),
  (glyph: 'ౌ', label: 'au'),
  (glyph: 'ం', label: 'M'),
  (glyph: 'ః', label: 'H'),
  (glyph: '్', label: 'virama'),
];
