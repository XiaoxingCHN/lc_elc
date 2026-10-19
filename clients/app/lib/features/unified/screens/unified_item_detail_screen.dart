import 'package:lab_inventory_client/widgets/lab_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../models/detail_models.dart';
import '../models/identity.dart';
import '../models/unified_item.dart';
import '../providers/catalog_providers.dart';
import '../providers/cache_writer_providers.dart';
import '../providers/material_providers.dart';
import '../services/asset_cache.dart';
import '../unified_routes.dart';
import '../widgets/media_view.dart';
import '../widgets/status_views.dart';
import 'offline_views.dart';

/// Detail of ONE card: parameters, manual files, local archives, per-location
/// stock, the physical bags behind it and its own operation history.
///
/// The card identity is `lcsc:C123` or `lab:42`. When several local archives are
/// bound to the same C code they are ALL listed here separately - the merge
/// happens for the CARD only, never for the business records.
class UnifiedItemDetailScreen extends ConsumerStatefulWidget {
  const UnifiedItemDetailScreen({
    super.key,
    required this.itemKey,
    this.offline = false,
  });

  final String itemKey;

  /// Public offline mode: only cached parameters, images and manuals are shown -
  /// never stock, SN, bags or history (the cache does not contain them).
  final bool offline;

  @override
  ConsumerState<UnifiedItemDetailScreen> createState() =>
      _UnifiedItemDetailScreenState();
}

