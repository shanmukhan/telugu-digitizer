import 'package:flutter/material.dart';

import '../../../../data/models/api_models.dart';
import '../../../core/app_theme.dart';
import '../view_models/studio_view_model.dart';

enum MobileReviewMode { split, scanOnly, editorOnly }

class PageReviewTabView extends StatefulWidget {
  const PageReviewTabView({super.key, required this.viewModel});

  final StudioViewModel viewModel;

  @override
  State<PageReviewTabView> createState() => _PageReviewTabViewState();
}

class _PageReviewTabViewState extends State<PageReviewTabView> {
  MobileReviewMode _mobileMode = MobileReviewMode.split;
  bool _filterFlaggedOnly = false;
  String _searchQuery = '';
  double _teluguFontScale = 1.0;
  bool _showQuickSigns = false;

  final Map<String, TextEditingController> _controllers = {};
  final Map<String, bool> _rememberByBlock = {};
  final Map<String, String> _scopeByBlock = {};
  String? _activeEditingBlockId;
  String _lastPageContextKey = '';

  @override
  void dispose() {
    for (final c in _controllers.values) {
      c.dispose();
    }
    super.dispose();
  }

  void _syncControllers(PageReviewPayload review) {
    final contextKey =
        '${review.bookId}:${review.pageNumber}:${review.primaryRunId ?? ''}';
    final sameContext = _lastPageContextKey == contextKey;
    _lastPageContextKey = contextKey;

    final seenIds = <String>{};
    for (final blk in review.blocks) {
      seenIds.add(blk.blockId);
      final existing = _controllers[blk.blockId];
      if (existing == null) {
        _controllers[blk.blockId] =
            TextEditingController(text: blk.currentText);
      } else if (!sameContext) {
        existing.text = blk.currentText;
      }
    }
    final obsolete =
        _controllers.keys.where((k) => !seenIds.contains(k)).toList();
    for (final k in obsolete) {
      _controllers.remove(k)?.dispose();
    }
  }

  void _insertSignAtActiveCursor(String sign) {
    final blockId = _activeEditingBlockId ?? widget.viewModel.selectedBlockId;
    if (blockId == null) return;
    final controller = _controllers[blockId];
    if (controller == null) return;

    final value = controller.value;
    final start = value.selection.isValid ? value.selection.start : value.text.length;
    final end = value.selection.isValid ? value.selection.end : value.text.length;
    final nextText = value.text.replaceRange(start, end, sign);
    controller.value = TextEditingValue(
      text: nextText,
      selection: TextSelection.collapsed(offset: start + sign.length),
    );
    setState(() {});
  }

  void _jumpToNextFlagged(List<ReviewBlock> flaggedBlocks) {
    if (flaggedBlocks.isEmpty) return;
    final currentId = widget.viewModel.selectedBlockId;
    final idx = flaggedBlocks.indexWhere((b) => b.blockId == currentId);
    final next = flaggedBlocks[(idx + 1) % flaggedBlocks.length];
    widget.viewModel.selectBlock(next.blockId);
  }

