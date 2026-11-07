import 'package:lab_inventory_client/widgets/lab_ui.dart';

import 'dart:async';

import '../../../updates/update_ui.dart';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../models/catalog_query.dart';
import '../models/unified_item.dart';
import '../providers/catalog_providers.dart';
import '../providers/offline_providers.dart';
import '../unified_routes.dart';
import '../widgets/category_sidebar.dart';
import '../widgets/filter_panel.dart';
import '../widgets/item_card.dart';
import '../widgets/status_banner.dart';
import '../widgets/status_views.dart';
import 'offline_views.dart';

/// THE unified component library - the app's single entry point for materials.
///
/// There is deliberately no separate "internal stock library" and "LCSC library"
/// screen: one server query merges captured catalog data with local materials,
/// one card per canonical identity, in-stock first (a server-side global order).
///
/// Responsive behaviour:
///   * width >= 900 (Windows / Linux desktop, landscape tablet): category sidebar
///     on the left, grid on the right, filters in an end drawer;
///   * width < 900 (phone): grid with a toolbar; the whole filter panel is folded
///     into the navigation drawer.
class UnifiedCatalogScreen extends ConsumerStatefulWidget {
  const UnifiedCatalogScreen({
    super.key,
    this.initialQuery,
    this.initialCategoryId,
    this.offline = false,
  });

  /// Optional deep-link values (e.g. from the home screen search box).
  final String? initialQuery;
  final int? initialCategoryId;

  /// Public offline mode (`/catalog?offline=1`): the SAME library, read-only, with
  /// no session. The offline view is rendered by [OfflineCatalogView].
  final bool offline;

  @override
  ConsumerState<UnifiedCatalogScreen> createState() =>
      _UnifiedCatalogScreenState();
}

class _UnifiedCatalogScreenState extends ConsumerState<UnifiedCatalogScreen> {
  bool _grid = true;
  bool _bootstrapped = false;

