import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/catalog_query.dart';
import '../models/unified_item.dart';
import '../providers/catalog_providers.dart';

/// Multi-condition filter panel: search + stock + category + brand + package +
/// parameter combinations.
///
/// Every interaction sends a NEW query to the server through
/// [CatalogNotifier.updateQuery]; the client never filters an already-loaded
/// page. The text field is debounced so typing does not fire one request per
/// keystroke.
class FilterPanel extends ConsumerStatefulWidget {
  const FilterPanel({
    super.key,
    this.showCategories = false,
    this.autoFocusSearch = false,
  });

  /// The category tree has its own sidebar on wide screens; the drawer version
  /// shows it inline.
  final bool showCategories;

  final bool autoFocusSearch;

  @override
  ConsumerState<FilterPanel> createState() => _FilterPanelState();
}

class _FilterPanelState extends ConsumerState<FilterPanel> {
  late final TextEditingController _search;
  Timer? _debounce;

  /// Parameter families are long; the first few are shown and the rest stay
  /// reachable through "展开更多参数" instead of being dropped.
  bool _showAllParameters = false;

  static const int _visibleParameterCount = 5;

  @override
  void initState() {
    super.initState();
    _search = TextEditingController(text: ref.read(catalogQueryProvider).text);
    // Clearing the filters (or a deep link changing the query) must clear the
    // visible text as well; typing is never interrupted because the listener
    // only reacts to an EXTERNALLY emptied/shortened query.
    ref.listenManual<CatalogQuery>(catalogQueryProvider, (previous, next) {
      if (next.text == _search.text) return;
      if (next.text.isEmpty) {
        _debounce?.cancel();
        _search.text = '';
      }
    });
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _apply(CatalogQuery query) {
    ref.read(catalogProvider.notifier).updateQuery(query);
  }

  void _onSearchChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 450), () {
      if (!mounted) return;
      _apply(ref.read(catalogQueryProvider).copyWith(text: value));
    });
  }

  void _submitSearchNow(String value) {
    _debounce?.cancel();
    _apply(ref.read(catalogQueryProvider).copyWith(text: value));
  }

  @override
  Widget build(BuildContext context) {
    final query = ref.watch(catalogQueryProvider);
    final facetsAsync = ref.watch(catalogFacetsProvider);
    final categoriesAsync = ref.watch(catalogCategoriesProvider);
    final theme = Theme.of(context);

    return ListView(
      padding: const EdgeInsets.all(12),
      children: <Widget>[
        TextField(
          controller: _search,
          autofocus: widget.autoFocusSearch,
          textInputAction: TextInputAction.search,
          onChanged: _onSearchChanged,
          onSubmitted: _submitSearchNow,
          decoration: InputDecoration(
            isDense: true,
            labelText: '搜索器件',
            hintText: 'C 编号 / 型号 / 名称 / 品牌',
            prefixIcon: const Icon(Icons.search),
            suffixIcon: _search.text.isEmpty
                ? null
                : IconButton(
                    tooltip: '清空搜索',
                    icon: const Icon(Icons.clear),
                    onPressed: () {
                      _search.clear();
                      _submitSearchNow('');
                    },
                  ),
            border: const OutlineInputBorder(),
          ),
        ),
        const SizedBox(height: 8),
        SwitchListTile(
          dense: true,
          contentPadding: EdgeInsets.zero,
          title: const Text('只看内部有库存'),
          subtitle: const Text('按实验室实际库存过滤（不含商城现货）',
              style: TextStyle(fontSize: 11)),
          value: query.stockOnly,
          onChanged: (value) => _apply(query.copyWith(stockOnly: value)),
        ),
        const Divider(height: 8),

        // ---------------------------------------------------------------- category
        if (widget.showCategories)
          categoriesAsync.when(
            loading: () => const Padding(
              padding: EdgeInsets.symmetric(vertical: 12),
              child: LinearProgressIndicator(),
            ),
            error: (error, _) => _InlineError(
              message: '分类加载失败：$error',
              onRetry: () => ref.invalidate(catalogCategoriesProvider),
            ),
            data: (categories) {
              final options = _flatten(categories);
              if (options.isEmpty) return const SizedBox.shrink();
              return Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: DropdownButtonFormField<int?>(
                  isExpanded: true,
                  decoration: const InputDecoration(
                    isDense: true,
                    labelText: '分类',
                    border: OutlineInputBorder(),
                  ),
                  value: query.categoryId,
                  items: <DropdownMenuItem<int?>>[
                    const DropdownMenuItem<int?>(value: null, child: Text('全部分类')),
                    for (final option in options)
                      DropdownMenuItem<int?>(
                        value: option.category.id,
                        child: Text(
                          '${'　' * (option.depth.clamp(0, 3))}${option.category.display}',
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                  ],
                  onChanged: (value) => _apply(query.copyWith(categoryId: value)),
                ),
              );
            },
          ),

        // ------------------------------------------------------------ facet groups
        facetsAsync.when(
          loading: () => const Padding(
            padding: EdgeInsets.symmetric(vertical: 12),
            child: LinearProgressIndicator(),
          ),
          error: (error, _) => _InlineError(
            message: '筛选条件加载失败：$error',
            onRetry: () => ref.invalidate(catalogFacetsProvider),
          ),
          data: (facets) {
            if (facets.isEmpty) {
              return Text(
                '当前条件下没有可用的品牌/封装/参数筛选项。',
                style: theme.textTheme.bodySmall,
              );
            }
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                if (facets.brands.isNotEmpty)
                  _FacetGroup(
                    title: '品牌',
                    options: facets.brands,
                    selected: query.brands,
                    onChanged: (values) =>
                        _apply(query.copyWith(brands: values.toSet())),
                  ),
                if (facets.packages.isNotEmpty)
                  _FacetGroup(
                    title: '封装',
                    options: facets.packages,
                    selected: query.packages,
                    onChanged: (values) =>
                        _apply(query.copyWith(packages: values.toSet())),
                  ),
                for (final parameter in (_showAllParameters
                    ? facets.parameters
                    : facets.parameters.take(_visibleParameterCount)))
                  _FacetGroup(
                    title: parameter.label,
                    options: parameter.values,
                    selected: query.parameters[parameter.code] ?? const <String>{},
                    onChanged: (values) {
                      final parameters =
                          Map<String, Set<String>>.of(query.parameters);
                      if (values.isEmpty) {
                        parameters.remove(parameter.code);
                      } else {
                        parameters[parameter.code] = values.toSet();
                      }
                      _apply(query.copyWith(parameters: parameters));
                    },
                  ),
                if (facets.parameters.length > _visibleParameterCount)
                  Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton.icon(
                      onPressed: () => setState(
                        () => _showAllParameters = !_showAllParameters,
                      ),
                      icon: Icon(
                        _showAllParameters ? Icons.expand_less : Icons.expand_more,
                        size: 18,
                      ),
                      label: Text(
                        _showAllParameters
                            ? '收起参数'
                            : '展开更多参数（还有 '
                                '${facets.parameters.length - _visibleParameterCount} 项）',
                      ),
                    ),
                  ),
              ],
            );
          },
        ),

        const Divider(height: 16),
        Row(
          children: <Widget>[
            Expanded(
              child: Text(
                query.isFiltered ? '已启用 ${query.activeFilterCount} 个条件' : '未设置筛选条件',
                style: theme.textTheme.bodySmall,
              ),
            ),
            TextButton.icon(
              onPressed: query.isFiltered
                  ? () {
                      _search.clear();
                      _apply(const CatalogQuery());
                    }
                  : null,
              icon: const Icon(Icons.filter_alt_off_outlined, size: 18),
              label: const Text('清空筛选'),
            ),
          ],
        ),
      ],
    );
  }

  static List<({CatalogCategory category, int depth})> _flatten(
    List<CatalogCategory> nodes, [
    int depth = 0,
  ]) {
    final result = <({CatalogCategory category, int depth})>[];
    for (final node in nodes) {
      result.add((category: node, depth: depth));
      if (node.children.isNotEmpty) {
        result.addAll(_flatten(node.children, depth + 1));
      }
    }
    return result;
  }
}

