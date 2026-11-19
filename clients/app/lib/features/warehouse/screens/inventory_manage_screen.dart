import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../widgets/lab_ui.dart';
import '../../unified/models/inventory.dart';
import '../../unified/providers/inventory_providers.dart';
import '../../unified/unified_routes.dart';
import '../widgets/stat_tile.dart';

/// 库存管理: the five operations, one screen.
///
/// Before this they were a floating button on the library (入库 only) plus
/// links scattered across detail pages, so "where do I go to hand something
/// out?" had no answer. Each card here opens the SAME route as before - this
/// screen is a launcher, not a new workflow - and each is disabled with a
/// reason when the session's permissions do not cover it.
class InventoryManageScreen extends ConsumerWidget {
  const InventoryManageScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final bootstrap = ref.watch(inventoryBootstrapProvider);
    final permissions = bootstrap.valueOrNull?.permissions ??
        InventoryPermissions.unknown;
    final theme = Theme.of(context);

    // `unknown` means the server did not report permissions. Treating that as
    // "denied" would lock an operator out of flows the server would accept, so
    // an unknown permission stays enabled and the server decides on submit.
    bool allowed(bool? granted) => !permissions.known || granted != false;

    final cards = <Widget>[
      NavCard(
        title: '入库',
        subtitle: '制袋贴标 · 扫码上架 · 直接入库',
        icon: Icons.qr_code_scanner,
        enabled: allowed(permissions.canReceipt),
        disabledReason: '当前账号没有入库权限，请联系库存管理员。',
        onTap: () => context.push(UnifiedRoutes.pendingReceipt),
      ),
      NavCard(
        title: '领料',
        subtitle: '选袋、填写领用人',
        icon: Icons.outbox_outlined,
        enabled: allowed(permissions.canIssue),
        disabledReason: '当前账号没有领料权限，请联系库存管理员。',
        onTap: () => context.push(UnifiedRoutes.issue),
      ),
      NavCard(
        title: '归还',
        subtitle: '按原领料记录归还',
        icon: Icons.assignment_return_outlined,
        enabled: allowed(permissions.canReturn),
        disabledReason: '当前账号没有归还权限，请联系库存管理员。',
        onTap: () => context.push(UnifiedRoutes.returnGoods),
      ),
      NavCard(
        title: '标签打印',
        subtitle: '器件追溯标签 · 仓位标签 · 待入库批量',
        icon: Icons.print_outlined,
        enabled: allowed(permissions.canPrintLabels),
        disabledReason: '当前账号没有打印标签的权限，请联系库存管理员。',
        onTap: () => context.push(UnifiedRoutes.labels),
      ),
      NavCard(
        title: '历史追溯',
        subtitle: '按人 / 项目 / 袋 / 仓位查流水',
        icon: Icons.history,
        enabled: true,
        onTap: () => context.push(UnifiedRoutes.history),
      ),
    ];

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: LabAppBar(
        title: const Text('库存管理'),
        actions: <Widget>[
          IconButton(
            tooltip: '刷新权限',
            onPressed: () => ref.invalidate(inventoryBootstrapProvider),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
        children: <Widget>[
          if (bootstrap.hasError)
            Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: Text(
                '权限读取失败，按钮按“未限制”显示；提交时仍由服务器校验。',
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.error),
              ),
            ),
          for (final card in cards)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: card,
            ),
          const SizedBox(height: 8),
          Text(
            '入库与领料会改变真实库存；取消或失败不会产生任何库存变动。',
            style: theme.textTheme.labelSmall
                ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
          ),
        ],
      ),
    );
  }
}
