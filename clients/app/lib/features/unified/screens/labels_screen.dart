import 'package:lab_inventory_client/widgets/lab_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/labels.dart';
import '../providers/catalog_providers.dart';
import '../providers/inventory_providers.dart';
import '../providers/label_providers.dart';
import '../widgets/item_picker.dart';
import '../widgets/label_preview.dart';
import '../widgets/status_views.dart';
import 'package:go_router/go_router.dart';
import '../unified_routes.dart';

/// 标签 (labels): design the physical size in millimetres, preview the real A4
/// PDF, save it and print it.
///
/// The user's rules:
///   * a material label prints SN / 库码 / 型号 / C 编号 / 参数 as TEXT and exactly
///     ONE trace QR; a location label prints its OWN 库码 QR only;
///   * width, height, margins, gap and copies are set in mm by the operator;
///   * a label that cannot fit the A4 usable area is REFUSED with an explicit
///     message (no silent crop);
///   * the PDF is produced by the server, decoded here, previewed in-app and can
///     be saved or sent to the real system print dialog on all three platforms;
///   * reparinting an old label calls the preview endpoint only - it never
///     changes stock.
class LabelsScreen extends ConsumerStatefulWidget {
  const LabelsScreen({super.key, this.initialKind, this.initialIds});

  /// `bag` or `location` (deep link / bag QR flow).
  final String? initialKind;

  /// Comma-separated ids to preselect.
  final String? initialIds;

  @override
  ConsumerState<LabelsScreen> createState() => _LabelsScreenState();
}

