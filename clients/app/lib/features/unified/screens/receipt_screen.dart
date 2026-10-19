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
import '../unified_routes.dart';
import '../widgets/item_picker.dart';
import '../widgets/scan_input.dart';
import '../widgets/status_views.dart';

/// 入库 (receipt): scan / type a code, pick the internal location, confirm the
/// quantity, then - and only then - create the physical bag stock.
///
/// Guarantees that matter to the operator and to acceptance:
///   * every code goes through `/lab/api/inventory/resolve_code`, so this
///     system's trace code, a `LABL:` location code, the original LCSC bag
///     payload and a bare `C123456` all work here;
///   * nothing is written until the confirmation dialog is accepted; resolving
///     or cancelling never changes stock;
///   * every submission carries a UUID `request_key` that SURVIVES a failure, so
///     "重试" after a timeout can never create a second bag;
///   * a failure keeps every entered value on screen;
///   * a catalog row without a local archive is created on demand (server-made
///     SN) instead of failing with "material does not exist".
class ReceiptScreen extends ConsumerStatefulWidget {
  const ReceiptScreen({
    super.key,
    this.initialItemKey,
    this.initialItemName,
    this.initialCode,
  });

  final String? initialItemKey;
  final String? initialItemName;

  /// Code to resolve on open (deep link / scanner intent).
  final String? initialCode;

  @override
  ConsumerState<ReceiptScreen> createState() => _ReceiptScreenState();
}