class _UnifiedItemDetailScreenState
    extends ConsumerState<UnifiedItemDetailScreen> {
  /// Assets are pinned once per screen instance (a "viewed" item stays offline
  /// available), after the first successful detail load.
  bool _assetsPinned = false;

  void _pinAssets(CatalogDetail detail, UnifiedItem? row) {
    if (_assetsPinned) return;
    _assetsPinned = true;

    final assets = <({String url, MediaKind kind})>[
      if (row?.imageUrl != null) (url: row!.imageUrl!, kind: MediaKind.image),
      if (row?.imageAlternateUrl != null)
        (url: row!.imageAlternateUrl!, kind: MediaKind.image),
      for (final file in detail.files) (url: file.url, kind: MediaKind.manual),
    ];
    if (assets.isEmpty) return;
    // Fire and forget through the writer seam: caching must never block the UI, and
    // a widget test can disable it entirely.
    ref.read(catalogCacheWriterProvider).pinItemAssets(assets);
  }

  @override
  Widget build(BuildContext context) {
    final itemKey = widget.itemKey.trim();
    if (itemKey.isEmpty) {
      return Scaffold(
        appBar: LabAppBar(title: const Text('器件详情'), fallbackLocation: UnifiedRoutes.catalog),
        body: const ErrorView(message: '缺少器件标识，无法打开详情。'),
      );
    }

    if (widget.offline) {
      // Same screen, read-only body: the offline mode shows public catalog facts
      // and cached files only.
      return Scaffold(
        appBar: LabAppBar(fallbackLocation: widget.offline ? UnifiedRoutes.offlineCatalog : UnifiedRoutes.catalog,title: const Text('器件详情（离线缓存）')),
        body: OfflineItemDetailView(itemKey: itemKey),
      );
    }

    final async = ref.watch(catalogDetailProvider(itemKey));
    final row = ref.watch(catalogRowProvider(itemKey));

    return Scaffold(
      appBar: LabAppBar(fallbackLocation: widget.offline ? UnifiedRoutes.offlineCatalog : UnifiedRoutes.catalog,
        title: Text(row?.title.isNotEmpty == true ? row!.title : '器件详情'),
        actions: <Widget>[
          IconButton(
            tooltip: '刷新',
            onPressed: () => ref.invalidate(catalogDetailProvider(itemKey)),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: async.when(
        loading: () => const LoadingView(label: '正在读取器件详情…'),
        error: (error, _) => ErrorView(
          message: '$error',
          onRetry: () => ref.invalidate(catalogDetailProvider(itemKey)),
        ),
        data: (result) {
          if (!result.fromCache) _pinAssets(result.detail, row);
          return _DetailBody(
            itemKey: itemKey,
            result: result,
            row: row,
            onRefresh: () => ref.invalidate(catalogDetailProvider(itemKey)),
          );
        },
      ),
    );
  }
}

class _DetailBody extends ConsumerWidget {
  const _DetailBody({
    required this.itemKey,
    required this.result,
    required this.row,
    required this.onRefresh,
  });

  final String itemKey;
  final CachedDetailResult result;
  final UnifiedItem? row;
  final VoidCallback onRefresh;

  CatalogDetail get detail => result.detail;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final item = detail.item ?? row;
    final kind = identityKindOf(itemKey);
    final internalQuantity = item?.labQuantity ?? detail.locationTotal ?? 0;

    return ListView(
      padding: const EdgeInsets.all(12),
      children: <Widget>[
        if (result.fromCache) _OfflineBanner(result: result, onRetry: onRefresh),

        // ----------------------------------------------------------------- header
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                CachedMediaImage(
                  url: item?.imageUrl,
                  alternateUrl: item?.imageAlternateUrl,
                  width: 110,
                  height: 110,
                  decodeWidth: 320,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        item?.title ?? itemKey,
                        style: theme.textTheme.titleMedium,
                      ),
                      if (item?.subtitle.isNotEmpty ?? false)
                        Text(item!.subtitle, style: theme.textTheme.bodySmall),
                      const SizedBox(height: 6),
                      Wrap(
                        spacing: 6,
                        runSpacing: 4,
                        children: <Widget>[
                          if (item?.catalogCode.isNotEmpty ?? false)
                            Chip(
                              label: Text(displayCatalogCode(item!.catalogCode)),
                              visualDensity: VisualDensity.compact,
                            ),
                          if (kind == IdentityKind.lab)
                            const Chip(
                              label: Text('本地物料'),
                              visualDensity: VisualDensity.compact,
                            ),
                          for (final sn in (item?.snCodes ?? const <String>[]).take(3))
                            Chip(
                              label: Text(sn),
                              visualDensity: VisualDensity.compact,
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 8),

        // ------------------------------------------------------------------ stock
        Card(
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Text('库存', style: theme.textTheme.titleSmall),
                const SizedBox(height: 6),
                // Wrap, not Row: three metrics with six-digit quantities and a
                // long Chinese brand must not overflow a 320px phone.
                Wrap(
                  spacing: 20,
                  runSpacing: 8,
                  children: <Widget>[
                    _Metric(
                      label: '实验室内部库存',
                      value: UnifiedItem.formatQuantity(internalQuantity),
                      highlight: internalQuantity > 0,
                    ),
                    if (item != null)
                      _Metric(
                        label: '可用（可领用）',
                        value: UnifiedItem.formatQuantity(item.labAvailableQuantity),
                      ),
                    _Metric(
                      label: '立创商城现货',
                      value: item?.catalogStock == null
                          ? '未采集'
                          : UnifiedItem.formatQuantity(item!.catalogStock!),
                      muted: true,
                      subtitle: '仅供参考',
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 8),

        // ---------------------------------------------------------------- actions
        Wrap(
          spacing: 8,
          runSpacing: 8,
          children: <Widget>[
            FilledButton.icon(
              onPressed: () => context.push(
                UnifiedRoutes.receiptWith(itemKey, item?.title ?? ''),
              ),
              icon: const Icon(Icons.add_box_outlined),
              label: const Text('入库'),
            ),
            FilledButton.tonalIcon(
              onPressed: () => context.push(
                UnifiedRoutes.issueWith(itemKey, item?.title ?? ''),
              ),
              icon: const Icon(Icons.outbox_outlined),
              label: const Text('领料'),
            ),
            OutlinedButton.icon(
              onPressed: () => context.push(UnifiedRoutes.returnGoods),
              icon: const Icon(Icons.assignment_return_outlined),
              label: const Text('归还'),
            ),
            OutlinedButton.icon(
              onPressed: detail.bags.isEmpty
                  ? null
                  : () => context.push(
                        UnifiedRoutes.labelsForBag(detail.bags.first.id!),
                      ),
              icon: const Icon(Icons.qr_code_2),
              label: const Text('打印标签'),
            ),
            OutlinedButton.icon(
              onPressed: () =>
                  context.push(UnifiedRoutes.historyFor(itemKey)),
              icon: const Icon(Icons.history),
              label: const Text('历史追溯'),
            ),
          ],
        ),
        const SizedBox(height: 8),

        // ------------------------------------------------- local archives / SN
        if (item != null && item.hasLocalArchives)
          _Section(
            title: '本地档案与 SN',
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                if (item.labTemplateIds.length > 1)
                  Text(
                    '同一编号下有 ${item.labTemplateIds.length} 个本地档案：'
                    '卡片只有一张，历史档案不合并也不删除。',
                    style: theme.textTheme.labelSmall,
                  ),
                for (final material in detail.materials)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Text(
                      <String>[
                        material.display,
                        if (material.quantity != null)
                          '库存 ${UnifiedItem.formatQuantity(material.quantity!)}',
                      ].join(' · '),
                    ),
                  ),
                if (detail.materials.isEmpty)
                  for (final sn in item.snCodes)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Text('SN：$sn'),
                    ),
                if (detail.materials.isEmpty && item.snCodes.isEmpty)
                  Text(
                    '共 ${item.labTemplateIds.length} 个本地档案；'
                    '扫码入库或在入库确认界面选择后即可看到对应 SN。',
                    style: theme.textTheme.labelSmall,
                  ),
              ],
            ),
          ),

        // ------------------------------------------------------ catalog-only action
        if (item != null && item.isCatalogCard && !item.hasLocalArchives)
          _CatalogOnlyActions(itemKey: itemKey, catalogCode: item.catalogCode),

        // ------------------------------------------------------------- locations
        _Section(
          title: '库位分布',
          child: detail.locations.isEmpty
              ? const Text('服务器没有返回库位分布。')
              : Column(
                  children: <Widget>[
                    for (final location in detail.locations)
                      ListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        leading: const Icon(Icons.location_on_outlined),
                        title: Text(location.display),
                        subtitle: location.path.isEmpty ? null : Text(location.path),
                        trailing: Text(
                          location.quantity == null
                              ? '—'
                              : UnifiedItem.formatQuantity(location.quantity!),
                          style: theme.textTheme.titleSmall,
                        ),
                        onTap: location.hasId
                            ? () {
                                ScaffoldMessenger.of(context).showSnackBar(
                                  SnackBar(content: Text('库位码：${location.code}')),
                                );
                              }
                            : null,
                      ),
                  ],
                ),
        ),

        // ------------------------------------------------------------------ bags
        _Section(
          title: '追溯袋 / 批次',
          trailing: detail.bags.isEmpty
              ? null
              : TextButton.icon(
                  onPressed: () => context.push(
                    UnifiedRoutes.labelsForBag(detail.bags.first.id!),
                  ),
                  icon: const Icon(Icons.qr_code_2, size: 16),
                  label: const Text('打标签'),
                ),
          child: detail.bags.isEmpty
              ? const Text('该器件还没有已入库的实物袋。')
              : Column(
                  children: <Widget>[
                    for (final bag in detail.bags)
                      Card(
                        margin: const EdgeInsets.only(bottom: 6),
                        child: ListTile(
                          dense: true,
                          leading: const Icon(Icons.inventory_2_outlined),
                          title: Text(
                            bag.display,
                            style: const TextStyle(fontFamily: 'monospace'),
                          ),
                          subtitle: Text(
                            <String>[
                              if (bag.sn.isNotEmpty) 'SN ${bag.sn}',
                              if (bag.locationCode.isNotEmpty ||
                                  bag.locationName.isNotEmpty)
                                '库位 ${bag.locationCode.isNotEmpty ? bag.locationCode : bag.locationName}',
                              if (bag.supplier.isNotEmpty) '来料 ${bag.supplier}',
                            ].join(' · '),
                          ),
                          trailing: Text(
                            bag.quantity == null
                                ? '—'
                                : UnifiedItem.formatQuantity(bag.quantity!),
                            style: theme.textTheme.titleSmall,
                          ),
                          onTap: bag.hasId
                              ? () => context.push(
                                    UnifiedRoutes.labelsForBag(bag.id!),
                                  )
                              : null,
                        ),
                      ),
                  ],
                ),
        ),

        // ------------------------------------------------------------ parameters
        _Section(
          title: '参数',
          child: (item?.parameters.isEmpty ?? true)
              ? const Text('已采集资料中没有参数记录。')
              : Column(
                  children: <Widget>[
                    for (final parameter in item!.parameters)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 2),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            SizedBox(
                              width: 120,
                              child: Text(
                                parameter.label,
                                style: theme.textTheme.bodySmall
                                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                              ),
                            ),
                            Expanded(child: Text(parameter.value)),
                          ],
                        ),
                      ),
                  ],
                ),
        ),

        // --------------------------------------------------------------- manuals
        _Section(
          title: '手册 / 数据表',
          child: ManualList(files: detail.files),
        ),

        // --------------------------------------------------------------- history
        _Section(
          title: '最近操作',
          trailing: TextButton(
            onPressed: () => context.push(UnifiedRoutes.historyFor(itemKey)),
            child: const Text('查看全部'),
          ),
          child: detail.history.isEmpty
              ? const Text('没有操作记录。')
              : Column(
                  children: <Widget>[
                    for (final operation in detail.history.take(5))
                      OperationTile(operation: operation),
                  ],
                ),
        ),
      ],
    );
  }
}

