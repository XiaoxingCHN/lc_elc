import 'package:lab_inventory_client/widgets/lab_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/lab_api_exception.dart';
import '../models/identity.dart';
import '../providers/inventory_providers.dart';
import '../providers/unified_providers.dart';
import '../widgets/item_picker.dart';
import '../widgets/status_views.dart';
import 'unified_item_detail_screen.dart' show OperationTile;

/// 历史追溯 (history): the immutable trace feed.
///
/// The operator filters by picking a material or by scanning an SN / bag / C code
/// (which is resolved by the server) - never by typing an internal key. The screen
/// only READS: nothing here can rewrite a trace record.
class HistoryScreen extends ConsumerStatefulWidget {
  const HistoryScreen({super.key, this.initialItemKey, this.initialBagId});

  final String? initialItemKey;
  final int? initialBagId;

  @override
  ConsumerState<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends ConsumerState<HistoryScreen> {
  /// Internal identity the provider pages on (never displayed).
  String _scope = '';

  int? _bagId;

  /// What the operator sees: a C code, an SN or '全部记录'.
  String _filterLabel = '';

  bool _loaded = false;
  bool _scanning = false;

  @override
  void initState() {
    super.initState();
    _scope = widget.initialItemKey ?? '';
    _bagId = widget.initialBagId;
    _filterLabel = _scope.isEmpty ? '' : humanItemLabel(_scope);
    WidgetsBinding.instance.addPostFrameCallback((_) => _load());
  }

  void _load() {
    if (!mounted || _loaded) return;
    _loaded = true;
    ref.read(historyProvider(_scope).notifier).setFilters(
          itemKey: _scope.isEmpty ? null : _scope,
          bagId: _bagId,
        );
  }

  /// Switches the filter to one identity (a new scope has its own paged state).
  void _focusOn({required String scope, required String label, int? bagId}) {
    setState(() {
      _scope = scope;
      _bagId = bagId;
      _filterLabel = label;
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      ref.read(historyProvider(scope).notifier).setFilters(
            itemKey: scope.isEmpty ? null : scope,
            bagId: bagId,
          );
    });
  }

  Future<void> _pickItem() async {
    final item = await ItemPickerDialog.show(context, title: '选择要追溯的器件');
    if (item == null || !mounted) return;
    _focusOn(
      scope: item.itemKey,
      label: item.title,
      bagId: null,
    );
  }

  Future<void> _resolveCode(String raw) async {
    if (_scanning) return;
    setState(() => _scanning = true);
    try {
      final resolved = await ref.read(labApiProvider).resolveCode(raw);
      if (!mounted) return;
      final scope = resolved.itemKey.isNotEmpty ? resolved.itemKey : _scope;
      final label = <String>[
        if (resolved.sn != null && resolved.sn!.isNotEmpty) resolved.sn!,
        if (resolved.bag != null) '袋 ${resolved.bag!.display}',
        if (resolved.sn == null || resolved.sn!.isEmpty)
          humanItemLabel(scope, name: _filterLabel),
      ].where((part) => part.isNotEmpty).join(' · ');
      _focusOn(scope: scope, label: label, bagId: resolved.bag?.id);
    } on LabApiException catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(error.message)));
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('识别失败：$error')));
    } finally {
      if (mounted) setState(() => _scanning = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(historyProvider(_scope));
    final theme = Theme.of(context);

    return Scaffold(
      appBar: LabAppBar(fallbackLocation: '/catalog',
        title: const Text('历史追溯'),
        actions: <Widget>[
          IconButton(
            tooltip: '刷新',
            onPressed: () => ref.read(historyProvider(_scope).notifier).refresh(),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: Column(
        children: <Widget>[
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 6),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: <Widget>[
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  crossAxisAlignment: WrapCrossAlignment.center,
                  children: <Widget>[
                    OutlinedButton.icon(
                      onPressed: _pickItem,
                      icon: const Icon(Icons.inventory_2_outlined, size: 18),
                      label: const Text('选择器件'),
                    ),
                    if (_filterLabel.isNotEmpty || _scope.isNotEmpty)
                      TextButton.icon(
                        onPressed: () => _focusOn(
                          scope: '',
                          label: '',
                          bagId: null,
                        ),
                        icon: const Icon(Icons.clear_all, size: 18),
                        label: const Text('查看全部记录'),
                      ),
                    if (_scanning)
                      const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      ),
                  ],
                ),
                const SizedBox(height: 6),
                // Scan an SN, a bag trace code or a C code: the server says which
                // material (and bag) it is, so the operator never types a key.
                _ScanFilterField(
                  enabled: !_scanning,
                  onSubmit: _resolveCode,
                ),
                const SizedBox(height: 4),
                Text(
                  _filterLabel.isEmpty
                      ? '当前查看：全部记录'
                      : '当前查看：$_filterLabel',
                  style: theme.textTheme.labelSmall,
                ),
                Text(
                  '历史流水不可改写；每条记录显示人、项目、袋、库位与时间。',
                  style: theme.textTheme.labelSmall
                      ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                ),
              ],
            ),
          ),
          const Divider(height: 1),
          Expanded(child: _buildList(state)),
        ],
      ),
    );
  }

  Widget _buildList(HistoryState state) {
    final theme = Theme.of(context);
    if (state.loading && state.operations.isEmpty) {
      return const LoadingView(label: '正在读取历史流水…');
    }
    if (state.error != null && state.operations.isEmpty) {
      return ErrorView(
        message: state.error!,
        code: state.errorCode,
        onRetry: () => ref.read(historyProvider(_scope).notifier).refresh(),
      );
    }
    if (state.isEmpty) {
      return const EmptyView(
        title: '没有操作记录',
        subtitle: '换一个器件或扫一个 SN / 追溯袋码，或先做一笔入库 / 领料。',
        icon: Icons.history_toggle_off,
      );
    }

    return NotificationListener<ScrollNotification>(
      onNotification: (notification) {
        if (notification.metrics.extentAfter < 400) {
          ref.read(historyProvider(_scope).notifier).loadMore();
        }
        return false;
      },
      child: ListView.builder(
        padding: const EdgeInsets.all(8),
        itemCount: state.operations.length + 1,
        itemBuilder: (context, index) {
          if (index >= state.operations.length) {
            if (!state.hasMore) {
              return Padding(
                padding: const EdgeInsets.all(16),
                child: Center(
                  child: Text(
                    '已到最后一条（${state.operations.length} 条）',
                    style: theme.textTheme.labelSmall,
                  ),
                ),
              );
            }
            return Padding(
              padding: const EdgeInsets.all(16),
              child: Center(
                child: state.loadingMore
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : OutlinedButton(
                        onPressed: () =>
                            ref.read(historyProvider(_scope).notifier).loadMore(),
                        child: const Text('加载更多'),
                      ),
              ),
            );
          }

          final operation = state.operations[index];
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Padding(
                padding: const EdgeInsets.only(left: 4, top: 4),
                child: Text(
                  operation.itemName.isNotEmpty
                      ? operation.itemName
                      : humanItemLabel(operation.itemKey),
                  style: theme.textTheme.labelMedium,
                ),
              ),
              OperationTile(operation: operation),
            ],
          );
        },
      ),
    );
  }
}