  /// Kept as a raw controller: `ref` may no longer be used in [dispose], but the
  /// offline flag must still be cleared when the browser is left.
  StateController<bool>? _offlineMode;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (widget.offline) {
        // Publish the mode so every media widget reads the public cache and no
        // credential is ever used while browsing offline.
        final controller = ref.read(offlineCatalogModeProvider.notifier);
        _offlineMode = controller;
        controller.state = true;
        return;
      }
      _bootstrap();
    });
  }

  @override
  void dispose() {
    // Leaving the offline browser must not leave the app in offline mode.
    _offlineMode?.state = false;
    super.dispose();
  }

  void _bootstrap() {
    if (!mounted || _bootstrapped) return;
    _bootstrapped = true;

    final notifier = ref.read(catalogProvider.notifier);
    final query = ref.read(catalogQueryProvider);
    final wantsQuery =
        (widget.initialQuery?.trim().isNotEmpty ?? false) ||
        widget.initialCategoryId != null;

    if (wantsQuery) {
      unawaited(
        notifier.updateQuery(
          query.copyWith(
            text: widget.initialQuery?.trim() ?? query.text,
            categoryId: widget.initialCategoryId ?? query.categoryId,
          ),
        ),
      );
      return;
    }

    final state = ref.read(catalogProvider);
    if (state.items.isEmpty && !state.loading && state.error == null) {
      unawaited(notifier.refresh());
    }
  }

  void _selectCategory(int? categoryId) {
    final query = ref.read(catalogQueryProvider);
    if (query.categoryId == categoryId) return;
    unawaited(
      ref
          .read(catalogProvider.notifier)
          .updateQuery(query.copyWith(categoryId: categoryId)),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (widget.offline) {
      // The offline browser is the same library with a read-only body: one route,
      // one card widget, no second library screen.
      return Scaffold(
        appBar: LabAppBar(
          leading: const LabBackButton(fallbackLocation: '/login'),
          title: const Text('仓库（离线缓存）'),
          actions: <Widget>[
            IconButton(
              tooltip: '重新读取本机缓存',
              onPressed: () => ref.invalidate(offlineCatalogEntriesProvider),
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        body: const OfflineCatalogView(),
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 900;
        final selectedCategory = ref.watch(
          catalogProvider.select((state) => state.query.categoryId),
        );

        final body = _CatalogBody(
          grid: _grid,
          wide: wide,
          onToggleView: () => setState(() => _grid = !_grid),
        );

        return Scaffold(
          appBar: LabAppBar(
            title: const Text('仓库'),
            actions: <Widget>[
              const ClientUpdateButton(),
              IconButton(
                tooltip: _grid ? '切换为列表' : '切换为网格',
                onPressed: () => setState(() => _grid = !_grid),
                icon: Icon(_grid ? Icons.view_list : Icons.grid_view),
              ),
              IconButton(
                tooltip: '刷新',
                onPressed: () =>
                    unawaited(ref.read(catalogProvider.notifier).refresh()),
                icon: const Icon(Icons.refresh),
              ),
              _FilterButton(wide: wide),
              const SizedBox(width: 4),
            ],
          ),
          // Phones: everything folds into the drawer ("折叠筛选drawer").
          drawer: wide
              ? null
              : const FilterDrawer(child: FilterPanel(showCategories: true)),
          // Desktop: filters stay reachable without stealing grid width.
          endDrawer: wide ? const FilterDrawer(child: FilterPanel()) : null,
          floatingActionButton: FloatingActionButton.extended(
            onPressed: () => context.push(UnifiedRoutes.pendingReceipt),
            icon: const Icon(Icons.qr_code_scanner),
            label: const Text('采购入库'),
          ),
          body: wide
              ? Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                    CategorySidebar(
                      selectedId: selectedCategory,
                      onSelected: _selectCategory,
                    ),
                    const VerticalDivider(width: 1),
                    Expanded(child: body),
                  ],
                )
              : body,
        );
      },
    );
  }
}

/// Toolbar button that opens the filter drawer and shows how many filters are on.
class _FilterButton extends ConsumerWidget {
  const _FilterButton({required this.wide});

  final bool wide;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final count = ref.watch(
      catalogProvider.select((state) => state.query.activeFilterCount),
    );
    return IconButton(
      tooltip: '筛选条件',
      onPressed: () {
        final scaffold = Scaffold.maybeOf(context);
        if (scaffold == null) return;
        if (wide) {
          scaffold.openEndDrawer();
        } else {
          scaffold.openDrawer();
        }
      },
      icon: Badge(
        isLabelVisible: count > 0,
        label: Text('$count'),
        child: const Icon(Icons.tune),
      ),
    );
  }
}

class _CatalogBody extends ConsumerWidget {
  const _CatalogBody({
    required this.grid,
    required this.wide,
    required this.onToggleView,
  });

  final bool grid;
  final bool wide;
  final VoidCallback onToggleView;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(catalogProvider);
    final theme = Theme.of(context);

    if (state.loading && state.items.isEmpty) {
      return const LoadingView(label: '正在检索已采集资料…');
    }
    if (state.error != null && state.items.isEmpty) {
      return ErrorView(
        message: state.error!,
        code: state.errorCode,
        onRetry: () => unawaited(ref.read(catalogProvider.notifier).refresh()),
      );
    }
    if (state.isEmpty) {
      return _buildEmpty(context, ref, state);
    }