/// One collapsible chip group.
class _FacetGroup extends StatefulWidget {
  const _FacetGroup({
    required this.title,
    required this.options,
    required this.selected,
    required this.onChanged,
  });

  final String title;
  final List<FacetOption> options;
  final Set<String> selected;
  final ValueChanged<Set<String>> onChanged;

  @override
  State<_FacetGroup> createState() => _FacetGroupState();
}

class _FacetGroupState extends State<_FacetGroup> {
  static const int _collapsedCount = 8;
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final values = _expanded
        ? widget.options
        : widget.options.take(_collapsedCount).toList();

    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      childrenPadding: const EdgeInsets.only(bottom: 8),
      initiallyExpanded: widget.selected.isNotEmpty,
      title: Text(widget.title, style: Theme.of(context).textTheme.bodyMedium),
      subtitle: widget.selected.isEmpty
          ? null
          : Text(
              widget.selected.join('、'),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelSmall,
            ),
      children: <Widget>[
        Align(
          alignment: Alignment.centerLeft,
          child: Wrap(
            spacing: 6,
            runSpacing: 6,
            children: <Widget>[
              for (final option in values)
                FilterChip(
                  label: Text(option.display, style: const TextStyle(fontSize: 11)),
                  selected: widget.selected.contains(option.value),
                  onSelected: (selected) {
                    final next = Set<String>.of(widget.selected);
                    if (selected) {
                      next.add(option.value);
                    } else {
                      next.remove(option.value);
                    }
                    widget.onChanged(next);
                  },
                ),
              if (!_expanded && widget.options.length > _collapsedCount)
                ActionChip(
                  label: const Text('更多…', style: TextStyle(fontSize: 11)),
                  onPressed: () => setState(() => _expanded = true),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

class _InlineError extends StatelessWidget {
  const _InlineError({required this.message, this.onRetry});

  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: <Widget>[
          Icon(Icons.error_outline, size: 16, color: theme.colorScheme.error),
          const SizedBox(width: 6),
          Expanded(
            child: Text(message, style: theme.textTheme.bodySmall),
          ),
          if (onRetry != null)
            TextButton(onPressed: onRetry, child: const Text('重试')),
        ],
      ),
    );
  }
}

/// Phone layout: the same panel inside a drawer.
class FilterDrawer extends StatelessWidget {
  const FilterDrawer({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Drawer(
      width: MediaQuery.of(context).size.width * 0.86,
      child: SafeArea(
        child: Column(
          children: <Widget>[
            ListTile(
              title: const Text('筛选条件'),
              trailing: IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.of(context).pop(),
              ),
            ),
            const Divider(height: 1),
            Expanded(child: child),
          ],
        ),
      ),
    );
  }
}