/// Compact code entry for the history filter (scanner gun / paste / camera).
class _ScanFilterField extends StatefulWidget {
  const _ScanFilterField({required this.onSubmit, required this.enabled});

  final ValueChanged<String> onSubmit;
  final bool enabled;

  @override
  State<_ScanFilterField> createState() => _ScanFilterFieldState();
}

class _ScanFilterFieldState extends State<_ScanFilterField> {
  final TextEditingController _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _submit(String raw) {
    final code = raw.replaceAll(RegExp(r'[\r\n\t]'), '').trim();
    if (code.isEmpty) return;
    _controller.text = code;
    widget.onSubmit(code);
  }

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: _controller,
      enabled: widget.enabled,
      textInputAction: TextInputAction.search,
      onSubmitted: _submit,
      decoration: InputDecoration(
        isDense: true,
        labelText: '扫描 / 输入 SN、追溯袋码或 C 编号',
        hintText: '例如 LAB-000001 / 袋上二维码 / C225521',
        prefixIcon: const Icon(Icons.qr_code_scanner, size: 18),
        suffixIcon: IconButton(
          tooltip: '识别',
          icon: const Icon(Icons.play_arrow),
          onPressed: widget.enabled ? () => _submit(_controller.text) : null,
        ),
        border: const OutlineInputBorder(),
      ),
    );
  }
}
