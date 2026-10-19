import 'package:lab_inventory_client/widgets/lab_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/unified_item.dart';
import '../providers/inventory_providers.dart';
import '../widgets/status_views.dart';

/// 归还 (return): choose the ORIGINAL issue record, then one of its lines, and
/// return at most its outstanding quantity.
///
/// Rules implemented here:
///   * the operator cannot type an issue: they pick from `/lab/api/inventory/issues`
///     (outstanding-only by default);
///   * the quantity is capped by the selected line's outstanding balance - the
///     field itself refuses more, and the controller re-checks before sending;
///   * the destination is NOT chosen by the client: the server returns the
///     material to the original bag/location;
///   * the submission carries a UUID `request_key` that survives a failure, so a
///     retry cannot double-return.
class ReturnScreen extends ConsumerStatefulWidget {
  const ReturnScreen({super.key, this.initialIssueId});

  final int? initialIssueId;

  @override
  ConsumerState<ReturnScreen> createState() => _ReturnScreenState();
}

class _ReturnScreenState extends ConsumerState<ReturnScreen> {
  final TextEditingController _quantity = TextEditingController();
  final TextEditingController _note = TextEditingController();
  bool _loaded = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || _loaded) return;
      _loaded = true;
      ref.read(returnControllerProvider.notifier).loadIssues();
    });
  }

  @override
  void dispose() {
    _quantity.dispose();
    _note.dispose();
    super.dispose();
  }

  Future<void> _confirmAndSubmit() async {
    final state = ref.read(returnControllerProvider);
    final line = state.selectedLine;
    final quantity = state.quantity;
    if (line == null || quantity == null || quantity <= 0 || quantity > line.outstanding) {
      await ref.read(returnControllerProvider.notifier).submit();
      return;
    }

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('确认归还'),
        content: Text(
          '器件：${line.itemName.isNotEmpty ? line.itemName : state.selectedIssue?.displayTitle ?? ''}\n'
          '来源袋：${line.bagTrace.isNotEmpty ? line.bagTrace : '袋#${line.bagId}'}\n'
          '归还数量：${_format(quantity)}（尚未归还 ${_format(line.outstanding)}）\n\n'
          '确认后库存将回到原库位/原袋。',
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('确认归还'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await ref.read(returnControllerProvider.notifier).submit();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(returnControllerProvider);
    final theme = Theme.of(context);

    return Scaffold(
      appBar: LabAppBar(fallbackLocation: '/catalog',
        title: const Text('归还'),
        actions: <Widget>[
          IconButton(
            tooltip: '刷新领料记录',
            onPressed: () {
              _quantity.clear();
              ref.read(returnControllerProvider.notifier).loadIssues();
            },
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: <Widget>[
          if (state.succeeded) _ReturnResultCard(state: state),

          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Row(
                    children: <Widget>[
                      Expanded(
                        child: Text('选择原领料记录', style: theme.textTheme.titleSmall),
                      ),
                      Switch(
                        value: state.outstandingOnly,
                        onChanged: state.isBusy
                            ? null
                            : (value) => ref
                                .read(returnControllerProvider.notifier)
                                .loadIssues(outstandingOnly: value),
                      ),
                      Text('只看未归还', style: theme.textTheme.labelSmall),
                    ],
                  ),
                  const SizedBox(height: 6),
                  if (state.loadingIssues)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 8),
                      child: LinearProgressIndicator(),
                    ),
                  if (state.issuesError != null)
                    ErrorView(
                      message: state.issuesError!,
                      compact: true,
                      onRetry: () =>
                          ref.read(returnControllerProvider.notifier).loadIssues(),
                    ),
                  if (!state.loadingIssues &&
                      state.issuesError == null &&
                      state.issues.isEmpty)
                    const EmptyView(
                      title: '没有可归还的领料记录',
                      subtitle: '未归还数量为 0，或该账号没有可见的领料单。',
                      icon: Icons.assignment_turned_in_outlined,
                    ),
                  for (final issue in state.issues)
                    Card(
                      margin: const EdgeInsets.only(bottom: 6),
                      color: state.selectedIssue?.id == issue.id
                          ? theme.colorScheme.primaryContainer
                          : null,
                      child: ExpansionTile(
                        initiallyExpanded: state.selectedIssue?.id == issue.id,
                        onExpansionChanged: (expanded) {
                          if (expanded) {
                            ref
                                .read(returnControllerProvider.notifier)
                                .selectIssue(issue);
                          }
                        },
                        title: Text(issue.displayTitle),
                        subtitle: Text(
                          <String>[
                            if (issue.borrowerName.isNotEmpty) '领用人 ${issue.borrowerName}',
                            if (issue.actorName.isNotEmpty) '操作人 ${issue.actorName}',
                            '未归还 ${UnifiedItem.formatQuantity(issue.outstanding)}',
                          ].join(' · '),
                        ),
                        children: <Widget>[
                          for (final line in issue.lines)
                            ListTile(
                              dense: true,
                              selected: state.selectedLine?.id == line.id,
                              leading: const Icon(Icons.inventory_2_outlined),
                              title: Text(
                                line.bagTrace.isNotEmpty
                                    ? line.bagTrace
                                    : '袋#${line.bagId ?? '-'}',
                                style: const TextStyle(fontFamily: 'monospace'),
                              ),
                              subtitle: Text(
                                <String>[
                                  if (line.itemName.isNotEmpty) line.itemName,
                                  if (line.locationCode.isNotEmpty) '库位 ${line.locationCode}',
                                  '已领 ${UnifiedItem.formatQuantity(line.quantity ?? 0)}',
                                  if (line.returnedQuantity != null)
                                    '已还 ${UnifiedItem.formatQuantity(line.returnedQuantity!)}',
                                ].join(' · '),
                              ),
                              trailing: Text(
                                '未还 ${UnifiedItem.formatQuantity(line.outstanding)}',
                                style: theme.textTheme.labelMedium?.copyWith(
                                  color: line.outstanding > 0
                                      ? theme.colorScheme.primary
                                      : theme.colorScheme.outline,
                                ),
                              ),
                              onTap: line.hasId
                                  ? () {
                                      ref
                                          .read(returnControllerProvider.notifier)
                                          .selectLine(line);
                                      _quantity.text = line.outstanding
                                          .toString()
                                          .replaceAll(RegExp(r'\.0$'), '');
                                    }
                                  : null,
                            ),
                        ],
                      ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),

          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    state.selectedLine == null
                        ? '请选择要归还的领料明细行'
                        : '未归还数量：${UnifiedItem.formatQuantity(state.outstanding)}'
                            '（默认回到原库位/原袋）',
                    style: theme.textTheme.bodySmall,
                  ),
                  const SizedBox(height: 8),
                  TextField(
                    controller: _quantity,
                    enabled: !state.isBusy && state.selectedLine != null,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    inputFormatters: <TextInputFormatter>[
                      FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                    ],
                    onChanged: (value) =>
                        ref.read(returnControllerProvider.notifier).setQuantity(value),
                    decoration: const InputDecoration(
                      labelText: '归还数量',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _note,
                    enabled: !state.isBusy,
                    onChanged: (value) =>
                        ref.read(returnControllerProvider.notifier).setNote(value),
                    decoration: const InputDecoration(
                      labelText: '备注（可选）',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  if (state.quantity != null &&
                      state.selectedLine != null &&
                      state.quantity! > state.outstanding) ...<Widget>[
                    const SizedBox(height: 8),
                    Text(
                      '归还数量不能超过尚未归还数量 '
                      '${UnifiedItem.formatQuantity(state.outstanding)}。',
                      style: theme.textTheme.labelSmall
                          ?.copyWith(color: theme.colorScheme.error),
                    ),
                  ],
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
                : const Icon(Icons.assignment_return_outlined),
            label: const Text('确认归还'),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  static String _format(double value) =>
      value == value.roundToDouble() ? value.toInt().toString() : value.toStringAsFixed(2);
}

class _ReturnResultCard extends ConsumerWidget {
  const _ReturnResultCard({required this.state});

  final ReturnFormState state;

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
            Text('归还已完成', style: theme.textTheme.titleSmall),
            const SizedBox(height: 4),
            Text(state.notice ?? ''),
            const SizedBox(height: 8),
            FilledButton.tonalIcon(
              onPressed: () {
                ref.read(returnControllerProvider.notifier).reset();
                ref.read(returnControllerProvider.notifier).loadIssues();
              },
              icon: const Icon(Icons.refresh),
              label: const Text('继续归还'),
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
