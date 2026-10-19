import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/unified_item.dart';
import '../providers/catalog_providers.dart';

/// Desktop / tablet category navigation rail for the ONE unified library.
///
/// It filters the same list - there is no separate "lab library" or "catalog
/// library" entry point anywhere in the app.
class CategorySidebar extends ConsumerWidget {
  const CategorySidebar({
    super.key,
    required this.selectedId,
    required this.onSelected,
    this.width = 250,
  });

  final int? selectedId;
  final ValueChanged<int?> onSelected;
  final double width;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(catalogCategoriesProvider);
    final theme = Theme.of(context);

    return SizedBox(
      width: width,
      child: Material(
        color: theme.colorScheme.surfaceContainerLow,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
              child: Row(
                children: <Widget>[
                  const Icon(Icons.account_tree_outlined, size: 18),
                  const SizedBox(width: 6),
                  Text('分类导航', style: theme.textTheme.titleSmall),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: async.when(
                loading: () => const Center(
                  child: SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ),
                error: (error, _) => Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text('分类加载失败', style: theme.textTheme.bodyMedium),
                      const SizedBox(height: 4),
                      Text('$error', style: theme.textTheme.labelSmall),
                      const SizedBox(height: 8),
                      OutlinedButton(
                        onPressed: () => ref.invalidate(catalogCategoriesProvider),
                        child: const Text('重试'),
                      ),
                    ],
                  ),
                ),
                data: (categories) => ListView(
                  children: <Widget>[
                    ListTile(
                      dense: true,
                      selected: selectedId == null,
                      leading: const Icon(Icons.apps_outlined, size: 18),
                      title: const Text('全部已采集资料'),
                      onTap: () => onSelected(null),
                    ),
                    for (final node in categories) ..._buildNode(node, 0),
                    if (categories.isEmpty)
                      const Padding(
                        padding: EdgeInsets.all(12),
                        child: Text('服务端没有返回分类。', style: TextStyle(fontSize: 12)),
                      ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  List<Widget> _buildNode(CatalogCategory node, int depth) {
    if (node.children.isEmpty) {
      return <Widget>[
        ListTile(
          dense: true,
          contentPadding: EdgeInsets.only(left: 12 + depth * 12.0, right: 8),
          selected: selectedId == node.id,
          title: Text(node.display, style: const TextStyle(fontSize: 13)),
          onTap: () => onSelected(node.id),
        ),
      ];
    }
    return <Widget>[
      ExpansionTile(
        tilePadding: EdgeInsets.only(left: 12 + depth * 12.0, right: 8),
        childrenPadding: EdgeInsets.zero,
        dense: true,
        initiallyExpanded: selectedId != null &&
            _containsSelection(node, selectedId!),
        title: Text(node.display, style: const TextStyle(fontSize: 13)),
        onExpansionChanged: (_) {},
        children: <Widget>[
          ListTile(
            dense: true,
            contentPadding: EdgeInsets.only(left: 24 + depth * 12.0, right: 8),
            selected: selectedId == node.id,
            title: Text('全部 ${node.name}',
                style: const TextStyle(fontSize: 12, fontStyle: FontStyle.italic)),
            onTap: () => onSelected(node.id),
          ),
          for (final child in node.children) ..._buildNode(child, depth + 1),
        ],
      ),
    ];
  }

  static bool _containsSelection(CatalogCategory node, int id) {
    if (node.id == id) return true;
    return node.children.any((child) => _containsSelection(child, id));
  }
}
