import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../core/app_theme.dart';
import '../view_models/studio_view_model.dart';

class ExportTabView extends StatefulWidget {
  const ExportTabView({super.key, required this.viewModel});

  final StudioViewModel viewModel;

  @override
  State<ExportTabView> createState() => _ExportTabViewState();
}

class _ExportTabViewState extends State<ExportTabView> {
  String _exportChoice = 'docx_page_preserving';
  String _textVersion = 'human_approved';
  String _fontFamily = 'Noto Serif Telugu';
  bool _includePageNumbers = true;
  bool _includeToc = false;

  Future<void> _generateExport() async {
    final isTxt = _exportChoice == 'txt';
    final layoutMode = _exportChoice == 'docx_editable_flow'
        ? 'editable_flow'
        : 'page_preserving';

    final record = await widget.viewModel.createExport(
      format: isTxt ? 'txt' : 'docx',
      layoutMode: layoutMode,
      textVersion: _textVersion,
      fontFamily: _fontFamily,
      includePageNumbers: _includePageNumbers,
      includeTableOfContents:
          _exportChoice == 'docx_editable_flow' ? _includeToc : false,
    );
    if (record != null) {
      await _openUrl(record.downloadUrl);
    }
  }

  Future<void> _openUrl(String path) async {
    final uri = widget.viewModel.resolveDownloadUri(path);
    await launchUrl(uri, mode: LaunchMode.externalApplication);
  }

  @override
  Widget build(BuildContext context) {
    final vm = widget.viewModel;
    final book = vm.selectedBook;
    if (book == null) {
      return const Center(
        child: Text('Select a Telugu book in the Library tab first.'),
      );
    }

    final usableRuns = vm.runs
        .where((r) => r.status == 'completed' || r.status == 'partial')
        .toList();
    final needsOcrFirst =
        usableRuns.isEmpty && book.ocrTargetPagesCount > 0;

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 800),
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Export Document — ${book.title}',
                      style: Theme.of(context)
                          .textTheme
                          .titleMedium
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 6),
                    const Text(
                      'Generates genuine Telugu Unicode DOCX (page-preserving or editable-flow) or UTF-8 TXT and verifies paragraph integrity before saving.',
                      style: TextStyle(fontSize: 13, color: AppTheme.inkMuted),
                    ),
                    if (needsOcrFirst) ...[
                      const SizedBox(height: 12),
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: AppTheme.dangerBg,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: AppTheme.dangerBorder),
                        ),
                        child: Text(
                          'No completed OCR run exists for this book yet (${book.ocrTargetPagesCount} scanned/mixed pages). Run OCR from the Library tab before exporting.',
                          style: const TextStyle(color: AppTheme.dangerInk),
                        ),
                      ),
                    ],
                    const SizedBox(height: 14),
                    DropdownButtonFormField<String>(
                      initialValue: _exportChoice,
                      decoration: const InputDecoration(
                        labelText: 'Export Format & Layout Mode',
                      ),
                      items: const [
                        DropdownMenuItem(
                          value: 'docx_page_preserving',
                          child: Text('Page-preserving DOCX (.docx)'),
                        ),
                        DropdownMenuItem(
                          value: 'docx_editable_flow',
                          child: Text('Editable-flow DOCX (.docx)'),
                        ),
                        DropdownMenuItem(
                          value: 'txt',
                          child: Text('Plain Text UTF-8 (.txt)'),
                        ),
                      ],
                      onChanged: (v) {
                        if (v != null) setState(() => _exportChoice = v);
                      },
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      initialValue: _textVersion,
                      decoration: const InputDecoration(
                        labelText: 'Transcript Version',
                      ),
                      items: const [
                        DropdownMenuItem(
                          value: 'human_approved',
                          child: Text('Human-reviewed / latest edits'),
                        ),
                        DropdownMenuItem(
                          value: 'raw_ocr',
                          child: Text('Raw OCR output (unreviewed)'),
                        ),
                      ],
                      onChanged: (v) {
                        if (v != null) setState(() => _textVersion = v);
                      },
                    ),
                    if (_exportChoice != 'txt') ...[
                      const SizedBox(height: 12),
                      DropdownButtonFormField<String>(
                        initialValue: _fontFamily,
                        decoration: const InputDecoration(
                          labelText: 'Telugu Font Family',
                        ),
                        items: const [
                          DropdownMenuItem(
                            value: 'Noto Serif Telugu',
                            child: Text('Noto Serif Telugu'),
                          ),
                          DropdownMenuItem(
                            value: 'Noto Sans Telugu',
                            child: Text('Noto Sans Telugu'),
                          ),
                          DropdownMenuItem(
                            value: 'Kohinoor Telugu',
                            child: Text('Kohinoor Telugu'),
                          ),
                        ],
                        onChanged: (v) {
                          if (v != null) setState(() => _fontFamily = v);
                        },
                      ),
                      SwitchListTile(
                        contentPadding: EdgeInsets.zero,
                        value: _includePageNumbers,
                        onChanged: (v) =>
                            setState(() => _includePageNumbers = v),
                        title: const Text(
                          'Include page numbers / source page markers',
                        ),
                      ),
                      if (_exportChoice == 'docx_editable_flow')
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          value: _includeToc,
                          onChanged: (v) => setState(() => _includeToc = v),
                          title: const Text(
                            'Include Table of Contents field',
                          ),
                        ),
                    ],
                    const SizedBox(height: 12),
                    FilledButton.icon(
                      onPressed: vm.busyExport || needsOcrFirst
                          ? null
                          : _generateExport,
                      icon: const Icon(Icons.description_outlined),
                      label: Text(
                        vm.busyExport
                            ? 'Generating & Validating...'
                            : 'Generate & Download Export',
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              'Generated Exports (${vm.exports.length})',
              style: Theme.of(context)
                  .textTheme
                  .titleMedium
                  ?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 8),
            if (vm.exports.isEmpty)
              const Text(
                'No exports generated for this book yet.',
                style: TextStyle(color: AppTheme.inkMuted),
              )
            else
              ...vm.exports.map(
                (item) => Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Card(
                    child: ListTile(
                      title: Text(
                        item.filename,
                        style: const TextStyle(
                          fontWeight: FontWeight.w700,
                          fontFamilyFallback: AppTheme.teluguFontFallback,
                        ),
                      ),
                      subtitle: Text(
                        '${item.format.toUpperCase()} · ${formatLayoutMode(item.layoutMode)} · ${item.isFullyReviewed ? "Reviewed" : "Partial/Unreviewed"}${item.validationPassed ? " · ✓ Verified" : ""}',
                      ),
                      trailing: Wrap(
                        spacing: 6,
                        children: [
                          FilledButton.tonal(
                            onPressed: () => _openUrl(item.downloadUrl),
                            child: const Text('Download'),
                          ),
                          OutlinedButton(
                            onPressed: () => _openUrl(item.manifestUrl),
                            child: const Text('JSON'),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