    return Column(
      children: <Widget>[
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: Row(
            children: <Widget>[
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      '已加载 ${state.loadedCount} 条'
                      '${state.total > 0 ? ' / 共 ${state.total} 条' : ''}',
                      style: theme.textTheme.labelSmall,
                    ),
                    Text(
                      state.query.description,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              if (state.loading)
                const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
            ],
          ),
        ),
        if (state.error != null)
          StatusBanner(
            message: '加载下一页失败：${state.error}',
            tone: StatusTone.error,
            dense: true,
            action: TextButton(
              onPressed: () =>
                  unawaited(ref.read(catalogProvider.notifier).loadMore()),
              child: const Text('重试'),
            ),
          ),
        Expanded(
          child: NotificationListener<ScrollNotification>(
            onNotification: (notification) {
              if (notification.metrics.extentAfter < 600) {
                unawaited(ref.read(catalogProvider.notifier).loadMore());
              }
              return false;
            },
            child: grid
                ? _buildGrid(context, ref, state)
                : _buildList(context, ref, state),
          ),
        ),
      ],
    );
  }

  void _openDetail(BuildContext context, UnifiedItem item) {
    context.push(UnifiedRoutes.itemDetail(item.itemKey));
  }

  Widget _buildGrid(BuildContext context, WidgetRef ref, CatalogState state) {
    return GridView.builder(
      padding: const EdgeInsets.all(8),
      gridDelegate: SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: wide ? 240 : 200,
        mainAxisSpacing: 8,
        crossAxisSpacing: 8,
        // A fixed cell height is far more predictable than an aspect ratio when
        // the text length and the quantities vary (phones are the tight case).
        mainAxisExtent: wide ? 292 : 268,
      ),
      itemCount: state.items.length + 1,
      itemBuilder: (context, index) {
        if (index >= state.items.length) return _footer(context, ref, state);
        final item = state.items[index];
        return ItemCard(
          item: item,
          imageHeight: wide ? 84 : 72,
          onTap: () => _openDetail(context, item),
          onReceipt: () => context.push(UnifiedRoutes.receiptFor(item)),
          onIssue: () => context.push(UnifiedRoutes.issueFor(item)),
        );
      },
    );
  }

  Widget _buildList(BuildContext context, WidgetRef ref, CatalogState state) {
    return ListView.builder(
      padding: const EdgeInsets.all(8),
      itemCount: state.items.length + 1,
      itemBuilder: (context, index) {
        if (index >= state.items.length) return _footer(context, ref, state);
        final item = state.items[index];
        return Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: ItemListTile(
            item: item,
            onTap: () => _openDetail(context, item),
            onReceipt: () => context.push(UnifiedRoutes.receiptFor(item)),
            onIssue: () => context.push(UnifiedRoutes.issueFor(item)),
          ),
        );
      },
    );
  }

  Widget _footer(BuildContext context, WidgetRef ref, CatalogState state) {
    if (!state.hasMore) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Center(
          child: Text(
            '已到最后一条（共 ${state.loadedCount} 条）',
            style: Theme.of(context).textTheme.labelSmall,
          ),
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Center(
        child: state.loadingMore
            ? const SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(strokeWidth: 2),
              )
            : OutlinedButton.icon(
                onPressed: () =>
                    unawaited(ref.read(catalogProvider.notifier).loadMore()),
                icon: const Icon(Icons.expand_more),
                label: const Text('加载更多'),
              ),
      ),
    );
  }

  /// Zero rows: keep the real empty message, and offer the server's on-demand
  /// fetch only when it explicitly said the query is one exact C code / MPN.
  Widget _buildEmpty(BuildContext context, WidgetRef ref, CatalogState state) {
    final theme = Theme.of(context);
    final notifier = ref.read(catalogProvider.notifier);
    final suggestion = state.fetchSuggestion;
    final status = state.fetchStatus;
    final running = status != null && !status.isTerminal;
    final canFetch = suggestion != null && suggestion.isValid && !running;

    final actions = <Widget>[
      if (canFetch)
        FilledButton.icon(
          onPressed: state.fetchBusy
              ? null
              : () => unawaited(notifier.startFetch()),
          icon: state.fetchBusy
              ? const SizedBox(
                  width: 16,
                  height: 16,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.travel_explore),
          label: Text(status == null ? '立即从立创商城抓取' : '重新抓取'),
        ),
      if (state.query.isFiltered)
        TextButton(
          onPressed: () =>
              unawaited(notifier.updateQuery(const CatalogQuery())),
          child: const Text('清空筛选'),
        ),
    ];

    return SingleChildScrollView(
      padding: const EdgeInsets.symmetric(vertical: 24),
      child: Column(
        children: <Widget>[
          EmptyView(
            title: '没有匹配的器件',
            subtitle: state.query.isFiltered
                ? (state.query.text.trim().isEmpty
                      ? '当前条件：${state.query.description}。可清空筛选后重试。'
                      : '当前条件：${state.query.description}。参数可换写法：10R = 10Ω、'
                            '4R7 = 4.7Ω、100nF = 0.1uF。')
                : '服务端没有返回任何已采集资料。',
            action: actions.isEmpty
                ? null
                : Wrap(
                    alignment: WrapAlignment.center,
                    spacing: 8,
                    runSpacing: 8,
                    children: actions,
                  ),
          ),
          if (suggestion != null && suggestion.message.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 4, 24, 0),
              child: Text(
                suggestion.message,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ),
          if (status != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
              child: _FetchStatusPanel(
                status: status,
                onChoose: (candidate) =>
                    unawaited(notifier.chooseFetchCandidate(candidate)),
              ),
            ),
        ],
      ),
    );
  }
}

