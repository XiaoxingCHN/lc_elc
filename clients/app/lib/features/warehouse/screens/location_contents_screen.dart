import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../widgets/lab_ui.dart';
import '../../unified/models/detail_models.dart';
import '../../unified/models/unified_item.dart';
import '../../unified/providers/inventory_providers.dart';
import '../../unified/unified_routes.dart';
import '../../unified/widgets/status_views.dart';
import '../providers/warehouse_providers.dart';

/// 仓位内容: the bags physically sitting in one location.
///
/// This is the "否" branch of the operator's flow chart - scan a location code,
/// answer "not receiving", and land here. It is also the only place in the
/// client that lists bags directly: everywhere else a bag is reached through a
/// component or a trace code.
///
/// Three actions, in the order the operator needs them at a shelf: receive into
/// THIS location (prefilled and locked), print this location's own label, and
/// reload after walking the aisle.
class LocationContentsScreen extends ConsumerStatefulWidget {
  const LocationContentsScreen({super.key, required this.locationId});

  final int locationId;

  @override
  ConsumerState<LocationContentsScreen> createState() =>
      _LocationContentsScreenState();
}

class _LocationContentsScreenState
    extends ConsumerState<LocationContentsScreen> {
  final ScrollController _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(_maybeLoadMore);
  }

  @override
  void dispose() {
    _scroll.removeListener(_maybeLoadMore);
    _scroll.dispose();
    super.dispose();
  }

  void _maybeLoadMore() {
    if (!_scroll.hasClients) return;
    if (_scroll.position.extentAfter > 400) return;
    final notifier = ref.read(locationBagsProvider(widget.locationId).notifier);
    final state = ref.read(locationBagsProvider(widget.locationId));
    if (state.hasMore && !state.loadingMore) {
      notifier.loadMore();
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(locationBagsProvider(widget.locationId));
    final locations = ref.watch(inventoryLocationsWithStatsProvider);
    final theme = Theme.of(context);
    final location = locations.valueOrNull
        ?.where((row) => row.id == widget.locationId)
        .firstOrNull;

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: LabAppBar(
        title: Text(location?.display ?? '仓位内容'),
        actions: <Widget>[
          IconButton(
            tooltip: '打印仓位标签',
            onPressed: () => context.push(
              UnifiedRoutes.labelsForLocation(widget.locationId),
            ),
            icon: const Icon(Icons.print_outlined),
          ),
          IconButton(
            tooltip: '刷新',
            onPressed: () => ref
                .read(locationBagsProvider(widget.locationId).notifier)
                .refresh(),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () => ref
            .read(locationBagsProvider(widget.locationId).notifier)
            .refresh(),
        child: _body(context, ref, state, location, theme),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.push(
          Uri(
            path: UnifiedRoutes.receipt,
            queryParameters: <String, String>{
              'location_id': '${widget.locationId}',
            },
          ).toString(),
        ),
        icon: const Icon(Icons.add),
        label: const Text('录入库存'),
      ),
    );
  }

  Widget _body(
    BuildContext context,
    WidgetRef ref,
    LocationBagsState state,
    LabStockLocation? location,
    ThemeData theme,
  ) {
    if (state.loading && state.bags.isEmpty) {
      return const LoadingView(label: '正在读取仓位内容…');
    }
    if (state.error != null && state.bags.isEmpty) {
      return ListView(
        padding: const EdgeInsets.all(24),
        children: <Widget>[
          ErrorView(
            message: '仓位内容加载失败：${state.error}',
            code: state.errorCode,
            onRetry: () => ref
                .read(locationBagsProvider(widget.locationId).notifier)
                .refresh(),
          ),
        ],
      );
    }
    if (state.isEmpty) {
      return ListView(
        padding: const EdgeInsets.all(24),
        children: <Widget>[
          EmptyView(
            title: '这个仓位还没有实物袋',
            subtitle: '从这里录入，或先制袋贴标再扫码上架。',
            icon: Icons.inbox_outlined,
            action: FilledButton.tonalIcon(
              onPressed: () => context.push(
                Uri(
                  path: UnifiedRoutes.receipt,
                  queryParameters: <String, String>{
                    'location_id': '${widget.locationId}',
                  },
                ).toString(),
              ),
              icon: const Icon(Icons.add),
              label: const Text('录入库存'),
            ),
          ),
        ],
      );
    }

    var total = 0.0;
    for (final bag in state.bags) {
      total += bag.quantity ?? 0;
    }

    return ListView.separated(
      controller: _scroll,
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 96),
      itemCount: state.bags.length + 2,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (context, index) {
        if (index == 0) {
          return Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                if (location != null)
                  Text(
                    '库码 ${location.code}'
                    '${location.path.isNotEmpty ? ' · ${location.path}' : ''}',
                    style: theme.textTheme.labelSmall,
                  ),
                const SizedBox(height: 2),
                Text(
                  '${state.bags.length}${state.hasMore ? '+' : ''} 袋 · '
                  '已载入合计 ${UnifiedItem.formatQuantity(total)}',
                  style: theme.textTheme.titleSmall,
                ),
              ],
            ),
          );
        }
        if (index == state.bags.length + 1) {
          if (state.loadingMore) {
            return const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: Center(
                child: SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
            );
          }
          if (state.error != null) {
            return Padding(
              padding: const EdgeInsets.only(top: 8),
              child: StatusBannerInline(message: state.error!),
            );
          }
          return const SizedBox.shrink();
        }
        return _BagRow(bag: state.bags[index - 1]);
      },
    );
  }
}

class _BagRow extends StatelessWidget {
  const _BagRow({required this.bag});

  final LabBag bag;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return GlassPanel(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      child: Row(
        children: <Widget>[
          Icon(
            Icons.inventory_2_outlined,
            size: 20,
            color: theme.colorScheme.onSurfaceVariant,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(
                  bag.itemName.isNotEmpty ? bag.itemName : bag.traceCode,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.bodyMedium,
                ),
                Text(
                  <String>[
                    bag.traceCode,
                    if (bag.sn.isNotEmpty) 'SN ${bag.sn}',
                    if (bag.uom.isNotEmpty) bag.uom,
                  ].join(' · '),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.labelSmall,
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text(
            bag.quantity == null
                ? '—'
                : UnifiedItem.formatQuantity(bag.quantity!),
            style: theme.textTheme.titleSmall,
          ),
        ],
      ),
    );
  }
}

/// A compact failure strip used inside a list (the full [ErrorView] is a page).
class StatusBannerInline extends StatelessWidget {
  const StatusBannerInline({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: <Widget>[
        Icon(Icons.error_outline, size: 16, color: theme.colorScheme.error),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            message,
            style: theme.textTheme.labelSmall
                ?.copyWith(color: theme.colorScheme.error),
          ),
        ),
      ],
    );
  }
}
