import 'package:lab_inventory_client/widgets/lab_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/unified/unified_routes.dart';
import '../providers/auth_provider.dart';

/// The signed-in home screen.
///
/// It is a launcher for the business flows only: ONE unified component library
/// plus 入库 / 领料 / 归还 / 标签 / 历史. There is deliberately no second library
/// entry ("internal stock" and "LCSC catalog" are the same list) and no roadmap,
/// version or implementation text on this page.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authProvider);
    final theme = Theme.of(context);

    return Scaffold(
      appBar: LabAppBar(
        title: const Text('实验室库存'),
        actions: <Widget>[
          IconButton(
            tooltip: '退出登录',
            onPressed: () async {
              await ref.read(authProvider.notifier).logout();
              if (context.mounted) context.go('/login');
            },
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: LayoutBuilder(
        builder: (context, constraints) {
          final wide = constraints.maxWidth >= 720;
          return ListView(
            padding: const EdgeInsets.all(16),
            children: <Widget>[
              Text(
                '欢迎，用户 ID: ${authState.uid}',
                style: theme.textTheme.titleMedium,
              ),
              if (authState.baseUrl != null || authState.database != null)
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text(
                    <String>[
                      if (authState.database != null) '数据库 ${authState.database}',
                      if (authState.baseUrl != null) authState.baseUrl!,
                    ].join(' · '),
                    style: theme.textTheme.labelSmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                ),
              const SizedBox(height: 16),

              // ---------------------------------------------- unified library
              Card(
                color: theme.colorScheme.primaryContainer,
                child: InkWell(
                  borderRadius: BorderRadius.circular(12),
                  onTap: () => context.push(UnifiedRoutes.catalog),
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Row(
                      children: <Widget>[
                        Icon(
                          Icons.inventory_2,
                          size: wide ? 44 : 36,
                          color: theme.colorScheme.onPrimaryContainer,
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: <Widget>[
                              Text(
                                '统一器件库',
                                style: theme.textTheme.titleMedium?.copyWith(
                                  fontWeight: FontWeight.w700,
                                  color: theme.colorScheme.onPrimaryContainer,
                                ),
                              ),
                              const SizedBox(height: 2),
                              Text(
                                '本地物料与已采集立创资料合并检索；'
                                '内部有库存的排在最前',
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: theme.colorScheme.onPrimaryContainer,
                                ),
                              ),
                            ],
                          ),
                        ),
                        Icon(
                          Icons.chevron_right,
                          color: theme.colorScheme.onPrimaryContainer,
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 12),

              // ------------------------------------------------------ operations
              GridView.count(
                crossAxisCount: wide ? 4 : 2,
                shrinkWrap: true,
                physics: const NeverScrollableScrollPhysics(),
                childAspectRatio: wide ? 1.5 : 1.4,
                mainAxisSpacing: 12,
                crossAxisSpacing: 12,
                children: <Widget>[
                  _ActionCard(
                    title: '采购入库',
                    subtitle: '制袋贴标 · 扫码上架',
                    icon: Icons.qr_code_scanner,
                    onTap: () => context.push(UnifiedRoutes.pendingReceipt),
                  ),
                  _ActionCard(
                    title: '领料',
                    subtitle: '选袋与领用人',
                    icon: Icons.outbox_outlined,
                    onTap: () => context.push(UnifiedRoutes.issue),
                  ),
                  _ActionCard(
                    title: '归还',
                    subtitle: '按原领料记录',
                    icon: Icons.assignment_return_outlined,
                    onTap: () => context.push(UnifiedRoutes.returnGoods),
                  ),
                  _ActionCard(
                    title: '标签打印',
                    subtitle: '毫米尺寸 / A4 PDF',
                    icon: Icons.print_outlined,
                    onTap: () => context.push(UnifiedRoutes.labels),
                  ),
                  _ActionCard(
                    title: '历史追溯',
                    subtitle: '人 / 项目 / 袋 / 库位',
                    icon: Icons.history,
                    onTap: () => context.push(UnifiedRoutes.history),
                  ),
                ],
              ),
            ],
          );
        },
      ),
    );
  }
}

class _ActionCard extends StatelessWidget {
  const _ActionCard({
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.onTap,
  });

  final String title;
  final String subtitle;
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      child: InkWell(
        borderRadius: BorderRadius.circular(12),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Icon(icon, size: 28, color: theme.colorScheme.primary),
              const SizedBox(height: 6),
              Text(title, style: theme.textTheme.titleSmall),
              Text(
                subtitle,
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
