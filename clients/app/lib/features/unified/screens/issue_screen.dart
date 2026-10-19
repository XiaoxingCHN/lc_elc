import 'package:lab_inventory_client/widgets/lab_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../models/detail_models.dart';
import '../models/identity.dart';
import '../models/inventory.dart';
import '../providers/catalog_providers.dart';
import '../providers/inventory_providers.dart';
import '../providers/unified_providers.dart';
import '../unified_routes.dart';
import '../widgets/item_picker.dart';
import '../widgets/status_views.dart';

/// 领料 (issue): pick the source bags and quantities, the 领用人 and the project.
///
/// The borrower rule (user's final decision) is enforced here:
///   * the borrower MUST be an existing system account from
///     `bootstrap.borrowers` - free text is impossible;
///   * an ordinary operator may only issue to their OWN account (self-service);
///   * an inventory manager sees the server-authorised list and may issue for
///     somebody else - the ACTOR is still recorded by the server from the
///     authenticated session, so a manager can never be logged as the borrower.
class IssueScreen extends ConsumerStatefulWidget {
  const IssueScreen({super.key, this.initialItemKey, this.initialItemName});

  final String? initialItemKey;
  final String? initialItemName;

  @override
  ConsumerState<IssueScreen> createState() => _IssueScreenState();
}

