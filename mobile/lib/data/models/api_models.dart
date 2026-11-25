/// Strongly-typed API and domain models for Telugu Book Digitizer mobile client.
library;

class ApiException implements Exception {
  const ApiException({
    required this.statusCode,
    required this.code,
    required this.message,
  });

  final int statusCode;
  final String code;
  final String message;

  @override
  String toString() => '$code ($statusCode): $message';
}

class EngineCapability {
  const EngineCapability({
    required this.available,
    required this.modelId,
    this.reason,
  });

  final bool available;
  final String? reason;
  final String modelId;

  factory EngineCapability.fromJson(Map<String, dynamic> json) {
    return EngineCapability(
      available: json['available'] as bool? ?? false,
      reason: json['reason'] as String?,
      modelId: json['model_id'] as String? ?? '',
    );
  }
}

class HostCapabilities {
  const HostCapabilities({
    required this.platformMachine,
    required this.authEnabled,
    required this.maxUploadMb,
    required this.maxPdfPages,
    required this.engines,
  });

  final String platformMachine;
  final bool authEnabled;
  final int maxUploadMb;
  final int maxPdfPages;
  final Map<String, EngineCapability> engines;

  bool get isPaddleAvailable =>
      engines['paddle_ppocrv5_te']?.available ?? true;

  bool get isTesseractAvailable =>
      engines['tesseract_tel_best']?.available ?? true;

  factory HostCapabilities.fromJson(Map<String, dynamic> json) {
    final rawEngines = json['engines'] as Map<String, dynamic>? ?? const {};
    final mapped = <String, EngineCapability>{};
    for (final entry in rawEngines.entries) {
      if (entry.value is Map<String, dynamic>) {
        mapped[entry.key] = EngineCapability.fromJson(
          entry.value as Map<String, dynamic>,
        );
      }
    }
    return HostCapabilities(
      platformMachine: json['platform_machine'] as String? ?? 'unknown',
      authEnabled: json['auth_enabled'] as bool? ?? false,
      maxUploadMb: (json['max_upload_mb'] as num?)?.toInt() ?? 200,
      maxPdfPages: (json['max_pdf_pages'] as num?)?.toInt() ?? 1000,
      engines: mapped,
    );
  }
}

class BookSummary {
  const BookSummary({
    required this.bookId,
    required this.title,
    required this.author,
    required this.publisher,
    required this.publicationYear,
    required this.languageCode,
    required this.orthographyProfile,
    required this.originalFilename,
    required this.sourceSha256,
    required this.pageCount,
    required this.rightsStatus,
    required this.trainingConsent,
    required this.createdAt,
    required this.updatedAt,
    required this.scannedPagesCount,
    required this.digitalTextPagesCount,
    required this.mixedPagesCount,
  });

  final String bookId;
  final String title;
  final String? author;
  final String? publisher;
  final int? publicationYear;
  final String languageCode;
  final String orthographyProfile;
  final String originalFilename;
  final String sourceSha256;
  final int pageCount;
  final String rightsStatus;
  final bool trainingConsent;
  final String createdAt;
  final String updatedAt;
  final int scannedPagesCount;
  final int digitalTextPagesCount;
  final int mixedPagesCount;

  int get ocrTargetPagesCount => scannedPagesCount + mixedPagesCount;

  factory BookSummary.fromJson(Map<String, dynamic> json) {
    return BookSummary(
      bookId: json['book_id'] as String,
      title: json['title'] as String? ?? 'Untitled',
      author: json['author'] as String?,
      publisher: json['publisher'] as String?,
      publicationYear: (json['publication_year'] as num?)?.toInt(),
      languageCode: json['language_code'] as String? ?? 'te',
      orthographyProfile: json['orthography_profile'] as String? ?? 'unspecified',
      originalFilename: json['original_filename'] as String? ?? 'document.pdf',
      sourceSha256: json['source_sha256'] as String? ?? '',
      pageCount: (json['page_count'] as num?)?.toInt() ?? 0,
      rightsStatus: json['rights_status'] as String? ?? 'unknown',
      trainingConsent: json['training_consent'] as bool? ?? false,
      createdAt: json['created_at'] as String? ?? '',
      updatedAt: json['updated_at'] as String? ?? '',
      scannedPagesCount: (json['scanned_pages_count'] as num?)?.toInt() ?? 0,
      digitalTextPagesCount:
          (json['digital_text_pages_count'] as num?)?.toInt() ?? 0,
      mixedPagesCount: (json['mixed_pages_count'] as num?)?.toInt() ?? 0,
    );
  }