class _ReceiptScreenState extends ConsumerState<ReceiptScreen> {
  final TextEditingController _quantity = TextEditingController();
  final TextEditingController _note = TextEditingController();
  bool _prefilled = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _prefill());
  }

  void _prefill() {
    if (!mounted || _prefilled) return;
    _prefilled = true;
    final notifier = ref.read(receiptControllerProvider.notifier);

    final code = widget.initialCode?.trim();
    if (code != null && code.isNotEmpty) {
      notifier.setInput(code);
      notifier.resolve();
      return;
    }
    final itemKey = widget.initialItemKey?.trim();
    if (itemKey != null && itemKey.isNotEmpty) {
      notifier.setItem(
        itemKey: itemKey,
        itemName: widget.initialItemName ?? '',
      );
    }
  }

  @override
  void dispose() {
    _quantity.dispose();
    _note.dispose();
    super.dispose();
  }

  Future<void> _pickItem() async {
    final item = await ItemPickerDialog.show(context, title: '选择要入库的器件');
    if (item == null || !mounted) return;
    ref.read(receiptControllerProvider.notifier).setItem(
          itemKey: item.itemKey,
          itemName: item.title,
        );
  }

  Future<void> _confirmAndSubmit() async {
    final state = ref.read(receiptControllerProvider);
    final quantity = state.quantity;
    if (!state.canSubmit || quantity == null) {
      // Show the controller's own actionable validation text.
      await ref.read(receiptControllerProvider.notifier).submit();
      return;
    }

    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('确认入库'),
        content: Text(
          '器件：${state.itemName.isNotEmpty ? state.itemName : state.itemKey}\n'
          '本地档案：${state.sn.isNotEmpty ? state.sn : (state.templateId != null ? '#${state.templateId}' : '首次入库自动创建')}\n'
          '数量：${_format(quantity)}\n'
          '库位：${state.locationLabel.isEmpty ? '库位#${state.locationId}' : state.locationLabel}\n\n'
          '确认后将写入实际库存（可在历史追溯中查看）。',
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('确认入库'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    await ref.read(receiptControllerProvider.notifier).submit();
  }

  Future<void> _createLocation() async {
    final controller = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('新建库位'),
        content: TextField(
          controller: controller,
          autofocus: true,
          decoration: const InputDecoration(
            labelText: '库位名称（如 R01）',
            border: OutlineInputBorder(),
          ),
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('创建'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    final location = await ref
        .read(locationCreateProvider.notifier)
        .create(name: controller.text);
    if (!mounted) return;
    if (location == null) {
      final error = ref.read(locationCreateProvider).error;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(error ?? '创建库位失败。')),
      );
      return;
    }
    // The new 库码 is a real, independent code printed on its own label.
    ref.read(receiptControllerProvider.notifier).setLocation(
          location.id,
          label: location.display,
        );
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('已创建库位 ${location.display}（库码 ${location.code}）')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(receiptControllerProvider);
    final bootstrap = ref.watch(inventoryBootstrapProvider);
    final theme = Theme.of(context);
    final itemKey = state.itemKey.trim();

    // The card's local archives: needed so a multi-archive C code makes the
    // operator choose the SN BEFORE anything is submitted.
    if (itemKey.isNotEmpty) {
      final detail = ref.watch(catalogDetailProvider(itemKey));
      final materials = detail.valueOrNull?.detail.materials ?? const <LabMaterial>[];
      if (materials.isNotEmpty && !_sameMaterials(materials, state.materials)) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (!mounted) return;
          ref.read(receiptControllerProvider.notifier).setMaterials(materials);
        });
      }
    }

    return Scaffold(
      appBar: LabAppBar(fallbackLocation: '/catalog',
        title: const Text('入库'),
        actions: <Widget>[
          IconButton(
            tooltip: '重新开始',
            onPressed: () {
              _quantity.clear();
              _note.clear();
              ref.read(receiptControllerProvider.notifier).reset();
            },
            icon: const Icon(Icons.restart_alt),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: <Widget>[
          if (state.succeeded) _ResultCard(state: state),

          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  ScanInputField(
                    label: '扫描 / 输入编码',
                    enabled: !state.isBusy,
                    autofocus: widget.initialCode == null,
                    onSubmit: (code) {
                      ref.read(receiptControllerProvider.notifier).setInput(code);
                      ref.read(receiptControllerProvider.notifier).resolve();
                    },
                  ),
                  if (state.resolving)
                    const Padding(
                      padding: EdgeInsets.only(top: 8),
                      child: LinearProgressIndicator(),
                    ),
                  if (state.resolved != null) ...<Widget>[
                    const SizedBox(height: 8),
                    _ResolvedCard(resolved: state.resolved!),
                  ],
                  const SizedBox(height: 8),
                  Row(
                    children: <Widget>[
                      Expanded(
                        child: Text(
                          state.itemKey.isEmpty
                              ? '尚未确定要入库的器件'
                              : '器件：${state.itemName.isNotEmpty ? state.itemName : humanItemLabel(state.itemKey, sn: state.sn)}',
                          style: theme.textTheme.bodySmall,
                        ),
                      ),
                      TextButton.icon(
                        onPressed: state.isBusy ? null : _pickItem,
                        icon: const Icon(Icons.search, size: 18),
                        label: const Text('从器件库选择'),
                      ),
                    ],
                  ),
                  if (state.itemKey.isNotEmpty) ...<Widget>[
                    const SizedBox(height: 8),
                    _ArchiveSelector(
                      state: state,
                      enabled: !state.isBusy,
                      onSelected: (material) => ref
                          .read(receiptControllerProvider.notifier)
                          .setTemplate(material.templateId, sn: material.sn),
                    ),
                  ],
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),

          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: <Widget>[
                  bootstrap.when(
                    loading: () => const Padding(
                      padding: EdgeInsets.symmetric(vertical: 8),
                      child: LinearProgressIndicator(),
                    ),
                    error: (error, _) => ErrorView(
                      message: '库位加载失败：$error',
                      onRetry: () => ref.invalidate(inventoryBootstrapProvider),
                      compact: true,
                    ),
                    data: (data) => _LocationField(
                      locations: data.locations,
                      selectedId: state.locationId,
                      enabled: !state.isBusy,
                      onSelected: (id, label) => ref
                          .read(receiptControllerProvider.notifier)
                          .setLocation(id, label: label),
                      onCreate: _createLocation,
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _quantity,
                    enabled: !state.isBusy,
                    keyboardType: const TextInputType.numberWithOptions(decimal: true),
                    inputFormatters: <TextInputFormatter>[
                      FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
                    ],
                    onChanged: (value) =>
                        ref.read(receiptControllerProvider.notifier).setQuantity(value),
                    decoration: const InputDecoration(
                      labelText: '入库数量',
                      hintText: '正整数或小数，例如 100',
                      border: OutlineInputBorder(),
                    ),
                  ),
                  const SizedBox(height: 12),
                  TextField(
                    controller: _note,
                    enabled: !state.isBusy,
                    onChanged: (value) =>
                        ref.read(receiptControllerProvider.notifier).setNote(value),
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

          if (state.error != null) _MessageCard(message: state.error!, error: true),
          if (state.notice != null && !state.succeeded)
            _MessageCard(message: state.notice!),
          if (!state.canSubmit && !state.isBusy)
            Padding(
              padding: const EdgeInsets.only(bottom: 8),
              child: Text(
                '提交前请确认：${state.missingHint}',
                style: theme.textTheme.labelSmall,
              ),
            ),

          FilledButton.icon(
            onPressed: state.isBusy ? null : _confirmAndSubmit,
            icon: state.submitting
                ? const SizedBox(
                    width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.check),
            label: Text(state.succeeded ? '再入库一袋（同一器件）' : '确认入库'),
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  static String _format(double value) =>
      value == value.roundToDouble() ? value.toInt().toString() : value.toStringAsFixed(2);

  /// Cheap comparison used to avoid re-pushing the same archive list.
  static bool _sameMaterials(List<LabMaterial> a, List<LabMaterial> b) {
    if (identical(a, b)) return true;
    if (a.length != b.length) return false;
    for (var index = 0; index < a.length; index++) {
      if (a[index].templateId != b[index].templateId || a[index].sn != b[index].sn) {
        return false;
      }
    }
    return true;
  }
}

/// The local-archive / SN choice of one receipt.
///
/// This is the UI half of root's rule: when one C code has several local
/// archives, the new bag MUST be bound to a chosen archive (or to the archive the
/// scanned SN/bag named). One archive is auto-selected; several require a choice,
/// and the client never falls back to the first row.
class _ArchiveSelector extends StatelessWidget {
  const _ArchiveSelector({
    required this.state,
    required this.enabled,
    required this.onSelected,
  });

  final ReceiptFormState state;
  final bool enabled;
  final ValueChanged<LabMaterial> onSelected;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    if (state.materials.isEmpty) {
      return Row(
        children: <Widget>[
          const Icon(Icons.info_outline, size: 16),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              '该器件还没有本地物料档案：首次入库时由服务器自动创建并生成 SN。',
              style: theme.textTheme.labelSmall,
            ),
          ),
        ],
      );
    }

    if (state.materials.length == 1) {
      final only = state.materials.first;
      return Row(
        children: <Widget>[
          const Icon(Icons.badge_outlined, size: 16),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              '本地档案：${only.display}（唯一档案，已自动选择）',
              style: theme.textTheme.labelSmall,
            ),
          ),
        ],
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        DropdownButtonFormField<int?>(
          isExpanded: true,
          value: state.materials.any(
            (material) => material.templateId == state.templateId,
          )
              ? state.templateId
              : null,
          decoration: InputDecoration(
            isDense: true,
            labelText: '本次入库的本地档案 / SN *',
            helperText: '该编号下有 ${state.materials.length} 个档案，必须选择其一',
            border: const OutlineInputBorder(),
          ),
          items: <DropdownMenuItem<int?>>[
            const DropdownMenuItem<int?>(value: null, child: Text('请选择档案 / SN')),
            for (final material in state.materials)
              DropdownMenuItem<int?>(
                value: material.templateId,
                child: Text(material.display, overflow: TextOverflow.ellipsis),
              ),
          ],
          onChanged: enabled
              ? (value) {
                  for (final material in state.materials) {
                    if (material.templateId == value) {
                      onSelected(material);
                      return;
                    }
                  }
                  onSelected(
                    LabMaterial(
                      templateId: value,
                      productId: null,
                      sn: '',
                      name: '',
                      quantity: null,
                      available: null,
                    ),
                  );
                }
              : null,
        ),
        const SizedBox(height: 4),
        Text(
          '选择只决定新袋归属哪个 SN/档案，不改变历史档案与旧袋记录。',
          style: theme.textTheme.labelSmall
              ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
        ),
      ],
    );
  }
}

class _LocationField extends StatelessWidget {
  const _LocationField({
    required this.locations,
    required this.selectedId,
    required this.onSelected,
    required this.onCreate,
    required this.enabled,
  });

  final List<LabStockLocation> locations;
  final int? selectedId;
  final void Function(int? id, String label) onSelected;
  final VoidCallback onCreate;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: <Widget>[
        Expanded(
          child: DropdownButtonFormField<int?>(
            isExpanded: true,
            value: locations.any((location) => location.id == selectedId)
                ? selectedId
                : null,
            decoration: const InputDecoration(
              labelText: '入库库位',
              border: OutlineInputBorder(),
            ),
            items: <DropdownMenuItem<int?>>[
              const DropdownMenuItem<int?>(value: null, child: Text('请选择库位')),
              for (final location in locations)
                DropdownMenuItem<int?>(
                  value: location.id,
                  child: Text(location.display, overflow: TextOverflow.ellipsis),
                ),
            ],
            onChanged: enabled
                ? (value) {
                    final match = locations.where((location) => location.id == value);
                    onSelected(value, match.isEmpty ? '' : match.first.display);
                  }
                : null,
          ),
        ),
        const SizedBox(width: 8),
        IconButton(
          tooltip: '新建库位',
          onPressed: enabled ? onCreate : null,
          icon: const Icon(Icons.create_new_folder_outlined),
        ),
      ],
    );
  }
}