class _IssueScreenState extends ConsumerState<IssueScreen> {
  final TextEditingController _project = TextEditingController();
  final TextEditingController _note = TextEditingController();
  final Map<int, TextEditingController> _quantities = <int, TextEditingController>{};
  bool _prefilled = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || _prefilled) return;
      _prefilled = true;
      final itemKey = widget.initialItemKey?.trim();
      if (itemKey != null && itemKey.isNotEmpty) {
        ref.read(issueControllerProvider.notifier).setItem(
              itemKey: itemKey,
              itemName: widget.initialItemName ?? '',
            );
      }
    });
  }

  @override
  void dispose() {
    _project.dispose();
    _note.dispose();
    for (final controller in _quantities.values) {
      controller.dispose();
    }
    super.dispose();
  }

  TextEditingController _controllerFor(int bagId) {
    return _quantities.putIfAbsent(bagId, () => TextEditingController());
  }

  Future<void> _pickItem() async {
    final item = await ItemPickerDialog.show(context, title: '选择要领用的器件');
    if (item == null || !mounted) return;
    ref.read(issueControllerProvider.notifier).setItem(
          itemKey: item.itemKey,
          itemName: item.title,
        );
  }

  Future<void> _confirmAndSubmit() async {
    final state = ref.read(issueControllerProvider);
    final problems = state.problems;
    if (problems.isNotEmpty) {
      await ref.read(issueControllerProvider.notifier).submit();
      return;
    }

    final borrower = ref.read(inventoryBootstrapProvider).valueOrNull;
    final borrowerLabel = _borrowerLabel(borrower, state.borrowerId);
    final lines = state.lines
        .where((line) => line.hasQuantity)
        .map((line) => '  · ${line.label} × ${line.quantityText}')
        .join('\n');

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('确认领料'),
        content: Text(
          '器件：${state.itemName.isNotEmpty ? state.itemName : state.itemKey}\n'
          '领用人：$borrowerLabel\n'
          '项目：${state.project}\n'
          '来源袋：\n$lines\n\n'
          '确认后库存将减少，操作人按当前登录账号记录。',
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('确认领料'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await ref.read(issueControllerProvider.notifier).submit();
  }

  String _borrowerLabel(InventoryBootstrap? bootstrap, int? borrowerId) {
    if (borrowerId == null) return '未选择';
    for (final borrower in bootstrap?.borrowers ?? const <Borrower>[]) {
      if (borrower.id == borrowerId) return borrower.display;
    }
    return '#$borrowerId';
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(issueControllerProvider);
    final theme = Theme.of(context);
    final itemKey = state.itemKey;
    final detailAsync =
        itemKey.isEmpty ? null : ref.watch(catalogDetailProvider(itemKey));

    return Scaffold(
      appBar: LabAppBar(fallbackLocation: '/catalog',
        title: const Text('领料'),
        actions: <Widget>[
          IconButton(
            tooltip: '重新开始',
            onPressed: () {
              _project.clear();
              _note.clear();
              for (final controller in _quantities.values) {
                controller.clear();
              }
              ref.read(issueControllerProvider.notifier).reset();
            },
            icon: const Icon(Icons.restart_alt),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: <Widget>[
          if (state.succeeded) _IssueResultCard(state: state),

          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Row(
                    children: <Widget>[
                      Expanded(
                        child: Text(
                          itemKey.isEmpty
                              ? '请选择要领用的器件'
                              : '器件：${state.itemName.isNotEmpty ? state.itemName : humanItemLabel(itemKey)}',
                          style: theme.textTheme.bodyMedium,
                        ),
                      ),
                      TextButton.icon(
                        onPressed: state.isBusy ? null : _pickItem,
                        icon: const Icon(Icons.search, size: 18),
                        label: const Text('选择器件'),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),

          // ----------------------------------------------------------- source bags
          if (detailAsync != null)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text('来源袋（追溯码）', style: theme.textTheme.titleSmall),
                    const SizedBox(height: 6),
                    detailAsync.when(
                      loading: () => const Padding(
                        padding: EdgeInsets.symmetric(vertical: 8),
                        child: LinearProgressIndicator(),
                      ),
                      error: (error, _) => ErrorView(
                        message: '读取袋明细失败：$error',
                        onRetry: () => ref.invalidate(catalogDetailProvider(itemKey)),
                        compact: true,
                      ),
                      data: (result) => _BagSelector(
                        detail: result.detail,
                        lines: state.lines,
                        controllerFor: _controllerFor,
                        onAdd: (bag) => ref
                            .read(issueControllerProvider.notifier)
                            .addBag(bag),
                        onRemove: (bagId) => ref
                            .read(issueControllerProvider.notifier)
                            .removeBag(bagId),
                        onQuantity: (bagId, value) => ref
                            .read(issueControllerProvider.notifier)
                            .updateQuantity(bagId, value),
                      ),
                    ),
                  ],
                ),
              ),
            ),

          // ------------------------------------------------------------- borrower
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: ref.watch(inventoryBootstrapProvider).when(
                    loading: () => const Padding(
                      padding: EdgeInsets.symmetric(vertical: 8),
                      child: LinearProgressIndicator(),
                    ),
                    error: (error, _) => ErrorView(
                      message: '领用人列表加载失败：$error',
                      onRetry: () => ref.invalidate(inventoryBootstrapProvider),
                      compact: true,
                    ),
                    data: (bootstrap) => _BorrowerSelector(
                      bootstrap: bootstrap,
                      currentUid: ref.watch(currentUidProvider),
                      selected: state.borrowerId,
                      onSelected: (id) =>
                          ref.read(issueControllerProvider.notifier).setBorrower(id),
                    ),
                  ),
            ),
          ),
          const SizedBox(height: 8),

          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                children: <Widget>[
                  TextField(
                    controller: _project,
                    enabled: !state.isBusy,
                    onChanged: (value) =>
                        ref.read(issueControllerProvider.notifier).setProject(value),
                    decoration: const InputDecoration(
                      labelText: '项目 *',
                      hintText: '例如 项目A / 课题编号',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _note,
                    enabled: !state.isBusy,
                    onChanged: (value) =>
                        ref.read(issueControllerProvider.notifier).setNote(value),
                    decoration: const InputDecoration(
                      labelText: '备注（可选）',
                      border: OutlineInputBorder(),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),

          if (state.error != null) _Banner(message: state.error!, error: true),
          if (state.notice != null && !state.succeeded) _Banner(message: state.notice!),

          FilledButton.icon(
            onPressed: state.isBusy ? null : _confirmAndSubmit,
            icon: state.submitting
                ? const SizedBox(
                    width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.outbox_outlined),
            label: Text('确认领料（共 ${_format(state.totalQuantity)} 件）'),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  static String _format(double value) =>
      value == value.roundToDouble() ? value.toInt().toString() : value.toStringAsFixed(2);
}

class _BagSelector extends StatelessWidget {
  const _BagSelector({
    required this.detail,
    required this.lines,
    required this.controllerFor,
    required this.onAdd,
    required this.onRemove,
    required this.onQuantity,
  });

  final CatalogDetail detail;
  final List<IssueBagLine> lines;
  final TextEditingController Function(int bagId) controllerFor;
  final ValueChanged<LabBag> onAdd;
  final ValueChanged<int> onRemove;
  final void Function(int bagId, String value) onQuantity;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    if (detail.bags.isEmpty) {
      return Text(
        '该器件当前没有可领用的实物袋（内部库存为 0 或尚未入库）。',
        style: theme.textTheme.bodySmall,
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        for (final bag in detail.bags)
          Builder(
            builder: (context) {
              final selected = lines.any((line) => line.bagId == bag.id);
              final matches =
                  lines.where((candidate) => candidate.bagId == bag.id).toList();
              final line = matches.isEmpty ? null : matches.first;
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  CheckboxListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    value: selected,
                    onChanged: !bag.hasId
                        ? null
                        : (value) {
                            if (value == true) {
                              onAdd(bag);
                            } else {
                              onRemove(bag.id!);
                            }
                          },
                    title: Text(
                      bag.display,
                      style: const TextStyle(fontFamily: 'monospace'),
                    ),
                    subtitle: Text(
                      <String>[
                        if (bag.sn.isNotEmpty) 'SN ${bag.sn}',
                        if (bag.locationCode.isNotEmpty) '库位 ${bag.locationCode}',
                        '可用 ${_format(bag.remaining)}',
                      ].join(' · '),
                    ),
                  ),
                  if (selected && line != null)
                    Padding(
                      padding: const EdgeInsets.only(left: 32, bottom: 8),
                      child: Row(
                        children: <Widget>[
                          SizedBox(
                            width: 140,
                            child: TextField(
                              controller: controllerFor(bag.id!),
                              keyboardType: const TextInputType.numberWithOptions(decimal: true),
                              inputFormatters: <TextInputFormatter>[
                                FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                              ],
                              onChanged: (value) => onQuantity(bag.id!, value),
                              decoration: InputDecoration(
                                isDense: true,
                                labelText: '领用数量',
                                helperText: '上限 ${_format(bag.remaining)}',
                                border: const OutlineInputBorder(),
                              ),
                            ),
                          ),
                          const SizedBox(width: 8),
                          if (line.exceedsAvailable)
                            Expanded(
                              child: Text(
                                '超过袋内可用数量',
                                style: theme.textTheme.labelSmall
                                    ?.copyWith(color: theme.colorScheme.error),
                              ),
                            ),
                        ],
                      ),
                    ),
                ],
              );
            },
          ),
      ],
    );
  }

  static String _format(double value) =>
      value == value.roundToDouble() ? value.toInt().toString() : value.toStringAsFixed(2);
}

/// System-account borrower picker.
class _BorrowerSelector extends StatelessWidget {
  const _BorrowerSelector({
    required this.bootstrap,
    required this.currentUid,
    required this.selected,
    required this.onSelected,
  });

  final InventoryBootstrap bootstrap;
  final int? currentUid;
  final int? selected;
  final ValueChanged<int?> onSelected;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final selectable = bootstrap.selectableBorrowers(currentUid: currentUid);
    final self = bootstrap.selfBorrower(currentUid: currentUid);

    if (selectable.isEmpty) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text('领用人 *', style: theme.textTheme.titleSmall),
          const SizedBox(height: 6),
          Text(
            bootstrap.borrowers.isEmpty
                ? '服务器没有返回可用的领用人账号。领用人必须是已建立的系统账号，'
                    '请联系管理员为操作员建立账号后再领料。'
                : '当前账号不在可代领名单中，且服务器未返回本人的领用账号，无法自助领料。'
                    '请联系库存管理员。',
            style: theme.textTheme.bodySmall?.copyWith(color: theme.colorScheme.error),
          ),
        ],
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text('领用人（系统账号）*', style: theme.textTheme.titleSmall),
        const SizedBox(height: 4),
        Text(
          bootstrap.canIssueForOthers
              ? '当前账号可代他人领料；实际操作人仍按登录账号记录。'
              : '当前账号只能为本人领料（自助领料仅限本人）。',
          style: theme.textTheme.labelSmall,
        ),
        const SizedBox(height: 6),
        DropdownButtonFormField<int?>(
          isExpanded: true,
          value: selectable.any((borrower) => borrower.id == selected) ? selected : null,
          decoration: const InputDecoration(
            labelText: '选择领用人',
            border: OutlineInputBorder(),
          ),
          items: <DropdownMenuItem<int?>>[
            const DropdownMenuItem<int?>(value: null, child: Text('请选择领用人')),
            for (final borrower in selectable)
              DropdownMenuItem<int?>(
                value: borrower.id,
                child: Text(
                  borrower.display +
                      (self != null && borrower.id == self.id ? '（本人）' : ''),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
          ],
          onChanged: onSelected,
        ),
      ],
    );
  }
}

class _IssueResultCard extends ConsumerWidget {
  const _IssueResultCard({required this.state});

  final IssueFormState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    return Card(
      color: theme.colorScheme.primaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text('领料已完成', style: theme.textTheme.titleSmall),
            const SizedBox(height: 4),
            Text(state.notice ?? ''),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: <Widget>[
                FilledButton.tonalIcon(
                  onPressed: () =>
                      ref.read(issueControllerProvider.notifier).reset(),
                  icon: const Icon(Icons.add),
                  label: const Text('继续领料'),
                ),
                OutlinedButton.icon(
                  onPressed: () => context.push(UnifiedRoutes.returnGoods),
                  icon: const Icon(Icons.assignment_return_outlined),
                  label: const Text('归还'),
                ),
                OutlinedButton.icon(
                  onPressed: () => context.push(UnifiedRoutes.history),
                  icon: const Icon(Icons.history),
                  label: const Text('历史追溯'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({required this.message, this.error = false});

  final String message;
  final bool error;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      color: error ? theme.colorScheme.errorContainer : theme.colorScheme.tertiaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Text(message, style: theme.textTheme.bodySmall),
      ),
    );
  }
}