class _LabelsScreenState extends ConsumerState<LabelsScreen> {
  final TextEditingController _width = TextEditingController(text: '60');
  final TextEditingController _height = TextEditingController(text: '40');
  final TextEditingController _margin = TextEditingController(text: '10');
  final TextEditingController _gap = TextEditingController(text: '2');
  bool _applied = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _applyInitial());
  }

  void _applyInitial() {
    if (!mounted || _applied) return;
    _applied = true;
    final notifier = ref.read(labelDesignerProvider.notifier);
    final kind = (widget.initialKind ?? '').toLowerCase();
    notifier.setKind(switch (kind) {
      'location' => LabelKind.location,
      'pending' => LabelKind.pending,
      _ => LabelKind.bag,
    });
    final design = ref.read(labelDesignerProvider);
    _width.text = '${design.widthMm}';
    _height.text = '${design.heightMm}';
    _margin.text = '${design.marginMm}';
    _gap.text = '${design.gapMm}';
    final ids = (widget.initialIds ?? '')
        .split(',')
        .map((value) => int.tryParse(value.trim()))
        .whereType<int>()
        .toList();
    if (ids.isNotEmpty) {
      // A deep link carries bare ids; the human label is resolved later (from the
      // item detail or the location list), so no internal number is shown here.
      notifier.setSelection(<int, String>{
        for (final id in ids) id: '',
      });
    }
  }

  @override
  void dispose() {
    _width.dispose();
    _height.dispose();
    _margin.dispose();
    _gap.dispose();
    super.dispose();
  }

  Future<void> _pickBags(LabelDesignerState state) async {
    final item = await ItemPickerDialog.show(context, title: '选择器件以打袋标签');
    if (item == null || !mounted) return;
    final detail = await ref.read(catalogDetailProvider(item.itemKey).future);
    if (!mounted) return;
    if (detail.detail.bags.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('该器件没有已入库的实物袋，无法打印追溯标签。')),
      );
      return;
    }

    final selection = Map<int, String>.of(state.selection);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('选择要打印的追溯袋'),
        content: SizedBox(
          width: 420,
          child: StatefulBuilder(
            builder: (context, setDialogState) => SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: <Widget>[
                  for (final bag in detail.detail.bags)
                    CheckboxListTile(
                      dense: true,
                      value: bag.hasId && selection.containsKey(bag.id),
                      title: Text(
                        bag.display,
                        style: const TextStyle(fontFamily: 'monospace'),
                      ),
                      subtitle: Text(
                        <String>[
                          if (bag.sn.isNotEmpty) 'SN ${bag.sn}',
                          if (bag.locationCode.isNotEmpty) '库位 ${bag.locationCode}',
                        ].join(' · '),
                      ),
                      onChanged: !bag.hasId
                          ? null
                          : (value) => setDialogState(() {
                                if (value == true) {
                                  selection[bag.id!] =
                                      '${item.title} ${bag.display}';
                                } else {
                                  selection.remove(bag.id);
                                }
                              }),
                    ),
                ],
              ),
            ),
          ),
        ),
        actions: <Widget>[
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('确定'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    ref.read(labelDesignerProvider.notifier).setSelection(selection);
  }

  Future<void> _preview() async {
    final ok = await ref.read(labelDesignerProvider.notifier).preview();
    final pdf = ref.read(labelDesignerProvider).pdf;
    if (!ok || pdf == null || !mounted) return;
    await showDialog<void>(
      context: context,
      builder: (context) => LabelPdfDialog(pdf: pdf),
    );
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(labelDesignerProvider);
    final layout = state.layout;
    final theme = Theme.of(context);

    return Scaffold(
      appBar: LabAppBar(fallbackLocation: '/catalog',
        title: const Text('标签设计与打印'),
        actions: <Widget>[
          IconButton(
            tooltip: '重新开始',
            onPressed: () => ref.read(labelDesignerProvider.notifier).reset(),
            icon: const Icon(Icons.restart_alt),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(12),
        children: <Widget>[
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text('标签类型', style: theme.textTheme.titleSmall),
                  const SizedBox(height: 6),
                  DropdownButtonFormField<LabelKind>(
                    value: state.kind, isExpanded: true,
                    items: const [
                      DropdownMenuItem(value: LabelKind.pending, child: Text('待入库袋标签')),
                      DropdownMenuItem(value: LabelKind.bag, child: Text('已入库袋标签')),
                      DropdownMenuItem(value: LabelKind.location, child: Text('库位标签')),
                    ],
                    onChanged: state.submitting ? null : (value) {
                      if (value != null) ref.read(labelDesignerProvider.notifier).setKind(value);
                    },
                  ),
                  const SizedBox(height: 6),
                  Text(
                    state.kind != LabelKind.location
                        ? '器件标签：袋码、型号与关键参数，加一个追溯二维码。'
                        : '库位标签：只印一个库码二维码。',
                    style: theme.textTheme.labelSmall,
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),

          // -------------------------------------------------------- object choice
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
                          state.kind != LabelKind.location ? '要打印的追溯袋' : '要打印的库位',
                          style: theme.textTheme.titleSmall,
                        ),
                      ),
                      if (state.kind == LabelKind.bag)
                        TextButton.icon(
                          onPressed: state.submitting ? null : () => _pickBags(state),
                          icon: const Icon(Icons.search, size: 18),
                          label: const Text('按器件选择'),
                        ),
                      TextButton(
                        onPressed: state.selection.isEmpty
                            ? null
                            : () => ref
                                .read(labelDesignerProvider.notifier)
                                .clearSelection(),
                        child: const Text('清空'),
                      ),
                    ],
                  ),
                  if (state.kind == LabelKind.pending)
                    Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('已选 ${state.selection.length} 袋；补打沿用原袋码。'),
                    TextButton.icon(
                      onPressed: () => context.push(UnifiedRoutes.pendingReceipt),
                      icon: const Icon(Icons.playlist_add), label: const Text('在制袋列表管理打印选择'),
                    )])
                  else if (state.kind == LabelKind.bag)
                    Text(
                      state.selection.isEmpty
                          ? '尚未选择追溯袋。可从器件库选择；扫描入库后也可在入库结果中直接打标签。'
                          : _selectionSummary(state),
                      style: theme.textTheme.bodySmall,
                    )
                  else
                    Consumer(
                      builder: (context, ref, _) => ref
                          .watch(inventoryLocationsProvider)
                          .when(
                            loading: () => const Padding(
                              padding: EdgeInsets.symmetric(vertical: 8),
                              child: LinearProgressIndicator(),
                            ),
                            error: (error, _) => ErrorView(
                              message: '库位加载失败：$error',
                              compact: true,
                              onRetry: () => ref.invalidate(inventoryLocationsProvider),
                            ),
                            data: (locations) => locations.isEmpty
                                ? const Text('还没有内部库位，请先在入库页新建库位。')
                                : Column(
                                    children: <Widget>[
                                      for (final location in locations)
                                        CheckboxListTile(
                                          dense: true,
                                          contentPadding: EdgeInsets.zero,
                                          value: location.id != null &&
                                              state.selection.containsKey(location.id),
                                          title: Text(location.display),
                                          subtitle: Text('库码 ${location.code}'),
                                          onChanged: location.id == null
                                              ? null
                                              : (value) => ref
                                                  .read(labelDesignerProvider.notifier)
                                                  .toggleSelection(
                                                    location.id!,
                                                    location.display,
                                                  ),
                                        ),
                                    ],
                                  ),
                          ),
                    ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),

          // ------------------------------------------------------------ mm design
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text('尺寸（毫米）', style: theme.textTheme.titleSmall),
                  const SizedBox(height: 8),
                  Row(
                    children: <Widget>[
                      Expanded(child: _mmField(_width, '标签宽', (value) => ref.read(labelDesignerProvider.notifier).setWidth(value))),
                      const SizedBox(width: 8),
                      Expanded(child: _mmField(_height, '标签高', (value) => ref.read(labelDesignerProvider.notifier).setHeight(value))),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: <Widget>[
                      Expanded(child: _mmField(_margin, '页边距', (value) => ref.read(labelDesignerProvider.notifier).setMargin(value))),
                      const SizedBox(width: 8),
                      Expanded(child: _mmField(_gap, '标签间距', (value) => ref.read(labelDesignerProvider.notifier).setGap(value))),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: <Widget>[
                      Text('份数', style: theme.textTheme.bodyMedium),
                      const SizedBox(width: 8),
                      IconButton(
                        onPressed: state.copies > 1
                            ? () => ref
                                .read(labelDesignerProvider.notifier)
                                .setCopies(state.copies - 1)
                            : null,
                        icon: const Icon(Icons.remove_circle_outline),
                      ),
                      Text('${state.copies}', style: theme.textTheme.titleMedium),
                      IconButton(
                        onPressed: () => ref
                            .read(labelDesignerProvider.notifier)
                            .setCopies(state.copies + 1),
                        icon: const Icon(Icons.add_circle_outline),
                      ),
                      const Spacer(),
                      Text('共 ${layout.labelCount} 张', style: theme.textTheme.labelSmall),
                    ],
                  ),
                  const SizedBox(height: 4),
                  Text(
                    'A4 ${_mm(a4WidthMm)}×${_mm(a4HeightMm)} mm，'
                    '可用 ${_mm(layout.usableWidthMm)}×${_mm(layout.usableHeightMm)} mm。',
                    style: theme.textTheme.labelSmall,
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),

          // --------------------------------------------------------- text fields
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text('文字字段（二维码始终只有一个）', style: theme.textTheme.titleSmall),
                  const SizedBox(height: 4),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: <Widget>[
                      for (final field in kLabelFields)
                        FilterChip(
                          label: Text(field.label, style: const TextStyle(fontSize: 11)),
                          selected: state.fields.contains(field.id),
                          onSelected: (_) => ref
                              .read(labelDesignerProvider.notifier)
                              .toggleField(field.id),
                        ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),

          // ------------------------------------------------------------- layout
          Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text('A4 排版预览', style: theme.textTheme.titleSmall),
                  const SizedBox(height: 8),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Expanded(child: LabelLayoutPreview(layout: layout)),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: <Widget>[
                            Text(layout.summary, style: theme.textTheme.bodySmall),
                            const SizedBox(height: 6),
                            for (final error in layout.errors)
                              Text(
                                '✕ $error',
                                style: theme.textTheme.labelSmall
                                    ?.copyWith(color: theme.colorScheme.error),
                              ),
                            for (final warning in layout.warnings)
                              Text(
                                '! $warning',
                                style: theme.textTheme.labelSmall
                                    ?.copyWith(color: theme.colorScheme.tertiary),
                              ),
                          ],
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: 8),

          if (state.error != null)
            Card(
              color: theme.colorScheme.errorContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Text(state.error!, style: theme.textTheme.bodySmall),
              ),
            ),
          if (state.notice != null)
            Card(
              color: theme.colorScheme.tertiaryContainer,
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Text(state.notice!, style: theme.textTheme.bodySmall),
              ),
            ),
          const SizedBox(height: 8),

          FilledButton.icon(
            onPressed: state.canPreview ? _preview : null,
            icon: state.submitting
                ? const SizedBox(
                    width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.picture_as_pdf),
            label: const Text('生成 A4 PDF 并预览'),
          ),
          const SizedBox(height: 6),
          Text(
            '生成/重新打印不会改变库存；打印使用系统打印对话框，保存写入本机文档目录。',
            style: theme.textTheme.labelSmall,
          ),
          const SizedBox(height: 24),
        ],
      ),
    );
  }

  Widget _mmField(
    TextEditingController controller,
    String label,
    ValueChanged<double> onChanged,
  ) {
    return TextField(
      controller: controller,
      keyboardType: const TextInputType.numberWithOptions(decimal: true),
      inputFormatters: <TextInputFormatter>[
        FilteringTextInputFormatter.allow(RegExp(r'[0-9.]')),
      ],
      onChanged: (value) {
        final parsed = double.tryParse(value.trim());
        if (parsed != null) onChanged(parsed);
      },
      decoration: InputDecoration(
        isDense: true,
        labelText: '$label (mm)',
        border: const OutlineInputBorder(),
      ),
    );
  }

  static String _mm(double value) {
    if (value == value.roundToDouble()) return value.toInt().toString();
    return value.toStringAsFixed(1);
  }

  /// Human summary of the current selection (never an internal id or key).
  static String _selectionSummary(LabelDesignerState state) {
    final labels = state.selection.values.where((label) => label.isNotEmpty).toList();
    if (labels.isEmpty) return '已选 ${state.selection.length} 项';
    return '已选 ${state.selection.length} 个袋：'
        '${labels.take(3).join('、')}'
        '${labels.length > 3 ? ' …' : ''}';
  }
}