class _ResolvedCard extends StatelessWidget {
  const _ResolvedCard({required this.resolved});

  final ResolvedCode resolved;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final rows = <String>[
      '类型：${resolved.displayKind}',
      if (resolved.raw.isNotEmpty) '原始编码：${resolved.raw}',
      if (resolved.itemKey.isNotEmpty)
        '器件：${humanItemLabel(resolved.itemKey, sn: resolved.sn ?? '')}',
      if (resolved.bag != null) '袋：${resolved.bag!.display}',
      if (resolved.bag?.sn.isNotEmpty ?? false) 'SN：${resolved.bag!.sn}',
      if (resolved.location != null) '库位：${resolved.location!.display}',
      if (resolved.supplierMetadata.isNotEmpty)
        '来料信息：${resolved.supplierMetadata.entries.take(4).map((entry) => '${entry.key}=${entry.value}').join('、')}',
    ];

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          for (final row in rows)
            Text(row, style: theme.textTheme.bodySmall, maxLines: 2),
        ],
      ),
    );
  }
}

class _ResultCard extends ConsumerWidget {
  const _ResultCard({required this.state});

  final ReceiptFormState state;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final result = state.result;
    final theme = Theme.of(context);
    return Card(
      color: theme.colorScheme.primaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Text('本次入库已完成', style: theme.textTheme.titleSmall),
            const SizedBox(height: 4),
            Text(state.notice ?? ''),
            if (result?.bag != null)
              Text('追溯袋：${result!.bag!.display}（可打印标签）'),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              children: <Widget>[
                FilledButton.tonalIcon(
                  onPressed: () {
                    ref.read(receiptControllerProvider.notifier).startNewSubmission();
                  },
                  icon: const Icon(Icons.add),
                  label: const Text('继续入库'),
                ),
                if (result?.bag?.hasId ?? false)
                  OutlinedButton.icon(
                    onPressed: () => context.push(
                      UnifiedRoutes.labelsForBag(result!.bag!.id!),
                    ),
                    icon: const Icon(Icons.qr_code_2),
                    label: const Text('打印该袋标签'),
                  ),
                if (state.itemKey.isNotEmpty)
                  OutlinedButton.icon(
                    onPressed: () =>
                        context.push(UnifiedRoutes.itemDetail(state.itemKey)),
                    icon: const Icon(Icons.open_in_new),
                    label: const Text('查看器件'),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _MessageCard extends StatelessWidget {
  const _MessageCard({required this.message, this.error = false});

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