  Map<String, dynamic> toJson() {
    return {
      'book_id': bookId,
      'title': title,
      'author': author,
      'publisher': publisher,
      'publication_year': publicationYear,
      'language_code': languageCode,
      'orthography_profile': orthographyProfile,
      'original_filename': originalFilename,
      'source_sha256': sourceSha256,
      'page_count': pageCount,
      'rights_status': rightsStatus,
      'training_consent': trainingConsent,
      'created_at': createdAt,
      'updated_at': updatedAt,
      'scanned_pages_count': scannedPagesCount,
      'digital_text_pages_count': digitalTextPagesCount,
      'mixed_pages_count': mixedPagesCount,
    };
  }
}

class BookUploadResult {
  const BookUploadResult({
    required this.bookId,
    required this.title,
    required this.pageCount,
    required this.sourceSha256,
    required this.status,
    required this.duplicate,
  });

  final String bookId;
  final String title;
  final int pageCount;
  final String sourceSha256;
  final String status;
  final bool duplicate;

  factory BookUploadResult.fromJson(Map<String, dynamic> json) {
    return BookUploadResult(
      bookId: json['book_id'] as String,
      title: json['title'] as String? ?? '',
      pageCount: (json['page_count'] as num?)?.toInt() ?? 0,
      sourceSha256: json['source_sha256'] as String? ?? '',
      status: json['status'] as String? ?? 'uploaded',
      duplicate: json['duplicate'] as bool? ?? false,
    );
  }
}

class PageSummary {
  const PageSummary({
    required this.pageId,
    required this.pageNumber,
    required this.pageKind,
    required this.widthPx,
    required this.heightPx,
    required this.renderDpi,
    required this.extractedTextCharCount,
    required this.imageCoverageRatio,
    required this.reviewStatus,
    required this.hasImage,
  });

  final String pageId;
  final int pageNumber;
  final String pageKind;
  final int? widthPx;
  final int? heightPx;
  final int? renderDpi;
  final int extractedTextCharCount;
  final double imageCoverageRatio;
  final String reviewStatus;
  final bool hasImage;

  factory PageSummary.fromJson(Map<String, dynamic> json) {
    return PageSummary(
      pageId: json['page_id'] as String,
      pageNumber: (json['page_number'] as num).toInt(),
      pageKind: json['page_kind'] as String? ?? 'scanned_image',
      widthPx: (json['width_px'] as num?)?.toInt(),
      heightPx: (json['height_px'] as num?)?.toInt(),
      renderDpi: (json['render_dpi'] as num?)?.toInt(),
      extractedTextCharCount:
          (json['extracted_text_char_count'] as num?)?.toInt() ?? 0,
      imageCoverageRatio:
          (json['image_coverage_ratio'] as num?)?.toDouble() ?? 0.0,
      reviewStatus: json['review_status'] as String? ?? 'not_started',
      hasImage: json['has_image'] as bool? ?? false,
    );
  }
}

class BookOcrRunSummary {
  const BookOcrRunSummary({
    required this.ocrRunId,
    required this.engine,
    required this.modelId,
    required this.status,
    required this.progressCurrent,
    required this.progressTotal,
    required this.startedAt,
    required this.completedAt,
    required this.errorSummary,
    required this.config,
    required this.createdAt,
  });

  final String ocrRunId;
  final String? engine;
  final String? modelId;
  final String status;
  final int progressCurrent;
  final int progressTotal;
  final String? startedAt;
  final String? completedAt;
  final String? errorSummary;
  final Map<String, dynamic> config;
  final String createdAt;

  bool get isActive => status == 'running' || status == 'queued';
  bool get isResumable => status == 'partial' || status == 'failed';

  factory BookOcrRunSummary.fromJson(Map<String, dynamic> json) {
    return BookOcrRunSummary(
      ocrRunId: json['ocr_run_id'] as String,
      engine: json['engine'] as String?,
      modelId: json['model_id'] as String?,
      status: json['status'] as String? ?? 'queued',
      progressCurrent: (json['progress_current'] as num?)?.toInt() ?? 0,
      progressTotal: (json['progress_total'] as num?)?.toInt() ?? 0,
      startedAt: json['started_at'] as String?,
      completedAt: json['completed_at'] as String?,
      errorSummary: json['error_summary'] as String?,
      config: (json['config'] as Map<String, dynamic>?) ?? const {},
      createdAt: json['created_at'] as String? ?? '',
    );
  }
}