/// Progress and result of one on-demand LCSC fetch.
///
/// Every state pairs its colour with an icon and words; candidates are real
/// buttons because the server only lists variants whose MPN matched exactly.
class _FetchStatusPanel extends StatelessWidget {
  const _FetchStatusPanel({
    required this.status,
    required this.onChoose,
  });

  final CatalogFetchStatus status;
  final ValueChanged<CatalogFetchCandidate> onChoose;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final running = !status.isTerminal;
    final (IconData icon, Color tone) = switch (status.state) {
      'done' => (Icons.check_circle_outline, theme.colorScheme.primary),
      'failed' || 'not_found' => (
          Icons.error_outline,
          theme.colorScheme.error,
        ),
      'skipped_non_electronic' => (
          Icons.block,
          theme.colorScheme.onSurfaceVariant,
        ),
      'review' => (Icons.fact_check_outlined, theme.colorScheme.tertiary),
      _ => (Icons.hourglass_top, theme.colorScheme.primary),
    };

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Icon(icon, size: 20, color: tone),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _title(status.state),
                    style: theme.textTheme.titleSmall,
                  ),
                ),
              ],
            ),
            if (running) ...<Widget>[
              const SizedBox(height: 12),
              const LinearProgressIndicator(),
              const SizedBox(height: 8),
              Text(
                status.state == 'queued'
                    ? '排队等待后台处理，通常一分钟内开始。可离开本页，稍后回来再查。'
                    : '正在读取立创商城的中文详情页，请稍候…',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
            if (!running && status.message.isNotEmpty) ...<Widget>[
              const SizedBox(height: 8),
              Text(status.message, style: theme.textTheme.bodySmall),
            ],
            if (status.isDone && status.message.isEmpty) ...<Widget>[
              const SizedBox(height: 8),
              Text('已写入器件库，正在刷新检索结果…',
                  style: theme.textTheme.bodySmall),
            ],
            if (status.isCandidates && status.candidates.isNotEmpty) ...<Widget>[
              const SizedBox(height: 12),
              Text(
                '型号匹配到多个封装，请选择要入库的一个：',
                style: theme.textTheme.bodyMedium,
              ),
              const SizedBox(height: 4),
              ...status.candidates.map(
                (candidate) => ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(candidate.label),
                  trailing: TextButton(
                    onPressed: () => onChoose(candidate),
                    child: const Text('抓取'),
                  ),
                ),
              ),
              Text(
                '不确定时请先核对封装，避免把同系列不同封装的参数写进同一条记录。',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  static String _title(String state) {
    switch (state) {
      case 'queued':
        return '已加入抓取队列';
      case 'resolving':
        return '正在立创商城匹配型号';
      case 'fetching':
        return '正在抓取中文详情';
      case 'done':
        return '已抓取并入库';
      case 'failed':
        return '抓取失败';
      case 'skipped_non_electronic':
        return '已跳过：非电子元器件';
      case 'review':
        return '已记录，分类需人工复核';
      case 'not_found':
        return '立创商城未找到完全匹配的型号';
      case 'candidates':
        return '型号匹配到多个结果';
      default:
        return '抓取状态';
    }
  }
}