  @override
  Widget build(BuildContext context) {
    final vm = widget.viewModel;
    final book = vm.selectedBook;
    final review = vm.review;

    if (book == null) {
      return const Center(
        child: Text('Select or import a Telugu PDF book in the Library tab.'),
      );
    }

    if (review == null) {
      return const Center(child: CircularProgressIndicator());
    }

    _syncControllers(review);

    final flaggedBlocks =
        review.blocks.where((b) => b.isFlagged).toList();
    final trimmedQuery = _searchQuery.trim().toLowerCase();
    final visibleBlocks = review.blocks.where((b) {
      if (_filterFlaggedOnly && !b.isFlagged) return false;
      if (trimmedQuery.isNotEmpty) {
        final draft =
            (_controllers[b.blockId]?.text ?? b.currentText).toLowerCase();
        final raw = b.rawText.toLowerCase();
        final lineLabel = 'line ${b.blockIndex + 1}';
        return draft.contains(trimmedQuery) ||
            raw.contains(trimmedQuery) ||
            lineLabel.contains(trimmedQuery);
      }
      return true;
    }).toList();

    return Column(
      children: [
        // Top page navigation & status toolbar
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: const BoxDecoration(
            color: AppTheme.surfaceMuted,
            border: Border(bottom: BorderSide(color: AppTheme.border)),
          ),
          child: Wrap(
            spacing: 8,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            alignment: WrapAlignment.spaceBetween,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  IconButton.outlined(
                    visualDensity: VisualDensity.compact,
                    tooltip: 'Previous Page',
                    onPressed: review.pageNumber > 1
                        ? () => vm.navigatePage(review.pageNumber - 1)
                        : null,
                    icon: const Icon(Icons.chevron_left),
                  ),
                  const SizedBox(width: 6),
                  DropdownButton<int>(
                    value: review.pageNumber,
                    underline: const SizedBox.shrink(),
                    items: List.generate(
                      review.pageCount,
                      (idx) => DropdownMenuItem(
                        value: idx + 1,
                        child: Text(
                          'Page ${idx + 1} / ${review.pageCount}',
                          style: const TextStyle(fontWeight: FontWeight.w600),
                        ),
                      ),
                    ),
                    onChanged: (page) {
                      if (page != null) vm.navigatePage(page);
                    },
                  ),
                  const SizedBox(width: 6),
                  IconButton.outlined(
                    visualDensity: VisualDensity.compact,
                    tooltip: 'Next Page',
                    onPressed: review.pageNumber < review.pageCount
                        ? () => vm.navigatePage(review.pageNumber + 1)
                        : null,
                    icon: const Icon(Icons.chevron_right),
                  ),
                ],
              ),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  FilterChip(
                    label: Text('Flagged (${flaggedBlocks.length})'),
                    selected: _filterFlaggedOnly,
                    onSelected: (val) =>
                        setState(() => _filterFlaggedOnly = val),
                  ),
                  if (flaggedBlocks.isNotEmpty)
                    ActionChip(
                      label: const Text('Next Issue ▾'),
                      onPressed: () => _jumpToNextFlagged(flaggedBlocks),
                    ),
                  ActionChip(
                    avatar: const Icon(Icons.keyboard_alt_outlined, size: 16),
                    label: const Text('గుణింతాలు'),
                    backgroundColor:
                        _showQuickSigns ? AppTheme.primarySoft : null,
                    onPressed: () =>
                        setState(() => _showQuickSigns = !_showQuickSigns),
                  ),
                  FilledButton.tonalIcon(
                    onPressed: () => vm.updatePageStatus('approved'),
                    icon: const Icon(Icons.verified_outlined, size: 18),
                    label: Text(
                      review.reviewStatus == 'approved'
                          ? 'Approved'
                          : 'Approve Page',
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),

        // Optional Telugu combining signs bar
        if (_showQuickSigns)
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            decoration: const BoxDecoration(
              color: AppTheme.surface,
              border: Border(bottom: BorderSide(color: AppTheme.border)),
            ),
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  const Text(
                    'Signs: ',
                    style: TextStyle(
                      fontSize: 12,
                      fontWeight: FontWeight.w700,
                      color: AppTheme.inkMuted,
                    ),
                  ),
                  ...teluguQuickCombiningSigns.map(
                    (item) => Padding(
                      padding: const EdgeInsets.only(right: 6),
                      child: ActionChip(
                        visualDensity: VisualDensity.compact,
                        label: Text(
                          '${item.glyph} (${item.label})',
                          style: const TextStyle(
                            fontSize: 14,
                            fontFamilyFallback: AppTheme.teluguFontFallback,
                          ),
                        ),
                        onPressed: () =>
                            _insertSignAtActiveCursor(item.glyph),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),

        // Adaptive Body (Side-by-Side on tablet/landscape > 720px, Segmented/Split on phone)
        Expanded(
          child: LayoutBuilder(
            builder: (context, constraints) {
              if (constraints.maxWidth > 720) {
                return Row(
                  children: [
                    Expanded(
                      flex: 5,
                      child: _ScanOverlayPane(
                        viewModel: vm,
                        review: review,
                      ),
                    ),
                    const VerticalDivider(width: 1),
                    Expanded(
                      flex: 6,
                      child: _buildEditorPane(review, visibleBlocks),
                    ),
                  ],
                );
              }

              return Column(
                children: [
                  Padding(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                    child: SegmentedButton<MobileReviewMode>(
                      segments: const [
                        ButtonSegment(
                          value: MobileReviewMode.split,
                          icon: Icon(Icons.vertical_split_outlined, size: 18),
                          label: Text('Split'),
                        ),
                        ButtonSegment(
                          value: MobileReviewMode.scanOnly,
                          icon: Icon(Icons.image_search_outlined, size: 18),
                          label: Text('Scan + Boxes'),
                        ),
                        ButtonSegment(
                          value: MobileReviewMode.editorOnly,
                          icon: Icon(Icons.edit_note_outlined, size: 18),
                          label: Text('Lines'),
                        ),
                      ],
                      selected: {_mobileMode},
                      onSelectionChanged: (s) =>
                          setState(() => _mobileMode = s.first),
                    ),
                  ),
                  Expanded(
                    child: switch (_mobileMode) {
                      MobileReviewMode.scanOnly => _ScanOverlayPane(
                          viewModel: vm,
                          review: review,
                        ),
                      MobileReviewMode.editorOnly =>
                        _buildEditorPane(review, visibleBlocks),
                      MobileReviewMode.split => Column(
                          children: [
                            Expanded(
                              flex: 4,
                              child: _ScanOverlayPane(
                                viewModel: vm,
                                review: review,
                              ),
                            ),
                            const Divider(height: 1),
                            Expanded(
                              flex: 6,
                              child: _buildEditorPane(review, visibleBlocks),
                            ),
                          ],
                        ),
                    },
                  ),
                ],
              );
            },
          ),
        ),
      ],
    );
  }

  Widget _buildEditorPane(
    PageReviewPayload review,
    List<ReviewBlock> visibleBlocks,
  ) {
    final vm = widget.viewModel;
    final usableRuns = review.availableRuns
        .where((r) => r.status == 'completed' || r.status == 'partial')
        .toList();

    return Column(
      children: [
        // Search & font scale bar
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  decoration: const InputDecoration(
                    hintText: 'Filter lines on this page…',
                    prefixIcon: Icon(Icons.search, size: 18),
                    isDense: true,
                  ),
                  onChanged: (v) => setState(() => _searchQuery = v),
                ),
              ),
              if (usableRuns.length > 1) ...[
                const SizedBox(width: 8),
                DropdownButton<String>(
                  value: review.primaryRunId,
                  hint: const Text('Engine'),
                  items: usableRuns
                      .map(
                        (r) => DropdownMenuItem(
                          value: r.ocrRunId,
                          child: Text(
                            formatEngineLabel(r.engine),
                            style: const TextStyle(fontSize: 12.5),
                          ),
                        ),
                      )
                      .toList(),
                  onChanged: vm.selectPrimaryRun,
                ),
              ],
              const SizedBox(width: 4),
              IconButton(
                tooltip: 'Smaller Telugu font',
                visualDensity: VisualDensity.compact,
                onPressed: () => setState(
                  () => _teluguFontScale =
                      (_teluguFontScale - 0.15).clamp(0.85, 1.6),
                ),
                icon: const Icon(Icons.text_decrease, size: 18),
              ),
              IconButton(
                tooltip: 'Larger Telugu font',
                visualDensity: VisualDensity.compact,
                onPressed: () => setState(
                  () => _teluguFontScale =
                      (_teluguFontScale + 0.15).clamp(0.85, 1.6),
                ),
                icon: const Icon(Icons.text_increase, size: 18),
              ),
            ],
          ),
        ),
        Expanded(
          child: review.pageKind == 'digital_text'
              ? ListView(
                  padding: const EdgeInsets.all(16),
                  children: [
                    Card(
                      child: Padding(
                        padding: const EdgeInsets.all(16),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Chip(
                              label: Text('Born-Digital Text Path (Not OCR)'),
                              backgroundColor: AppTheme.okBg,
                            ),
                            const SizedBox(height: 8),
                            SelectableText(
                              review.digitalTextContent ??
                                  '(Empty digital text)',
                              style: TextStyle(
                                fontSize: 17 * _teluguFontScale,
                                height: 1.6,
                                fontFamilyFallback:
                                    AppTheme.teluguFontFallback,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                )
              : visibleBlocks.isEmpty
                  ? Center(
                      child: Padding(
                        padding: const EdgeInsets.all(24),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Text(
                              'No OCR lines to display on this page.',
                              style: TextStyle(fontWeight: FontWeight.w600),
                            ),
                            const SizedBox(height: 8),
                            if (review.availableRuns.isEmpty)
                              FilledButton.icon(
                                onPressed: vm.isOcrRunning
                                    ? null
                                    : () => vm.startOcr(),
                                icon: const Icon(Icons.play_arrow),
                                label: const Text('Run OCR Now'),
                              ),
                          ],
                        ),
                      ),
                    )
                  : ListView.builder(
                      padding: const EdgeInsets.fromLTRB(12, 12, 12, 96),
                      itemCount: visibleBlocks.length,
                      itemBuilder: (context, index) {
                        final block = visibleBlocks[index];
                        final controller = _controllers[block.blockId]!;
                        final isSelected =
                            block.blockId == vm.selectedBlockId;
                        final isBusy = vm.busyBlockId == block.blockId;
                        final isDirty = controller.text != block.currentText;
                        final remember =
                            _rememberByBlock[block.blockId] ?? false;
                        final scope =
                            _scopeByBlock[block.blockId] ?? 'book_only';

                        return Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: Card(
                            color: block.isFlagged
                                ? const Color(0xFFFFFBEB)
                                : AppTheme.surface,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12),
                              side: BorderSide(
                                color: isSelected
                                    ? AppTheme.primary
                                    : block.isFlagged
                                        ? AppTheme.warnBorder
                                        : AppTheme.border,
                                width: isSelected ? 2 : 1,
                              ),
                            ),
                            child: Padding(
                              padding: const EdgeInsets.all(12),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  // Badges row
                                  Wrap(
                                    spacing: 6,
                                    runSpacing: 6,
                                    children: [
                                      _Badge(
                                        text: 'Line ${block.blockIndex + 1}',
                                      ),
                                      if (block.confidence != null)
                                        _Badge(
                                          text:
                                              'Conf: ${review.primaryEngine == 'tesseract' ? '${block.confidence!.toStringAsFixed(1)}%' : block.confidence!.toStringAsFixed(3)}',
                                          isWarn: block.lowConfidenceFlag,
                                        ),
                                      if (block.lowConfidenceFlag)
                                        const _Badge(
                                          text: '⚠ Low Conf',
                                          isWarn: true,
                                        ),
                                      if (block.disagreementFlag)
                                        _Badge(
                                          text:
                                              '⇄ Disagrees (${review.comparatorEngine})',
                                          isWarn: true,
                                        ),
                                      if (block.isEdited)
                                        const _Badge(
                                          text: '✓ Edited',
                                          isOk: true,
                                        ),
                                      if (block.latestAction == 'approved')
                                        const _Badge(
                                          text: '✓ Approved',
                                          isOk: true,
                                        ),
                                      if (block.latestAction == 'ignored' ||
                                          block.blockRole == 'ignore')
                                        const _Badge(
                                          text: '✕ Ignored',
                                          isWarn: true,
                                        ),
                                      if (block.blockRole == 'heading_1' ||
                                          block.blockRole == 'heading_2')
                                        _Badge(
                                          text: block.blockRole == 'heading_1'
                                              ? 'H1'
                                              : 'H2',
                                        ),
                                    ],
                                  ),
                                  const SizedBox(height: 8),

                                  // Immutable Raw OCR box
                                  Container(
                                    width: double.infinity,
                                    padding: const EdgeInsets.all(8),
                                    decoration: BoxDecoration(
                                      color: AppTheme.surfaceMuted,
                                      borderRadius: BorderRadius.circular(8),
                                    ),
                                    child: Text(
                                      'Raw OCR: ${block.rawText}',
                                      style: TextStyle(
                                        fontSize: 14 * _teluguFontScale,
                                        color: AppTheme.inkMuted,
                                        fontFamilyFallback:
                                            AppTheme.teluguFontFallback,
                                      ),
                                    ),
                                  ),

                                  // Comparator box when engines disagree
                                  if (block.disagreementFlag &&
                                      block.comparatorText != null) ...[
                                    const SizedBox(height: 6),
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 8,
                                        vertical: 6,
                                      ),
                                      decoration: BoxDecoration(
                                        color: AppTheme.warnBg,
                                        borderRadius: BorderRadius.circular(8),
                                        border: Border.all(
                                          color: AppTheme.warnBorder,
                                        ),
                                      ),
                                      child: Row(
                                        children: [
                                          Expanded(
                                            child: Text(
                                              '${formatEngineLabel(review.comparatorEngine)}: ${block.comparatorText}',
                                              style: TextStyle(
                                                fontSize:
                                                    14.5 * _teluguFontScale,
                                                fontFamilyFallback:
                                                    AppTheme.teluguFontFallback,
                                              ),
                                            ),
                                          ),
                                          TextButton(
                                            onPressed: () {
                                              controller.text =
                                                  block.comparatorText!;
                                              setState(() {});
                                            },
                                            child: const Text('Use'),
                                          ),
                                        ],
                                      ),
                                    ),
                                  ],

                                  // Contextual Correction Memory suggestions
                                  if (block.suggestions.isNotEmpty) ...[
                                    const SizedBox(height: 6),
                                    ...block.suggestions.map(
                                      (sug) => Container(
                                        margin:
                                            const EdgeInsets.only(bottom: 4),
                                        padding: const EdgeInsets.all(8),
                                        decoration: BoxDecoration(
                                          color: AppTheme.primarySoft,
                                          borderRadius:
                                              BorderRadius.circular(8),
                                        ),
                                        child: Row(
                                          children: [
                                            Expanded(
                                              child: Text(
                                                '💡 ${sug.incorrectText} → ${sug.correctedText} (${sug.contextMatch}, +${sug.approvedCount}/-${sug.rejectedCount})',
                                                style: TextStyle(
                                                  fontSize:
                                                      13.5 * _teluguFontScale,
                                                  fontFamilyFallback: AppTheme
                                                      .teluguFontFallback,
                                                ),
                                              ),
                                            ),
                                            TextButton(
                                              onPressed: isBusy
                                                  ? null
                                                  : () => vm.acceptSuggestion(
                                                        block: block,
                                                        suggestion: sug,
                                                      ),
                                              child: const Text('Apply'),
                                            ),
                                            TextButton(
                                              onPressed: isBusy
                                                  ? null
                                                  : () => vm.rejectSuggestion(
                                                        sug.correctionId,
                                                      ),
                                              child: const Text('Reject'),
                                            ),
                                          ],
                                        ),
                                      ),
                                    ),
                                  ],

                                  const SizedBox(height: 8),
                                  TextField(
                                    controller: controller,
                                    minLines: 1,
                                    maxLines: 5,
                                    style: TextStyle(
                                      fontSize: 17 * _teluguFontScale,
                                      height: 1.55,
                                      fontFamilyFallback:
                                          AppTheme.teluguFontFallback,
                                    ),
                                    onTap: () {
                                      _activeEditingBlockId = block.blockId;
                                      vm.selectBlock(block.blockId);
                                    },
                                    onChanged: (_) => setState(() {}),
                                  ),

                                  if (isDirty) ...[
                                    const SizedBox(height: 6),
                                    Wrap(
                                      spacing: 10,
                                      crossAxisAlignment:
                                          WrapCrossAlignment.center,
                                      children: [
                                        Row(
                                          mainAxisSize: MainAxisSize.min,
                                          children: [
                                            Checkbox(
                                              visualDensity:
                                                  VisualDensity.compact,
                                              value: remember,
                                              onChanged: (v) => setState(
                                                () => _rememberByBlock[
                                                        block.blockId] =
                                                    v ?? false,
                                              ),
                                            ),
                                            const Text(
                                              'Save to correction memory',
                                              style: TextStyle(fontSize: 12.5),
                                            ),
                                          ],
                                        ),
                                        if (remember)
                                          DropdownButton<String>(
                                            value: scope,
                                            isDense: true,
                                            items: const [
                                              DropdownMenuItem(
                                                value: 'book_only',
                                                child: Text(
                                                  'Book only',
                                                  style:
                                                      TextStyle(fontSize: 12.5),
                                                ),
                                              ),
                                              DropdownMenuItem(
                                                value: 'global_suggestion',
                                                child: Text(
                                                  'Global suggestion',
                                                  style:
                                                      TextStyle(fontSize: 12.5),
                                                ),
                                              ),
                                            ],
                                            onChanged: (v) {
                                              if (v != null) {
                                                setState(
                                                  () => _scopeByBlock[
                                                      block.blockId] = v,
                                                );
                                              }
                                            },
                                          ),
                                      ],
                                    ),
                                  ],

                                  const SizedBox(height: 8),
                                  Wrap(
                                    spacing: 8,
                                    runSpacing: 8,
                                    children: [
                                      FilledButton.tonal(
                                        onPressed: isBusy || !isDirty
                                            ? null
                                            : () => vm.saveBlockEdit(
                                                  blockId: block.blockId,
                                                  editedText: controller.text,
                                                  action: 'corrected',
                                                  addToMemory: remember,
                                                  memoryScope: scope,
                                                ),
                                        child: Text(
                                          isBusy
                                              ? 'Saving...'
                                              : 'Save Correction',
                                        ),
                                      ),
                                      OutlinedButton(
                                        onPressed: isBusy
                                            ? null
                                            : () => vm.saveBlockEdit(
                                                  blockId: block.blockId,
                                                  editedText: controller.text,
                                                  action: 'approved',
                                                ),
                                        child: const Text('Approve Block'),
                                      ),
                                      if (block.latestAction != 'ignored' &&
                                          block.blockRole != 'ignore')
                                        TextButton(
                                          onPressed: isBusy
                                              ? null
                                              : () => vm.saveBlockEdit(
                                                    blockId: block.blockId,
                                                    editedText: controller.text,
                                                    action: 'ignored',
                                                    blockRole: 'ignore',
                                                  ),
                                          child: const Text('Ignore Box'),
                                        ),
                                      if (block.currentText != block.rawText)
                                        TextButton(
                                          onPressed: isBusy
                                              ? null
                                              : () {
                                                  controller.text =
                                                      block.rawText;
                                                  vm.saveBlockEdit(
                                                    blockId: block.blockId,
                                                    editedText: block.rawText,
                                                    action: 'reverted',
                                                  );
                                                },
                                          child:
                                              const Text('Revert to Raw OCR'),
                                        ),
                                    ],
                                  ),

                                  if (block.editHistory.isNotEmpty)
                                    ExpansionTile(
                                      tilePadding: EdgeInsets.zero,
                                      dense: true,
                                      title: Text(
                                        'Revision history (${block.editHistory.length})',
                                        style: const TextStyle(
                                          fontSize: 12,
                                          color: AppTheme.inkMuted,
                                        ),
                                      ),
                                      children: block.editHistory
                                          .map(
                                            (h) => ListTile(
                                              dense: true,
                                              contentPadding: EdgeInsets.zero,
                                              title: Text(
                                                '${h.action}: ${h.editedText}',
                                                style: const TextStyle(
                                                  fontSize: 13,
                                                  fontFamilyFallback: AppTheme
                                                      .teluguFontFallback,
                                                ),
                                              ),
                                              subtitle: h.reviewNote != null
                                                  ? Text(h.reviewNote!)
                                                  : null,
                                            ),
                                          )
                                          .toList(),
                                    ),
                                ],
                              ),
                            ),
                          ),
                        );
                      },
                    ),
        ),
      ],
    );
  }
}