class OcrRunCreateResult {
  const OcrRunCreateResult({
    required this.ocrRunId,
    required this.ocrRunIds,
    required this.jobId,
    required this.status,
    required this.pagesTotal,
    required this.reusedExisting,
  });

  final String ocrRunId;
  final List<String> ocrRunIds;
  final String jobId;
  final String status;
  final int pagesTotal;
  final bool reusedExisting;

  factory OcrRunCreateResult.fromJson(Map<String, dynamic> json) {
    final rawIds = (json['ocr_run_ids'] as List<dynamic>?) ?? const [];
    return OcrRunCreateResult(
      ocrRunId: json['ocr_run_id'] as String,
      ocrRunIds: rawIds.map((e) => e.toString()).toList(),
      jobId: json['job_id'] as String? ?? '',
      status: json['status'] as String? ?? 'queued',
      pagesTotal: (json['pages_total'] as num?)?.toInt() ?? 0,
      reusedExisting: json['reused_existing'] as bool? ?? false,
    );
  }
}

class CorrectionSuggestionItem {
  const CorrectionSuggestionItem({
    required this.correctionId,
    required this.incorrectText,
    required this.correctedText,
    required this.leftContext,
    required this.rightContext,
    required this.correctionType,
    required this.scope,
    required this.status,
    required this.approvedCount,
    required this.rejectedCount,
    required this.contextMatch,
    required this.sourceBookCount,
    required this.hasConflict,
    required this.proposedBlockText,
  });

  final String correctionId;
  final String incorrectText;
  final String correctedText;
  final String? leftContext;
  final String? rightContext;
  final String? correctionType;
  final String scope;
  final String status;
  final int approvedCount;
  final int rejectedCount;
  final String contextMatch;
  final int sourceBookCount;
  final bool hasConflict;
  final String? proposedBlockText;

  factory CorrectionSuggestionItem.fromJson(Map<String, dynamic> json) {
    return CorrectionSuggestionItem(
      correctionId: json['correction_id'] as String,
      incorrectText: json['incorrect_text'] as String? ?? '',
      correctedText: json['corrected_text'] as String? ?? '',
      leftContext: json['left_context'] as String?,
      rightContext: json['right_context'] as String?,
      correctionType: json['correction_type'] as String?,
      scope: json['scope'] as String? ?? 'book_only',
      status: json['status'] as String? ?? 'active',
      approvedCount: (json['approved_count'] as num?)?.toInt() ?? 0,
      rejectedCount: (json['rejected_count'] as num?)?.toInt() ?? 0,
      contextMatch: json['context_match'] as String? ?? 'weak',
      sourceBookCount: (json['source_book_count'] as num?)?.toInt() ?? 1,
      hasConflict: json['has_conflict'] as bool? ?? false,
      proposedBlockText: json['proposed_block_text'] as String?,
    );
  }
}

class ReviewEditHistoryItem {
  const ReviewEditHistoryItem({
    required this.editId,
    required this.previousText,
    required this.editedText,
    required this.action,
    required this.reviewerId,
    required this.reviewNote,
    required this.createdAt,
  });

  final String editId;
  final String previousText;
  final String editedText;
  final String action;
  final String? reviewerId;
  final String? reviewNote;
  final String createdAt;

  factory ReviewEditHistoryItem.fromJson(Map<String, dynamic> json) {
    return ReviewEditHistoryItem(
      editId: json['edit_id'] as String,
      previousText: json['previous_text'] as String? ?? '',
      editedText: json['edited_text'] as String? ?? '',
      action: json['action'] as String? ?? 'corrected',
      reviewerId: json['reviewer_id'] as String?,
      reviewNote: json['review_note'] as String?,
      createdAt: json['created_at'] as String? ?? '',
    );
  }
}

class ReviewBlock {
  const ReviewBlock({
    required this.blockId,
    required this.blockIndex,
    required this.readingOrder,
    required this.blockType,
    this.blockRole = 'paragraph',
    required this.rawText,
    required this.normalizedText,
    required this.currentText,
    required this.isEdited,
    required this.latestAction,
    required this.confidence,
    required this.lowConfidenceFlag,
    required this.disagreementFlag,
    required this.shortOrEmptyFlag,
    required this.comparatorText,
    required this.polygon,
    required this.bbox,
    required this.suggestions,
    required this.editHistory,
  });

