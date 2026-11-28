export interface ApiErrorDetail {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export interface EngineCapability {
  available: boolean;
  reason: string | null;
  model_id: string;
}

export interface HostCapabilities {
  platform_machine: string;
  auth_enabled: boolean;
  guest_ocr_enabled?: boolean;
  admin_delete_requires_auth?: boolean;
  book_delete_enabled?: boolean;
  max_upload_mb: number;
  max_pdf_pages: number;
  engines: Record<string, EngineCapability>;
}

export type BookProcessingState =
  | "uploaded"
  | "calibration_pending"
  | "calibration_processing"
  | "calibration_review"
  | "calibration_completed"
  | "remaining_processing"
  | "review_in_progress"
  | "completed"
  | "paused";

export interface BookSummary {
  book_id: string;
  title: string;
  author: string | null;
  publisher: string | null;
  publication_year: number | null;
  language_code: string;
  orthography_profile: string;
  original_filename: string;
  source_sha256: string;
  page_count: number;
  rights_status: string;
  training_consent: boolean;
  processing_state?: BookProcessingState;
  calibration_start_page?: number | null;
  calibration_page_count?: number | null;
  calibration_end_page?: number | null;
  calibration_completed_at?: string | null;
  approved_pages_count?: number;
  created_at: string;
  updated_at: string;
  scanned_pages_count: number;
  digital_text_pages_count: number;
  mixed_pages_count: number;
}

export interface LearnedCharPattern {
  from_seq: string;
  to_seq: string;
  occurrences: number;
  examples: string[];
}

export interface BookCalibrationStatus {
  book_id: string;
  page_count: number;
  processing_state: BookProcessingState;
  calibration_start_page: number | null;
  calibration_page_count: number | null;
  calibration_range_end: number | null;
  book_end_page: number;
  skipped_front_pages_count: number;
  remaining_start_page: number | null;
  remaining_end_page: number | null;
  remaining_pages_count: number;
  calibration_pages_ocred: number;
  calibration_pages_approved: number;
  calibration_completed_at: string | null;
  learned_word_rules_count: number;
  learned_char_patterns: LearnedCharPattern[];
  conflicting_rules_count: number;
  auto_applied_blocks_count: number;
  newly_harvested_rules_count?: number;
}

export interface CalibrationRunResult extends OCRRunCreateResult {
  calibration: BookCalibrationStatus;
}

export interface CalibrationReapplyResult {
  book_id: string;
  pages_scanned: number;
  pages_updated: number;
  blocks_updated: number;
  active_rules_count: number;
}

export interface LegacyCorrectionNormalizeResult {
  inspected_count: number;
  split_legacy_rows: number;
  cleaned_punct_rows: number;
  created_word_rules: number;
  merged_duplicates: number;
}

export interface BookTrainingConsentResult {
  book_id: string;
  training_consent: boolean;
  harvested_crops_count: number;
  total_book_samples: number;
}

export interface TrainingBookSummaryItem {
  book_id: string;
  title: string;
  training_consent: boolean;
  verified_samples_count: number;
}

export interface TrainingDatasetSummary {
  total_verified_samples: number;
  unique_crop_hashes: number;
  consented_books_count: number;
  selected_book_consent: boolean | null;
  selected_book_samples: number;
  books: TrainingBookSummaryItem[];
}

export interface TrainingDatasetExportResult {
  export_id: string;
  filename: string;
  total_samples: number;
  train_count: number;
  val_count: number;
  deduplicated_skipped: number;
  archive_sha256: string;
  download_url: string;
  created_at: string;
}

export interface BookUploadResult {
  book_id: string;
  title: string;
  page_count: number;
  source_sha256: string;
  status: string;
  duplicate: boolean;
}

export interface PageSummary {
  page_id: string;
  page_number: number;
  page_kind: "scanned_image" | "digital_text" | "mixed";
  width_px: number | null;
  height_px: number | null;
  render_dpi: number | null;
  extracted_text_char_count: number;
  image_coverage_ratio: number;
  review_status: "not_started" | "in_review" | "approved" | "needs_attention";
  has_image: boolean;
}

export interface BookOCRRunSummary {
  ocr_run_id: string;
  engine: string | null;
  model_id: string | null;
  status: string;
  progress_current?: number;
  progress_total?: number;
  started_at?: string | null;
  error_summary?: string | null;
  config: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
}

export interface OCRRunCreateResult {
  ocr_run_id: string;
  ocr_run_ids: string[];
  job_id: string;
  status: string;
  pages_total: number;
  reused_existing: boolean;
}

export interface OCRRunStatus {
  ocr_run_id: string;
  book_id: string;
  job_id: string | null;
  engine: string | null;
  model_id: string | null;
  status: string;
  progress_current: number;
  progress_total: number;
  config: Record<string, unknown>;
  started_at: string | null;
  completed_at: string | null;
  error_summary: string | null;
  error_details: Record<string, unknown>;
  created_at: string;
}

export type BlockRole = "paragraph" | "heading_1" | "heading_2" | "verse" | "ignore";

export interface AutoAppliedRuleItem {
  correction_id: string | null;
  original: string;
  replacement: string;
  scope: "book_only" | "global_suggestion" | string;
  unit_type: "word" | "char_pattern" | "phrase" | string;
  context_match: string;
  confidence: number;
  reason: string;
}

export interface ReviewEditHistoryItem {
  edit_id: string;
  previous_text: string;
  edited_text: string;
  action: "corrected" | "approved" | "reverted" | "ignored" | "auto_applied";
  reviewer_id: string | null;
  review_note: string | null;
  applied_rules?: AutoAppliedRuleItem[] | null;
  created_at: string;
}

export interface CorrectionSuggestionItem {
  correction_id: string;
  incorrect_text: string;
  corrected_text: string;
  left_context: string | null;
  right_context: string | null;
  correction_type: string | null;
  unit_type?: "word" | "char_pattern" | "phrase";
  scope: "book_only" | "global_suggestion";
  status: string;
  approved_count: number;
  rejected_count: number;
  reliability_score?: number;
  context_match: "strong" | "medium" | "weak";
  source_book_count: number;
  has_conflict: boolean;
  proposed_block_text: string | null;
}

export interface CorrectionMemoryRecord {
  correction_id: string;
  language_code: string;
  incorrect_text: string;
  normalized_incorrect?: string | null;
  corrected_text: string;
  left_context: string | null;
  right_context: string | null;
  correction_type: string | null;
  unit_type?: "word" | "char_pattern" | "phrase";
  scope: "book_only" | "global_suggestion";
  book_id: string | null;
  source_book_title?: string | null;
  source_ocr_block_id: string | null;
  source_page_number?: number | null;
  status: "active" | "disabled" | "superseded" | "rejected";
  approved_count: number;
  rejected_count: number;
  reliability_score?: number;
  has_conflict?: boolean;
  conflict_count?: number;
  last_used_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CorrectionListResult {
  items: CorrectionMemoryRecord[];
  total_count: number;
  global_count: number;
  book_specific_count: number;
  conflicts_count: number;
}

export interface ReviewBlock {
  block_id: string;
  block_index: number;
  reading_order: number | null;
  block_type: string;
  block_role?: BlockRole;
  raw_text: string;
  normalized_text: string | null;
  current_text: string;
  is_edited: boolean;
  latest_action: "corrected" | "approved" | "reverted" | "ignored" | "auto_applied" | null;
  auto_applied_flag?: boolean;
  auto_applied_rules?: AutoAppliedRuleItem[];
  confidence: number | null;
  low_confidence_flag: boolean;
  disagreement_flag: boolean;
  short_or_empty_flag: boolean;
  comparator_text: string | null;
  polygon: number[][] | null;
  bbox: number[] | null;
  suggestions: CorrectionSuggestionItem[];
  edit_history: ReviewEditHistoryItem[];
}

export interface PageReviewPayload {
  book_id: string;
  book_title: string;
  page_id: string;
  page_number: number;
  page_count: number;
  page_kind: "scanned_image" | "digital_text" | "mixed";
  width_px: number | null;
  height_px: number | null;
  render_dpi: number | null;
  review_status: "not_started" | "in_review" | "approved" | "needs_attention";
  digital_text_content: string | null;
  available_runs: BookOCRRunSummary[];
  primary_run_id: string | null;
  primary_engine: string | null;
  primary_model_id: string | null;
  comparator_run_id: string | null;
  comparator_engine: string | null;
  blocks: ReviewBlock[];
}

export interface BlockEditResult {
  edit_id: string;
  block_id: string;
  raw_text: string;
  previous_text: string;
  current_text: string;
  action: "corrected" | "approved" | "reverted" | "ignored";
  block_role?: BlockRole;
  page_review_status: "not_started" | "in_review" | "approved" | "needs_attention";
  correction_memory_id: string | null;
  created_at: string;
}

export interface ManualBlockCreateResult {
  block_id: string;
  ocr_run_id: string;
  block_index: number;
  reading_order: number | null;
  block_type: string;
  raw_text: string;
  current_text: string;
  block_role: BlockRole;
}

export interface ExportCreatePayload {
  format: "docx" | "txt";
  layout_mode: "editable_flow" | "page_preserving";
  text_version: "human_approved" | "raw_ocr";
  primary_run_id?: string | null;
  font_family: string;
  body_font_size: number;
  include_page_numbers: boolean;
  include_table_of_contents: boolean;
}

export interface ExportRecord {
  export_id: string;
  book_id: string;
  transcript_version_id: string | null;
  format: "docx" | "txt";
  layout_mode: string;
  text_version: string;
  font_family: string;
  filename: string;
  status: string;
  is_fully_reviewed: boolean;
  validation: Record<string, unknown>;
  download_url: string;
  manifest_url: string;
  created_at: string;
}

export interface AutocorrectChangeItem {
  original: string;
  replacement: string;
  source: "correction_memory" | "dictionary" | "sentence_context" | string;
  confidence: number;
  reason: string;
}

export interface BlockAutocorrectProposal {
  block_id: string;
  original_text: string;
  proposed_text: string;
  changes: AutocorrectChangeItem[];
}

export interface PageAutocorrectResponse {
  book_id: string;
  page_number: number;
  primary_run_id: string | null;
  lexicon_word_count: number;
  total_blocks_scanned: number;
  changed_blocks_count: number;
  total_changes_count: number;
  blocks: BlockAutocorrectProposal[];
}

export interface BatchBlockEditPayload {
  block_id: string;
  edited_text: string;
  action?: "corrected" | "approved" | "reverted" | "ignored";
  block_role?: BlockRole;
  review_note?: string;
  add_to_correction_memory?: boolean;
  memory_scope?: "book_only" | "global_suggestion";
  correction_type?: string;
}

export interface PageBatchSaveResponse {
  book_id: string;
  page_number: number;
  saved_edits_count: number;
  approved_blocks_count: number;
  correction_memory_created_count: number;
  correction_memory_skipped_noise_count: number;
  page_review_status: "not_started" | "in_review" | "approved" | "needs_attention";
}

export interface DictionaryStats {
  available: boolean;
  has_definitions_db: boolean;
  total_words: number;
  words_with_definitions: number;
  total_definitions: number;
  custom_words_count: number;
  source_definition_counts: Record<string, number>;
  built_at: string | null;
}

export interface DictionaryDefinitionItem {
  source: string;
  lang: string;
  definition: string;
}

export interface DictionarySuggestionItem {
  word: string;
  confidence: number;
  reason: string;
}

export interface DictionarySearchItem {
  word: string;
  weight: number;
  sources: string[];
  translit: string;
  has_definition: boolean;
  is_custom: boolean;
  custom_word_id: string | null;
  definitions: DictionaryDefinitionItem[];
}

export interface DictionarySearchResponse {
  query: string;
  detected_mode: "telugu" | "english" | string;
  exact_match: boolean;
  items: DictionarySearchItem[];
  did_you_mean: DictionarySuggestionItem[];
}

export interface DictionaryWordDetail {
  word: string;
  found: boolean;
  is_valid_word: boolean;
  weight: number;
  sources: string[];
  translit: string;
  is_custom: boolean;
  custom_word_id: string | null;
  definitions: DictionaryDefinitionItem[];
  did_you_mean: DictionarySuggestionItem[];
}

export interface DictionaryTextIssueItem {
  token: string;
  token_index: number;
  best_replacement: string | null;
  confidence: number | null;
  reason: string;
  suggestions: string[];
}

export interface DictionaryTextCheckResponse {
  total_telugu_words: number;
  known_words_count: number;
  unknown_words_count: number;
  issues: DictionaryTextIssueItem[];
}

export interface CustomDictionaryWordRecord {
  word_id: string;
  language_code: string;
  word: string;
  translit: string | null;
  meaning_en: string | null;
  meaning_te: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}