/// One operation row, shared by the detail page and the history screen.
///
/// Only business facts are shown (who / what / how much / which bag / where /
/// when). Raw API payloads are deliberately NOT displayed: the product screens
/// stay free of interface-level technical output.
class OperationTile extends StatelessWidget {
  const OperationTile({super.key, required this.operation, this.dense = true});

  final LabOperation operation;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final details = <String>[
      if (operation.actor.isNotEmpty) '操作人 ${operation.actor}',
      if (operation.borrower.isNotEmpty) '领用人 ${operation.borrower}',
      if (operation.project.isNotEmpty) '项目 ${operation.project}',
      if (operation.bagTrace.isNotEmpty) '袋 ${operation.bagTrace}',
      if (operation.locationCode.isNotEmpty) '库位 ${operation.locationCode}',
      if (operation.note.isNotEmpty) operation.note,
    ];

    return Card(
      margin: const EdgeInsets.only(bottom: 6),
      child: ListTile(
        dense: dense,
        leading: Icon(
          operation.isReceipt
              ? Icons.login
              : operation.isReturn
                  ? Icons.assignment_return_outlined
                  : Icons.logout,
          color: operation.isReceipt
              ? theme.colorScheme.primary
              : theme.colorScheme.tertiary,
        ),
        title: Text('${operation.title}  ${operation.signedQuantity}'.trim()),
        subtitle: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            if (details.isNotEmpty)
              Text(details.join(' · '), maxLines: 3, overflow: TextOverflow.ellipsis),
            if (operation.at != null)
              Text(
                _formatTime(operation.at!),
                style: theme.textTheme.labelSmall,
              ),
            if (operation.outstandingQuantity != null)
              Text(
                '尚未归还 ${UnifiedItem.formatQuantity(operation.outstandingQuantity!)}',
                style: theme.textTheme.labelSmall,
              ),
          ],
        ),
      ),
    );
  }

  static String _formatTime(DateTime time) {
    final local = time.toLocal();
    String two(int value) => value.toString().padLeft(2, '0');
    return '${local.year}-${two(local.month)}-${two(local.day)} '
        '${two(local.hour)}:${two(local.minute)}';
  }
}