  final String blockId;
  final int blockIndex;
  final int? readingOrder;
  final String blockType;
  final String blockRole;
  final String rawText;
  final String? normalizedText;
  final String currentText;
  final bool isEdited;
  final String? latestAction;
  final double? confidence;
  final bool lowConfidenceFlag;
  final bool disagreementFlag;
  final bool shortOrEmptyFlag;
  final String? comparatorText;
  final List<List<double>>? polygon;
  final List<double>? bbox;
  final List<CorrectionSuggestionItem> suggestions;
  final List<ReviewEditHistoryItem> editHistory;

  bool get isFlagged =>
      lowConfidenceFlag ||
      disagreementFlag ||
      shortOrEmptyFlag ||
      suggestions.isNotEmpty;

  factory ReviewBlock.fromJson(Map<String, dynamic> json) {
    List<List<double>>? parsedPoly;
    final rawPoly = json['polygon'];
    if (rawPoly is List) {
      parsedPoly = rawPoly
          .whereType<List<dynamic>>()
          .where((pt) => pt.length >= 2)
          .map(
            (pt) => [
              (pt[0] as num).toDouble(),
              (pt[1] as num).toDouble(),
            ],
          )
          .toList();
    }

    List<double>? parsedBbox;
    final rawBbox = json['bbox'];
    if (rawBbox is List && rawBbox.length == 4) {
      parsedBbox = rawBbox.map((v) => (v as num).toDouble()).toList();
    }

    final rawSuggestions = (json['suggestions'] as List<dynamic>?) ?? const [];
    final rawHistory = (json['edit_history'] as List<dynamic>?) ?? const [];

    return ReviewBlock(
      blockId: json['block_id'] as String,
      blockIndex: (json['block_index'] as num?)?.toInt() ?? 0,
      readingOrder: (json['reading_order'] as num?)?.toInt(),
      blockType: json['block_type'] as String? ?? 'text_line',
      blockRole: json['block_role'] as String? ?? 'paragraph',
      rawText: json['raw_text'] as String? ?? '',
      normalizedText: json['normalized_text'] as String?,
      currentText: json['current_text'] as String? ?? '',
      isEdited: json['is_edited'] as bool? ?? false,
      latestAction: json['latest_action'] as String?,
      confidence: (json['confidence'] as num?)?.toDouble(),
      lowConfidenceFlag: json['low_confidence_flag'] as bool? ?? false,
      disagreementFlag: json['disagreement_flag'] as bool? ?? false,
      shortOrEmptyFlag: json['short_or_empty_flag'] as bool? ?? false,
      comparatorText: json['comparator_text'] as String?,
      polygon: parsedPoly,
      bbox: parsedBbox,
      suggestions: rawSuggestions
          .whereType<Map<String, dynamic>>()
          .map(CorrectionSuggestionItem.fromJson)
          .toList(),
      editHistory: rawHistory
          .whereType<Map<String, dynamic>>()
          .map(ReviewEditHistoryItem.fromJson)
          .toList(),
    );
  }
}

class PageReviewPayload {
  const PageReviewPayload({
    required this.bookId,
    required this.bookTitle,
    required this.pageId,
    required this.pageNumber,
    required this.pageCount,
    required this.pageKind,
    required this.widthPx,
    required this.heightPx,
    required this.renderDpi,
    required this.reviewStatus,
    required this.digitalTextContent,
    required this.availableRuns,
    required this.primaryRunId,
    required this.primaryEngine,
    required this.primaryModelId,
    required this.comparatorRunId,
    required this.comparatorEngine,
    required this.blocks,
  });

  final String bookId;
  final String bookTitle;
  final String pageId;
  final int pageNumber;
  final int pageCount;
  final String pageKind;
  final int? widthPx;
  final int? heightPx;
  final int? renderDpi;
  final String reviewStatus;
  final String? digitalTextContent;
  final List<BookOcrRunSummary> availableRuns;
  final String? primaryRunId;
  final String? primaryEngine;
  final String? primaryModelId;
  final String? comparatorRunId;
  final String? comparatorEngine;
  final List<ReviewBlock> blocks;

