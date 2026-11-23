# 08 — Correction Memory, Human Feedback and Future Learning

## 1. Goal

Use human-approved corrections to reduce repeated OCR errors over time without introducing unsafe automatic rewrites.

The system has three different improvement mechanisms. They must not be confused:

1. **Correction memory:** Immediate reuse of known corrections as suggestions.
2. **Contextual correction:** Use sentence/page/book context to decide whether a known candidate is relevant.
3. **OCR model training:** Learn visual character/word patterns from verified image-text pairs.

A text-only correction table does not teach the visual OCR model to recognize a glyph. It improves post-OCR suggestions only.

## 2. Correction lifecycle

```text
OCR raw block
    |
    v
Correction candidate lookup
    |
    +---- no candidate -------------------+
    |                                     |
    v                                     v
Contextual review                     Human review
    |                                     |
    +---------- suggestion ---------------+
                    |
                    v
             User accepts/rejects
                    |
          +---------+----------+
          |                    |
        Accept                Reject
          |                    |
    Save approved edit    Save rejection event
          |                    |
    Create memory entry   Update negative evidence
          |
          v
  Future occurrence lookup
```

## 3. Store enough evidence

Every correction record should retain:

- OCR-observed text exactly as returned;
- human-approved text;
- left and right context (token window and/or sentence);
- source book/page and OCR block ID;
- original source image crop and its hash when available;
- OCR engine, model and version;
- correction category;
- reviewer and timestamp;
- scope and status;
- accepted/rejected occurrence counts.

Store the image crop for eventual OCR training only when rights/consent permit. A book being processed does not automatically grant permission to use its pages as model-training data.

## 4. Scope and matching rules

### Book-only correction

Useful when a book uses an older spelling or has a particular proper noun. Reuse only inside the same book unless explicitly promoted.

### Global suggestion

May be shown for other books only as a contextual suggestion. Do not silently replace text everywhere.

### Context matching

Use, in order:

1. Exact OCR form plus exact/near-exact left and right context.
2. Exact OCR form with same book-specific profile.
3. Repeated confirmed mapping across independent books.
4. LLM-assisted ranking, if enabled locally, with the original text always available.

When context conflicts, present the correction for review. A word without context should not become an unconditional global mapping.

## 5. Rule for auto-application

Phase 1 and early MVP: no automatic text changes based on correction memory. Show suggestions only.

A future version may auto-apply only in an explicitly opted-in mode and only after an evidence policy is met, for example:

- same incorrect/correct pair accepted multiple times by a reviewer;
- examples come from more than one independent document;
- surrounding context matches strongly;
- no relevant rejection or conflicting mapping exists;
- the user can see an audit trail and undo it.

Even then, retain original OCR text and mark the corrected text as machine-applied, not human-approved.

## 6. LLM correction policy

If a local LLM is introduced later:

- Feed a short context window and relevant approved candidates.
- Ask for proposed minimal OCR edits only.
- Require structured output: original span, suggested span, reason, confidence/rationale and `needs_human_review`.
- Instruct it not to paraphrase, translate, modernize grammar or normalize old spelling.
- Reject responses that change unrelated text.
- Never treat a model-generated confidence number as a calibrated probability without measurement.
- Keep the LLM optional; core review/export must work without Ollama or a remote API.

## 7. Future OCR model training

To train the OCR recognizer, collect paired examples:

- cropped original printed line/word image;
- verified transcription;
- book/page and bounding box provenance;
- OCR engine/model version that generated the original text;
- reviewer verification status;
- rights/consent flag.

Create train/validation/test splits by book or edition, not random crops from the same pages. Remove duplicate crops and near-duplicates across splits. Keep an untouched test set.

Fine-tune only after sufficient diverse examples exist and after verifying the base model's training procedure, dataset format and license. Do not assume that the PP-OCRv5 inference package alone provides a ready-made Telugu fine-tuning recipe.

## 8. Evaluation of learning

Every proposed correction-memory release or fine-tuned OCR model must be compared with the previous version on the same fixed holdout set.

Measure:

- CER, WER, grapheme error rate and exact-line accuracy;
- false correction rate (correct OCR text changed into wrong text);
- correction acceptance rate;
- rejection rate;
- performance by book, font/print quality and error category.

The false correction rate matters. A fluent but incorrect correction can be worse than leaving an uncertain OCR word untouched.

## 9. Governance

- Users can disable a correction entry.
- Conflicting mappings remain separate with context.
- A reviewer can correct an earlier review; edits are append-only events.
- Global correction memory must not leak one user's private documents to another unless the product explicitly supports a shared knowledge base and permissions permit it.
- Training consent is separate from OCR processing consent.
