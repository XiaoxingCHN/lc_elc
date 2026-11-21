import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../widgets/lab_ui.dart';
import '../../unified/models/unified_item.dart';
import '../../unified/unified_routes.dart';
import '../../unified/widgets/item_card.dart';
import '../../unified/widgets/status_views.dart';
import '../providers/warehouse_providers.dart';
import '../widgets/stat_tile.dart';
import '../warehouse_routes.dart';

/// 库存速览: what the lab holds, in one screen.
///
/// This is the signed-in landing. It answers three questions the operator used
/// to have to assemble by hand - how many distinct parts, how many locations,
/// how much stock - and then offers the two things they do next (find a part,
/// go to a location). It is deliberately NOT a second library: the "有库存器件"
/// list is a short cut into the real one, and the whole page is one server
/// round-trip group.
class StockOverviewScreen extends ConsumerWidget {
  const StockOverviewScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final overview = ref.watch(stockOverviewProvider);
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: LabAppBar(
        title: const Text('库存速览'),
        actions: <Widget>[
          IconButton(
            tooltip: '刷新',
            onPressed: () => ref.invalidate(stockOverviewProvider),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: overview.when(
        loading: () => const LoadingView(label: '正在汇总库存…'),
        error: (error, _) => ErrorView(
          message: '库存速览加载失败：$error',
          onRetry: () => ref.invalidate(stockOverviewProvider),
        ),
        data: (data) {
          if (data.isEmpty) {
            return EmptyView(
              title: '库里还没有器件',
              subtitle: '先去「器件库」检索或抓取资料，再制袋入库。',
              icon: Icons.inventory_2_outlined,
              action: FilledButton.tonalIcon(
                onPressed: () => context.go(UnifiedRoutes.catalog),
                icon: const Icon(Icons.search),
                label: const Text('打开器件库'),
              ),
            );
          }
          return ListView(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
            children: <Widget>[
              GlassPanel(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text('当前库存', style: theme.textTheme.titleSmall),
                    const SizedBox(height: 12),
                    StatRow(
                      tiles: <Widget>[
                        StatTile(
                          label: '器件种类',
                          value: '${data.itemCount}',
                          icon: Icons.category_outlined,
                        ),
                        StatTile(
                          label: '有库存器件',
                          value: '${data.inStockItemCount}',
                          icon: Icons.check_circle_outline,
                          highlight: data.inStockItemCount > 0,
                        ),
                        StatTile(
                          label: '仓位',
                          value: '${data.locationCount}',
                          icon: Icons.warehouse_outlined,
                        ),
                        StatTile(
                          label: '实物袋',
                          value: '${data.bagCount}',
                          icon: Icons.inventory_outlined,
                        ),
                        StatTile(
                          label: '在库数量',
                          value: UnifiedItem.formatQuantity(data.totalQuantity),
                          icon: Icons.numbers,
                          highlight: data.totalQuantity > 0,
                          subtitle: '按 stock.quant 合计',
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),

              // ---- where things are (compact strip, full list one tap away) --
              if (data.locations.isNotEmpty) ...<Widget>[
                GlassPanel(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Row(
                        children: <Widget>[
                          Expanded(
                            child: Text('仓位分布', style: theme.textTheme.titleSmall),
                          ),
                          TextButton(
                            onPressed: () => context.go(WarehouseRoutes.locations),
                            child: const Text('全部仓位'),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      for (final location in data.locations.take(5))
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          child: Row(
                            children: <Widget>[
                              Icon(
                                Icons.location_on_outlined,
                                size: 16,
                                color: theme.colorScheme.onSurfaceVariant,
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  location.display,
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: theme.textTheme.bodySmall,
                                ),
                              ),
                              Text(
                                '${location.bagCount ?? 0} 袋 · '
                                '${UnifiedItem.formatQuantity(location.quantity ?? 0)}',
                                style: theme.textTheme.labelSmall,
                              ),
                            ],
                          ),
                        ),
                    ],
                  ),
                ),
                const SizedBox(height: 12),
              ],

              // ---- in-stock parts --------------------------------------------
              Row(
                children: <Widget>[
                  Expanded(
                    child: Text('有库存器件', style: theme.textTheme.titleSmall),
                  ),
                  TextButton(
                    onPressed: () => context.go(UnifiedRoutes.catalog),
                    child: const Text('打开器件库'),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              if (data.topItems.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Text(
                    '服务器报告有库存器件 ${data.inStockItemCount} 种，但这一页没有返回卡片。',
                    style: theme.textTheme.bodySmall,
                  ),
                )
              else
                for (final item in data.topItems)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: ItemListTile(
                      item: item,
                      onTap: () => context.push(UnifiedRoutes.itemDetail(item.itemKey)),
                      onReceipt: () => context.push(UnifiedRoutes.receiptFor(item)),
                      onIssue: () => context.push(UnifiedRoutes.issueFor(item)),
                    ),
                  ),
              const SizedBox(height: 8),
              Text(
                '数字来自服务器：器件数按卡片计，在库数量按 stock.quant 合计。',
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          );
        },
      ),
    );
  }
}