  factory PageReviewPayload.fromJson(Map<String, dynamic> json) {
    final rawRuns = (json['available_runs'] as List<dynamic>?) ?? const [];
    final rawBlocks = (json['blocks'] as List<dynamic>?) ?? const [];
    return PageReviewPayload(
      bookId: json['book_id'] as String,
      bookTitle: json['book_title'] as String? ?? '',
      pageId: json['page_id'] as String,
      pageNumber: (json['page_number'] as num).toInt(),
      pageCount: (json['page_count'] as num).toInt(),
      pageKind: json['page_kind'] as String? ?? 'scanned_image',
      widthPx: (json['width_px'] as num?)?.toInt(),
      heightPx: (json['height_px'] as num?)?.toInt(),
      renderDpi: (json['render_dpi'] as num?)?.toInt(),
      reviewStatus: json['review_status'] as String? ?? 'not_started',
      digitalTextContent: json['digital_text_content'] as String?,
      availableRuns: rawRuns
          .whereType<Map<String, dynamic>>()
          .map(BookOcrRunSummary.fromJson)
          .toList(),
      primaryRunId: json['primary_run_id'] as String?,
      primaryEngine: json['primary_engine'] as String?,
      primaryModelId: json['primary_model_id'] as String?,
      comparatorRunId: json['comparator_run_id'] as String?,
      comparatorEngine: json['comparator_engine'] as String?,
      blocks: rawBlocks
          .whereType<Map<String, dynamic>>()
          .map(ReviewBlock.fromJson)
          .toList(),
    );
  }
}

class CorrectionMemoryRecord {
  const CorrectionMemoryRecord({
    required this.correctionId,
    required this.languageCode,
    required this.incorrectText,
    required this.correctedText,
    required this.leftContext,
    required this.rightContext,
    required this.correctionType,
    required this.scope,
    required this.bookId,
    required this.sourceOcrBlockId,
    required this.status,
    required this.approvedCount,
    required this.rejectedCount,
    required this.createdAt,
    required this.updatedAt,
  });

  final String correctionId;
  final String languageCode;
  final String incorrectText;
  final String correctedText;
  final String? leftContext;
  final String? rightContext;
  final String? correctionType;
  final String scope;
  final String? bookId;
  final String? sourceOcrBlockId;
  final String status;
  final int approvedCount;
  final int rejectedCount;
  final String createdAt;
  final String updatedAt;

  factory CorrectionMemoryRecord.fromJson(Map<String, dynamic> json) {
    return CorrectionMemoryRecord(
      correctionId: json['correction_id'] as String,
      languageCode: json['language_code'] as String? ?? 'te',
      incorrectText: json['incorrect_text'] as String? ?? '',
      correctedText: json['corrected_text'] as String? ?? '',
      leftContext: json['left_context'] as String?,
      rightContext: json['right_context'] as String?,
      correctionType: json['correction_type'] as String?,
      scope: json['scope'] as String? ?? 'book_only',
      bookId: json['book_id'] as String?,
      sourceOcrBlockId: json['source_ocr_block_id'] as String?,
      status: json['status'] as String? ?? 'active',
      approvedCount: (json['approved_count'] as num?)?.toInt() ?? 0,
      rejectedCount: (json['rejected_count'] as num?)?.toInt() ?? 0,
      createdAt: json['created_at'] as String? ?? '',
      updatedAt: json['updated_at'] as String? ?? '',
    );
  }
}

class ExportRecord {
  const ExportRecord({
    required this.exportId,
    required this.bookId,
    required this.transcriptVersionId,
    required this.format,
    required this.layoutMode,
    required this.textVersion,
    required this.fontFamily,
    required this.filename,
    required this.status,
    required this.isFullyReviewed,
    required this.validation,
    required this.downloadUrl,
    required this.manifestUrl,
    required this.createdAt,
  });

  final String exportId;
  final String bookId;
  final String? transcriptVersionId;
  final String format;
  final String layoutMode;
  final String textVersion;
  final String fontFamily;
  final String filename;
  final String status;
  final bool isFullyReviewed;
  final Map<String, dynamic> validation;
  final String downloadUrl;
  final String manifestUrl;
  final String createdAt;

  bool get validationPassed => validation['passed'] == true;

  factory ExportRecord.fromJson(Map<String, dynamic> json) {
    return ExportRecord(
      exportId: json['export_id'] as String,
      bookId: json['book_id'] as String,
      transcriptVersionId: json['transcript_version_id'] as String?,
      format: json['format'] as String? ?? 'docx',
      layoutMode: json['layout_mode'] as String? ?? 'page_preserving',
      textVersion: json['text_version'] as String? ?? 'human_approved',
      fontFamily: json['font_family'] as String? ?? 'Noto Serif Telugu',
      filename: json['filename'] as String? ?? 'export.docx',
      status: json['status'] as String? ?? 'completed',
      isFullyReviewed: json['is_fully_reviewed'] as bool? ?? false,
      validation: (json['validation'] as Map<String, dynamic>?) ?? const {},
      downloadUrl: json['download_url'] as String? ?? '',
      manifestUrl: json['manifest_url'] as String? ?? '',
      createdAt: json['created_at'] as String? ?? '',
    );
  }
}
