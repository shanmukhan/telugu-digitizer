import 'package:flutter/material.dart';

import '../../../core/app_theme.dart';
import '../view_models/studio_view_model.dart';
import 'correction_memory_tab_view.dart';
import 'export_tab_view.dart';
import 'library_tab_view.dart';
import 'page_review_tab_view.dart';
import 'server_settings_sheet.dart';

class StudioHomeView extends StatefulWidget {
  const StudioHomeView({super.key, required this.viewModel});

  final StudioViewModel viewModel;

  @override
  State<StudioHomeView> createState() => _StudioHomeViewState();
}

class _StudioHomeViewState extends State<StudioHomeView> {
  int _selectedIndex = 0;

  void _openSettings() {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (_) => ServerSettingsSheet(viewModel: widget.viewModel),
    );
  }

  @override
  Widget build(BuildContext context) {
    final vm = widget.viewModel;
    return ListenableBuilder(
      listenable: vm,
      builder: (context, _) {
        final pages = <Widget>[
          LibraryTabView(
            viewModel: vm,
            onOpenReview: () => setState(() => _selectedIndex = 1),
            onOpenExport: () => setState(() => _selectedIndex = 3),
          ),
          PageReviewTabView(viewModel: vm),
          CorrectionMemoryTabView(viewModel: vm),
          ExportTabView(viewModel: vm),
        ];

        return LayoutBuilder(
          builder: (context, constraints) {
            final useRail = constraints.maxWidth >= 840;
            return Scaffold(
              appBar: AppBar(
                title: Row(
                  children: [
                    Container(
                      width: 34,
                      height: 34,
                      alignment: Alignment.center,
                      decoration: BoxDecoration(
                        color: AppTheme.primary,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: const Text(
                        'తె',
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                          fontSize: 18,
                          color: Colors.white,
                          fontFamilyFallback: AppTheme.teluguFontFallback,
                        ),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            'Telugu Book Digitizer',
                            style: TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                          Text(
                            vm.selectedBook?.title ?? vm.baseUrl,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              fontSize: 11.5,
                              color: Color(0xFFDFF3EE),
                              fontFamilyFallback: AppTheme.teluguFontFallback,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
                actions: [
                  _ConnectionPill(viewModel: vm, onTap: _openSettings),
                  IconButton(
                    tooltip: 'Server Settings',
                    onPressed: _openSettings,
                    icon: const Icon(Icons.settings_outlined),
                  ),
                ],
              ),
              body: Column(
                children: [
                  // Core Commitments Strip
                  Container(
                    width: double.infinity,
                    padding:
                        const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
                    color: const Color(0xFF06302A),
                    child: const SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: Row(
                        children: [
                          Text(
                            '🔒 Local/Self-Hosted  ·  🧾 Raw OCR Never Overwritten  ·  ✍️ No Silent Auto-Correction  ·  📄 Source PDF Read-Only',
                            style: TextStyle(
                              color: Color(0xFFDFF3EE),
                              fontSize: 11.5,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  if (vm.bannerMessage != null)
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 8,
                      ),
                      color: vm.bannerIsError
                          ? AppTheme.dangerBg
                          : AppTheme.okBg,
                      child: Row(
                        children: [
                          Expanded(
                            child: Text(
                              vm.bannerMessage!,
                              style: TextStyle(
                                color: vm.bannerIsError
                                    ? AppTheme.dangerInk
                                    : AppTheme.okInk,
                                fontSize: 13,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ),
                          IconButton(
                            visualDensity: VisualDensity.compact,
                            onPressed: vm.clearBanner,
                            icon: const Icon(Icons.close, size: 18),
                          ),
                        ],
                      ),
                    ),
                  Expanded(
                    child: useRail
                        ? Row(
                            children: [
                              NavigationRail(
                                selectedIndex: _selectedIndex,
                                onDestinationSelected: (idx) =>
                                    setState(() => _selectedIndex = idx),
                                labelType: NavigationRailLabelType.all,
                                destinations: const [
                                  NavigationRailDestination(
                                    icon: Icon(Icons.library_books_outlined),
                                    selectedIcon: Icon(Icons.library_books),
                                    label: Text('Library'),
                                  ),
                                  NavigationRailDestination(
                                    icon: Icon(Icons.fact_check_outlined),
                                    selectedIcon: Icon(Icons.fact_check),
                                    label: Text('Review'),
                                  ),
                                  NavigationRailDestination(
                                    icon: Icon(Icons.psychology_outlined),
                                    selectedIcon: Icon(Icons.psychology),
                                    label: Text('Memory'),
                                  ),
                                  NavigationRailDestination(
                                    icon: Icon(Icons.download_outlined),
                                    selectedIcon: Icon(Icons.download),
                                    label: Text('Export'),
                                  ),
                                ],
                              ),
                              const VerticalDivider(width: 1),
                              Expanded(child: pages[_selectedIndex]),
                            ],
                          )
                        : pages[_selectedIndex],
                  ),
                ],
              ),
              bottomNavigationBar: useRail
                  ? null
                  : NavigationBar(
                      selectedIndex: _selectedIndex,
                      onDestinationSelected: (idx) =>
                          setState(() => _selectedIndex = idx),
                      destinations: const [
                        NavigationDestination(
                          icon: Icon(Icons.library_books_outlined),
                          selectedIcon: Icon(Icons.library_books),
                          label: 'Library',
                        ),
                        NavigationDestination(
                          icon: Icon(Icons.fact_check_outlined),
                          selectedIcon: Icon(Icons.fact_check),
                          label: 'Page Review',
                        ),
                        NavigationDestination(
                          icon: Icon(Icons.psychology_outlined),
                          selectedIcon: Icon(Icons.psychology),
                          label: 'Memory',
                        ),
                        NavigationDestination(
                          icon: Icon(Icons.download_outlined),
                          selectedIcon: Icon(Icons.download),
                          label: 'Export',
                        ),
                      ],
                    ),
            );
          },
        );
      },
    );
  }
}

class _ConnectionPill extends StatelessWidget {
  const _ConnectionPill({required this.viewModel, required this.onTap});

  final StudioViewModel viewModel;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final activeRun = viewModel.primaryActiveRun;
    final String label;
    final Color dotColor;
    if (activeRun != null) {
      label =
          'OCR ${activeRun.progressCurrent}/${activeRun.progressTotal}';
      dotColor = Colors.amberAccent;
    } else if (viewModel.serverConnected) {
      label = 'Online';
      dotColor = Colors.greenAccent;
    } else {
      label = 'Offline';
      dotColor = Colors.redAccent;
    }

    return InkWell(
      borderRadius: BorderRadius.circular(99),
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(
          color: Colors.white.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(99),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 8,
              height: 8,
              decoration: BoxDecoration(
                color: dotColor,
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 6),
            Text(
              label,
              style: const TextStyle(
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