class _ScanOverlayPane extends StatelessWidget {
  const _ScanOverlayPane({
    required this.viewModel,
    required this.review,
  });

  final StudioViewModel viewModel;
  final PageReviewPayload review;

  void _handleTapDown(
    TapDownDetails details,
    Size renderedSize,
    double naturalWidth,
    double naturalHeight,
  ) {
    final scaleX = naturalWidth / renderedSize.width;
    final scaleY = naturalHeight / renderedSize.height;
    final pageX = details.localPosition.dx * scaleX;
    final pageY = details.localPosition.dy * scaleY;

    for (final block in review.blocks) {
      final bbox = block.bbox;
      if (bbox != null && bbox.length == 4) {
        if (pageX >= bbox[0] &&
            pageX <= bbox[2] &&
            pageY >= bbox[1] &&
            pageY <= bbox[3]) {
          viewModel.selectBlock(block.blockId);
          return;
        }
      }
      final poly = block.polygon;
      if (poly != null && poly.length >= 3) {
        final xs = poly.map((p) => p[0]);
        final ys = poly.map((p) => p[1]);
        final minX = xs.reduce((a, b) => a < b ? a : b);
        final maxX = xs.reduce((a, b) => a > b ? a : b);
        final minY = ys.reduce((a, b) => a < b ? a : b);
        final maxY = ys.reduce((a, b) => a > b ? a : b);
        if (pageX >= minX &&
            pageX <= maxX &&
            pageY >= minY &&
            pageY <= maxY) {
          viewModel.selectBlock(block.blockId);
          return;
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final naturalWidth = (review.widthPx ?? 1200).toDouble();
    final naturalHeight = (review.heightPx ?? 1600).toDouble();
    final aspect = naturalWidth / naturalHeight;
    final imgUrl = viewModel.pageImageUrl(review.bookId, review.pageNumber);

    return Container(
      color: const Color(0xFFE7E1D1),
      child: InteractiveViewer(
        minScale: 0.7,
        maxScale: 4.5,
        child: Center(
          child: AspectRatio(
            aspectRatio: aspect,
            child: LayoutBuilder(
              builder: (context, constraints) {
                final size =
                    Size(constraints.maxWidth, constraints.maxHeight);
                return GestureDetector(
                  onTapDown: (details) => _handleTapDown(
                    details,
                    size,
                    naturalWidth,
                    naturalHeight,
                  ),
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      Image.network(
                        imgUrl,
                        headers: viewModel.imageHeaders,
                        fit: BoxFit.fill,
                        errorBuilder: (_, _, _) => const Center(
                          child: Text('Page scan image unavailable'),
                        ),
                      ),
                      CustomPaint(
                        painter: _ScanPolygonOverlayPainter(
                          blocks: review.blocks,
                          selectedBlockId: viewModel.selectedBlockId,
                          naturalWidth: naturalWidth,
                          naturalHeight: naturalHeight,
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
        ),
      ),
    );
  }
}

class _ScanPolygonOverlayPainter extends CustomPainter {
  _ScanPolygonOverlayPainter({
    required this.blocks,
    required this.selectedBlockId,
    required this.naturalWidth,
    required this.naturalHeight,
  });

  final List<ReviewBlock> blocks;
  final String? selectedBlockId;
  final double naturalWidth;
  final double naturalHeight;

  @override
  void paint(Canvas canvas, Size size) {
    if (naturalWidth <= 0 || naturalHeight <= 0) return;
    final scaleX = size.width / naturalWidth;
    final scaleY = size.height / naturalHeight;

    for (final block in blocks) {
      final poly = block.polygon;
      if (poly == null || poly.length < 3) continue;

      final path = Path()
        ..moveTo(poly[0][0] * scaleX, poly[0][1] * scaleY);
      for (var i = 1; i < poly.length; i++) {
        path.lineTo(poly[i][0] * scaleX, poly[i][1] * scaleY);
      }
      path.close();

      final isSelected = block.blockId == selectedBlockId;
      final isFlagged = block.isFlagged;

      final fillPaint = Paint()
        ..style = PaintingStyle.fill
        ..color = isSelected
            ? AppTheme.primary.withValues(alpha: 0.25)
            : isFlagged
                ? AppTheme.warnBorder.withValues(alpha: 0.16)
                : AppTheme.primary.withValues(alpha: 0.08);

      final strokePaint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = isSelected
            ? 2.8
            : isFlagged
                ? 1.8
                : 1.1
        ..color = isSelected
            ? AppTheme.primaryDark
            : isFlagged
                ? AppTheme.warnBorder
                : AppTheme.primary.withValues(alpha: 0.7);

      canvas.drawPath(path, fillPaint);
      canvas.drawPath(path, strokePaint);
    }
  }

  @override
  bool shouldRepaint(covariant _ScanPolygonOverlayPainter oldDelegate) {
    return oldDelegate.blocks != blocks ||
        oldDelegate.selectedBlockId != selectedBlockId;
  }
}

class _Badge extends StatelessWidget {
  const _Badge({
    required this.text,
    this.isWarn = false,
    this.isOk = false,
  });

  final String text;
  final bool isWarn;
  final bool isOk;

  @override
  Widget build(BuildContext context) {
    final bg = isOk
        ? AppTheme.okBg
        : isWarn
            ? AppTheme.warnBg
            : AppTheme.surfaceMuted;
    final fg = isOk
        ? AppTheme.okInk
        : isWarn
            ? AppTheme.warnInk
            : AppTheme.ink;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(99),
      ),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 11.5,
          fontWeight: FontWeight.w600,
          color: fg,
        ),
      ),
    );
  }
}
