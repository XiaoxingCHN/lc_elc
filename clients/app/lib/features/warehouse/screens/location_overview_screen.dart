import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../widgets/lab_ui.dart';
import '../../unified/models/detail_models.dart';
import '../../unified/models/unified_item.dart';
import '../../unified/providers/inventory_providers.dart';
import '../../unified/providers/unified_providers.dart';
import '../../unified/widgets/status_views.dart';
import '../warehouse_routes.dart';

/// 仓位速览: every internal location with what is physically in it.
///
/// The list is the whole point of the section - before this the only way to see
/// a location's contents was to open a component's detail page and read its
/// distribution, i.e. you had to know WHAT you were looking for before you could
/// ask WHERE it was. Here the question is asked the other way round.
///
/// Figures come from `locations(with_stats: true)`: `bag_count` counts bags with
/// a non-zero quantity at that exact location, `quantity` sums `stock.quant`.
/// A location that was never counted shows `—`, never `0`.
class LocationOverviewScreen extends ConsumerWidget {
  const LocationOverviewScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final locations = ref.watch(inventoryLocationsWithStatsProvider);
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: LabAppBar(
        title: const Text('仓位速览'),
        actions: <Widget>[
          IconButton(
            tooltip: '新建仓位',
            onPressed: () => _createLocation(context, ref),
            icon: const Icon(Icons.add_location_alt_outlined),
          ),
          IconButton(
            tooltip: '刷新',
            onPressed: () => ref.invalidate(inventoryLocationsWithStatsProvider),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: locations.when(
        loading: () => const LoadingView(label: '正在读取仓位…'),
        error: (error, _) => ErrorView(
          message: '仓位加载失败：$error',
          onRetry: () => ref.invalidate(inventoryLocationsWithStatsProvider),
        ),
        data: (rows) {
          if (rows.isEmpty) {
            return EmptyView(
              title: '还没有仓位',
              subtitle: '新建一个仓位后会生成库码，可打印仓位标签贴到货架。',
              icon: Icons.warehouse_outlined,
              action: FilledButton.tonalIcon(
                onPressed: () => _createLocation(context, ref),
                icon: const Icon(Icons.add_location_alt_outlined),
                label: const Text('新建仓位'),
              ),
            );
          }

          // Totals across every location, for the header strip.
          var bags = 0;
          var quantity = 0.0;
          for (final row in rows) {
            bags += row.bagCount ?? 0;
            quantity += row.quantity ?? 0;
          }

          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
            children: <Widget>[
              Text(
                '${rows.length} 个仓位 · $bags 袋 · '
                '在库 ${UnifiedItem.formatQuantity(quantity)}',
                style: theme.textTheme.labelSmall,
              ),
              const SizedBox(height: 8),
              for (final row in rows)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: _LocationRow(row: row),
                ),
              const SizedBox(height: 8),
              Text(
                '袋数只算本仓位（不含子仓位）；在库数量按 stock.quant 合计。',
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          );
        },
      ),
    );
  }

  Future<void> _createLocation(BuildContext context, WidgetRef ref) async {
    final controller = TextEditingController();
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('新建仓位'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: '仓位名称（如 R01）',
            border: OutlineInputBorder(),
          ),
          onSubmitted: (value) => Navigator.pop(context, value.trim()),
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, controller.text.trim()),
            child: const Text('创建'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (name == null || name.isEmpty) return;

    try {
      final created =
          await ref.read(labApiProvider).createLocation(name: name);
      if (!context.mounted) return;
      ref.invalidate(inventoryLocationsWithStatsProvider);
      ref.invalidate(inventoryLocationsProvider);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text('已创建仓位 ${created.display}（库码 ${created.code}）'),
        ),
      );
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('新建仓位失败：$error')),
      );
    }
  }
}

class _LocationRow extends StatelessWidget {
  const _LocationRow({required this.row});

  final LabStockLocation row;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final canOpen = row.hasId;

    return InkWell(
      borderRadius: BorderRadius.circular(22),
      onTap: canOpen
          ? () => context.push(WarehouseRoutes.locationContents(row.id!))
          : null,
      child: GlassPanel(
        child: Row(
          children: <Widget>[
            Icon(
              Icons.location_on_outlined,
              size: 22,
              color: theme.colorScheme.primary,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  Text(
                    row.display,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.titleSmall,
                  ),
                  if (row.path.isNotEmpty && row.path != row.name)
                    Text(
                      row.path,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.labelSmall,
                    ),
                ],
              ),
            ),
            const SizedBox(width: 8),
            Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Text(
                  row.hasStats ? '${row.bagCount ?? 0} 袋' : '— 袋',
                  style: theme.textTheme.labelMedium
                      ?.copyWith(color: theme.colorScheme.onSurface),
                ),
                Text(
                  row.quantity == null
                      ? '—'
                      : UnifiedItem.formatQuantity(row.quantity!),
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
              ],
            ),
            if (canOpen) ...<Widget>[
              const SizedBox(width: 4),
              Icon(
                Icons.chevron_right,
                size: 18,
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ],
          ],
        ),
      ),
    );
  }
}
