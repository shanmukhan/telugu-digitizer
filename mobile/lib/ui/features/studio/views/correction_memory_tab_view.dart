import 'package:flutter/material.dart';

import '../../../core/app_theme.dart';
import '../view_models/studio_view_model.dart';

class CorrectionMemoryTabView extends StatefulWidget {
  const CorrectionMemoryTabView({super.key, required this.viewModel});

  final StudioViewModel viewModel;

  @override
  State<CorrectionMemoryTabView> createState() =>
      _CorrectionMemoryTabViewState();
}

class _CorrectionMemoryTabViewState extends State<CorrectionMemoryTabView> {
  final TextEditingController _searchController = TextEditingController();
  String _statusFilter = 'all';
  bool _bookOnly = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _reload();
    });
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _reload() async {
    await widget.viewModel.loadCorrections(
      bookOnly: _bookOnly,
      statusFilter: _statusFilter,
      query: _searchController.text,
    );
  }

  @override
  Widget build(BuildContext context) {
    final vm = widget.viewModel;
    final items = vm.corrections;

    // Detect conflicting active mappings sharing the same incorrect_text
    final targetsByIncorrect = <String, Set<String>>{};
    for (final item in items) {
      if (item.status != 'active') continue;
      targetsByIncorrect
          .putIfAbsent(item.incorrectText, () => <String>{})
          .add(item.correctedText);
    }

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 960),
        child: Column(
          children: [
            Card(
              margin: const EdgeInsets.all(12),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: TextField(
                            controller: _searchController,
                            decoration: const InputDecoration(
                              hintText: 'Search Telugu word or phrase…',
                              prefixIcon: Icon(Icons.search),
                              isDense: true,
                            ),
                            onSubmitted: (_) => _reload(),
                          ),
                        ),
                        const SizedBox(width: 8),
                        FilledButton(
                          onPressed: vm.busyCorrections ? null : _reload,
                          child: const Text('Search'),
                        ),
                      ],
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      crossAxisAlignment: WrapCrossAlignment.center,
                      children: [
                        for (final st in const [
                          'all',
                          'active',
                          'disabled',
                          'rejected',
                        ])
                          ChoiceChip(
                            label: Text(st.toUpperCase()),
                            selected: _statusFilter == st,
                            onSelected: (_) {
                              setState(() => _statusFilter = st);
                              _reload();
                            },
                          ),
                        if (vm.selectedBookId != null)
                          FilterChip(
                            label: const Text('Selected book only'),
                            selected: _bookOnly,
                            onSelected: (v) {
                              setState(() => _bookOnly = v);
                              _reload();
                            },
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            Expanded(
              child: vm.busyCorrections
                  ? const Center(child: CircularProgressIndicator())
                  : items.isEmpty
                      ? const Center(
                          child: Text('No correction memory records found.'),
                        )
                      : ListView.builder(
                          padding: const EdgeInsets.symmetric(horizontal: 12),
                          itemCount: items.length,
                          itemBuilder: (context, index) {
                            final item = items[index];
                            final hasConflict = item.status == 'active' &&
                                (targetsByIncorrect[item.incorrectText]
                                            ?.length ??
                                        0) >
                                    1;
                            return Padding(
                              padding: const EdgeInsets.only(bottom: 8),
                              child: Card(
                                child: ListTile(
                                  title: Text(
                                    '${item.incorrectText} → ${item.correctedText}',
                                    style: const TextStyle(
                                      fontWeight: FontWeight.w700,
                                      fontSize: 16,
                                      fontFamilyFallback:
                                          AppTheme.teluguFontFallback,
                                    ),
                                  ),
                                  subtitle: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        'Context: ${item.leftContext ?? "—"} | ${item.rightContext ?? "—"}',
                                        style: const TextStyle(
                                          fontFamilyFallback:
                                              AppTheme.teluguFontFallback,
                                        ),
                                      ),
                                      const SizedBox(height: 4),
                                      Wrap(
                                        spacing: 6,
                                        runSpacing: 4,
                                        children: [
                                          Chip(
                                            visualDensity:
                                                VisualDensity.compact,
                                            label: Text(item.scope),
                                          ),
                                          Chip(
                                            visualDensity:
                                                VisualDensity.compact,
                                            label: Text(item.status),
                                          ),
                                          Chip(
                                            visualDensity:
                                                VisualDensity.compact,
                                            label: Text(
                                              '+${item.approvedCount} / -${item.rejectedCount}',
                                            ),
                                          ),
                                          if (hasConflict)
                                            const Chip(
                                              visualDensity:
                                                  VisualDensity.compact,
                                              backgroundColor: AppTheme.warnBg,
                                              label: Text('⚠ Conflict'),
                                            ),
                                        ],
                                      ),
                                    ],
                                  ),
                                  trailing: Wrap(
                                    spacing: 6,
                                    children: [
                                      if (item.scope == 'book_only')
                                        TextButton(
                                          onPressed: () =>
                                              vm.promoteCorrectionToGlobal(
                                                  item),
                                          child: const Text('Promote'),
                                        ),
                                      OutlinedButton(
                                        onPressed: () =>
                                            vm.toggleCorrectionStatus(item),
                                        child: Text(
                                          item.status == 'active'
                                              ? 'Disable'
                                              : 'Re-enable',
                                        ),
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
        ),
      ),
    );
  }
}