/// Actions for a captured catalog row that has no local archive yet.
///
/// Root's requirement: a first receipt must never fail with "material does not
/// exist". The receipt flow creates the archive on demand, and these two buttons
/// let the operator do it explicitly up front - BEFORE any stock exists. Both
/// call real contract endpoints; the SN always comes from the server.
class _CatalogOnlyActions extends ConsumerWidget {
  const _CatalogOnlyActions({required this.itemKey, required this.catalogCode});

  final String itemKey;
  final String catalogCode;

  Future<void> _bind(BuildContext context, WidgetRef ref) async {
    final controller = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('绑定已有本地档案'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            const Text('把该立创编号绑定到一个已经存在的本地物料档案（product.template）。'),
            const SizedBox(height: 8),
            TextField(
              controller: controller,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: '本地档案 ID',
                border: OutlineInputBorder(),
              ),
            ),
          ],
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('绑定'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final id = int.tryParse(controller.text.trim());
    if (id == null) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('请输入有效的本地档案 ID（数字）。')),
        );
      }
      return;
    }
    await ref.read(materialActionProvider.notifier).bind(
          productTemplateId: id,
          catalogCode: catalogCode,
        );
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final state = ref.watch(materialActionProvider);
    final theme = Theme.of(context);

    ref.listen<MaterialActionState>(materialActionProvider, (previous, next) {
      final message = next.error ?? next.notice;
      if (message == null || message == previous?.error || message == previous?.notice) {
        return;
      }
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
    });

    return _Section(
      title: '本地建档',
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            '该器件来自已采集的立创资料，实验室还没有对应档案。'
            '首次入库时会自动建档；也可以先手动建档再入库。',
            style: theme.textTheme.labelSmall,
          ),
          const SizedBox(height: 8),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: <Widget>[
              FilledButton.tonalIcon(
                onPressed: state.running
                    ? null
                    : () => ref
                        .read(materialActionProvider.notifier)
                        .createMaterial(itemKey),
                icon: const Icon(Icons.add),
                label: const Text('创建本地物料（生成 SN）'),
              ),
              OutlinedButton.icon(
                onPressed: state.running ? null : () => _bind(context, ref),
                icon: const Icon(Icons.link),
                label: const Text('绑定已有档案'),
              ),
            ],
          ),
          if (state.created?.sn.isNotEmpty ?? false)
            Text('已创建 SN：${state.created!.sn}', style: theme.textTheme.labelSmall),
          if (state.error != null)
            Text(
              state.error!,
              style: theme.textTheme.labelSmall
                  ?.copyWith(color: theme.colorScheme.error),
            ),
        ],
      ),
    );
  }
}

