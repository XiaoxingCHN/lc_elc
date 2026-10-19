import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/lab_api_exception.dart';
import '../models/catalog_query.dart';
import '../models/identity.dart';
import '../models/unified_item.dart';
import '../providers/unified_providers.dart';
import 'media_view.dart';
import 'status_views.dart';

/// Server-searched component picker.
///
/// Used by the receipt / issue / label flows to pick the material they operate
/// on. It queries `/lab/api/catalog/search` with its OWN paging state, so it
/// never disturbs the main library list, and it keeps the same rule as the main
/// list: search and paging happen on the server.
class ItemPickerDialog extends ConsumerStatefulWidget {
  const ItemPickerDialog({
    super.key,
    this.title = '选择器件',
    this.initialQuery = '',
    this.onCreate,
  });

  final String title;
  final String initialQuery;
  final VoidCallback? onCreate;

  /// Opens the picker and returns the chosen row, or `null`.
  static Future<UnifiedItem?> show(
    BuildContext context, {
    String title = '选择器件',
    String initialQuery = '',
    Future<void> Function()? onCreate,
  }) async {
    FocusManager.instance.primaryFocus?.unfocus();
    var createRequested = false;
    final item = await showDialog<UnifiedItem>(
      context: context,
      builder: (context) => ItemPickerDialog(
        title: title,
        initialQuery: initialQuery,
        onCreate: onCreate == null
            ? null
            : () {
                createRequested = true;
                Navigator.of(context).pop();
              },
      ),
    );
    if (createRequested && context.mounted) await onCreate!();
    return item;
  }

  @override
  ConsumerState<ItemPickerDialog> createState() => _ItemPickerDialogState();
}

class _ItemPickerDialogState extends ConsumerState<ItemPickerDialog> {
  late final TextEditingController _search = TextEditingController(
    text: widget.initialQuery,
  );
  Timer? _debounce;

  CatalogQuery _query = const CatalogQuery();
  final List<UnifiedItem> _items = <UnifiedItem>[];
  String? _cursor;
  int _total = 0;
  bool _loading = false;
  bool _loadingMore = false;
  String? _error;
  int _token = 0;

  @override
  void initState() {
    super.initState();
    if (widget.initialQuery.trim().isNotEmpty) {
      _query = CatalogQuery(text: widget.initialQuery.trim());
    }
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadFirstPage());
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _onSearchChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 400), () {
      if (!mounted) return;
      _query = _query.copyWith(text: value);
      _loadFirstPage();
    });
  }

  Future<void> _loadFirstPage() async {
    if (!mounted) return;
    final token = ++_token;
    setState(() {
      _loading = true;
      _error = null;
      _items.clear();
      _cursor = null;
    });
    try {
      final page = await ref
          .read(labApiProvider)
          .search(_query, limit: LabApiClientPageSize.picker);
      if (!mounted || token != _token) return;
      setState(() {
        _items.addAll(page.items);
        _cursor = page.nextCursor;
        _total = page.total;
        _loading = false;
      });
    } on LabApiException catch (error) {
      if (!mounted || token != _token) return;
      setState(() {
        _loading = false;
        _error = error.message;
      });
    } catch (error) {
      if (!mounted || token != _token) return;
      setState(() {
        _loading = false;
        _error = '$error';
      });
    }
  }

  Future<void> _loadMore() async {
    if (_loading || _loadingMore || _cursor == null) return;
    final token = _token;
    setState(() => _loadingMore = true);
    try {
      final page = await ref
          .read(labApiProvider)
          .search(_query, cursor: _cursor, limit: LabApiClientPageSize.picker);
      if (!mounted || token != _token) return;
      setState(() {
        _items.addAll(page.items);
        _cursor = page.nextCursor;
        _loadingMore = false;
      });
    } catch (error) {
      if (!mounted || token != _token) return;
      setState(() {
        _loadingMore = false;
        _error = '$error';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      insetPadding: const EdgeInsets.all(16),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560, maxHeight: 680),
        child: Column(
          children: <Widget>[
            // AppBar's preferred height is only applied by Scaffold. In a
            // Column its flexibleSpace receives unbounded height and breaks
            // layout. A content-sized header also survives large system text.
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 4, 0),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      widget.title,
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ),
                  IconButton(
                    tooltip: '关闭',
                    icon: const Icon(Icons.close),
                    onPressed: () => Navigator.of(context).pop(),
                  ),
                ],
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
              child: TextField(
                controller: _search,
                autofocus: false,
                textInputAction: TextInputAction.search,
                onChanged: _onSearchChanged,
                onSubmitted: (value) {
                  _debounce?.cancel();
                  _query = _query.copyWith(text: value);
                  _loadFirstPage();
                },
                decoration: const InputDecoration(
                  isDense: true,
                  hintText: 'C 编号 / 型号 / 名称',
                  prefixIcon: Icon(Icons.search),
                  border: OutlineInputBorder(),
                ),
              ),
            ),
            if (widget.onCreate != null)
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: TextButton.icon(
                    onPressed: widget.onCreate,
                    icon: const Icon(Icons.add),
                    label: const Text('自定义 / 新建器件'),
                  ),
                ),
              ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              child: Row(
                children: <Widget>[
                  Expanded(
                    child: Text(
                      _loading
                          ? '正在读取立创资料与自定义器件…'
                          : '匹配 $_total 条，已显示 ${_items.length} 条',
                      style: Theme.of(context).textTheme.labelSmall,
                    ),
                  ),
                  if (_error != null)
                    Text(
                      '加载失败',
                      style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                ],
              ),
            ),
            const Divider(height: 8),
            Expanded(child: _buildList()),
            if (_error != null)
              Padding(
                padding: const EdgeInsets.all(8),
                child: Text(
                  _error!,
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildList() {
    if (_loading && _items.isEmpty) return const LoadingView();
    if (_error != null && _items.isEmpty) {
      return SingleChildScrollView(
        child: ErrorView(
          message: _error!,
          onRetry: _loadFirstPage,
          compact: true,
        ),
      );
    }
    if (_items.isEmpty) {
      return const EmptyView(title: '没有匹配的器件', subtitle: '换个关键词或 C 编号再试');
    }

    return NotificationListener<ScrollNotification>(
      onNotification: (notification) {
        if (notification.metrics.extentAfter < 400) _loadMore();
        return false;
      },
      child: ListView.builder(
        itemCount: _items.length + (_cursor != null ? 1 : 0),
        itemBuilder: (context, index) {
          if (index >= _items.length) {
            return Padding(
              padding: const EdgeInsets.all(12),
              child: Center(
                child: _loadingMore
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : TextButton(
                        onPressed: _loadMore,
                        child: const Text('加载更多'),
                      ),
              ),
            );
          }
          final item = _items[index];
          return ListTile(
            leading: CachedMediaImage(
              url: item.imageUrl,
              width: 44,
              height: 44,
              compactPlaceholder: true,
            ),
            title: Text(
              item.title,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
            ),
            subtitle: Text(
              <String>[
                if (item.catalogCode.isNotEmpty)
                  displayCatalogCode(item.catalogCode),
                if (item.subtitle.isNotEmpty) item.subtitle,
                item.hasStock ? '内部库存 ${item.labQuantityLabel}' : '内部无库存',
              ].join(' · '),
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),
            onTap: () => Navigator.of(context).pop(item),
          );
        },
      ),
    );
  }
}

/// Page size used by pickers (smaller than the main list: a dialog is short).
class LabApiClientPageSize {
  const LabApiClientPageSize._();

  static const int picker = 20;
}
