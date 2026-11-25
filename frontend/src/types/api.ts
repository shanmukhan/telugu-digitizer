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
  max_upload_mb: number;
  max_pdf_pages: number;
  engines: Record<string, EngineCapability>;
}

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
  created_at: string;
  updated_at: string;
  scanned_pages_count: number;
  digital_text_pages_count: number;
  mixed_pages_count: number;
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

export interface ReviewEditHistoryItem {
  edit_id: string;
  previous_text: string;
  edited_text: string;
  action: "corrected" | "approved" | "reverted" | "ignored";
  reviewer_id: string | null;
  review_note: string | null;
  created_at: string;
}

export interface CorrectionSuggestionItem {
  correction_id: string;
  incorrect_text: string;
  corrected_text: string;
  left_context: string | null;
  right_context: string | null;
  correction_type: string | null;
  scope: "book_only" | "global_suggestion";
  status: string;
  approved_count: number;
  rejected_count: number;
  context_match: "strong" | "medium" | "weak";
  source_book_count: number;
  has_conflict: boolean;
  proposed_block_text: string | null;
}

export interface CorrectionMemoryRecord {
  correction_id: string;
  language_code: string;
  incorrect_text: string;
  corrected_text: string;
  left_context: string | null;
  right_context: string | null;
  correction_type: string | null;
  scope: "book_only" | "global_suggestion";
  book_id: string | null;
  source_ocr_block_id: string | null;
  status: "active" | "disabled" | "superseded" | "rejected";
  approved_count: number;
  rejected_count: number;
  created_at: string;
  updated_at: string;
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
  latest_action: "corrected" | "approved" | "reverted" | "ignored" | null;
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