class _OfflineBanner extends StatelessWidget {
  const _OfflineBanner({required this.result, required this.onRetry});

  final CachedDetailResult result;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final savedAt = result.savedAt;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: theme.colorScheme.tertiaryContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        children: <Widget>[
          const Icon(Icons.cloud_off, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              '当前显示本机离线缓存${savedAt == null ? '' : '（${savedAt.toLocal().toString().substring(0, 16)}）'}。'
              '这里的库存数量是缓存值，可能已经过期，不能当作实时数量；'
              '恢复连接后请点“重连”刷新。已缓存的图片和手册可以直接打开。',
              style: theme.textTheme.labelSmall,
            ),
          ),
          TextButton(onPressed: onRetry, child: const Text('重连')),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.child, this.trailing});

  final String title;
  final Widget child;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Expanded(child: Text(title, style: theme.textTheme.titleSmall)),
                if (trailing != null) trailing!,
              ],
            ),
            const SizedBox(height: 6),
            child,
          ],
        ),
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  const _Metric({
    required this.label,
    required this.value,
    this.highlight = false,
    this.muted = false,
    this.subtitle,
  });

  final String label;
  final String value;
  final bool highlight;
  final bool muted;
  final String? subtitle;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = highlight
        ? theme.colorScheme.primary
        : muted
            ? theme.colorScheme.outline
            : theme.colorScheme.onSurface;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(label, style: theme.textTheme.labelSmall),
        Text(
          value,
          style: theme.textTheme.titleMedium
              ?.copyWith(color: color, fontWeight: FontWeight.w700),
        ),
        if (subtitle != null)
          Text(
            subtitle!,
            style: theme.textTheme.labelSmall
                ?.copyWith(color: theme.colorScheme.outline, fontSize: 9),
          ),
      ],
    );
  }
}
