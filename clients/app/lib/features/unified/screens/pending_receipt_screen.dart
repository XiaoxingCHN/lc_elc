import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../models/lab_api_exception.dart';

import '../../../services/lab_api_client.dart';
import '../../../widgets/lab_ui.dart';
import '../models/detail_models.dart';
import '../models/json_read.dart';
import '../models/pending_receipt.dart';
import '../models/unified_item.dart';
import '../providers/inventory_providers.dart';
import '../providers/unified_providers.dart';
import '../unified_routes.dart';
import '../widgets/item_picker.dart';
import '../widgets/scan_input.dart';

/// Re-keying discards forms and in-flight responses on account/company changes.
class PendingReceiptScreen extends ConsumerWidget {
  const PendingReceiptScreen({
    super.key,
    this.initialTab = 0,
    this.initialItemKey,
  });
  final int initialTab;
  final String? initialItemKey;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scope = ref.watch(effectiveSessionScopeProvider);
    ref.listen(effectiveSessionScopeProvider, (previous, next) {
      if (previous == next) return;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (context.mounted) {
          Navigator.of(context).popUntil((route) => route is PageRoute);
        }
      });
    });
    final base = Theme.of(context);
    return Theme(
      data: base.copyWith(
        textTheme: base.textTheme.copyWith(
          bodyLarge: base.textTheme.bodyLarge?.copyWith(fontSize: 17),
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(minimumSize: const Size(44, 48)),
        ),
        textButtonTheme: TextButtonThemeData(
          style: TextButton.styleFrom(minimumSize: const Size(44, 44)),
        ),
        inputDecorationTheme: base.inputDecorationTheme.copyWith(
          fillColor: base.colorScheme.surfaceContainerHighest,
          filled: true,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: BorderSide.none,
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(12),
            borderSide: BorderSide.none,
          ),
        ),
      ),
      child: _ReceiptWorkspace(
        key: ValueKey(scope.key),
        initialTab: initialTab,
        initialItemKey: initialItemKey,
      ),
    );
  }
}

class _ReceiptWorkspace extends ConsumerStatefulWidget {
  const _ReceiptWorkspace({
    super.key,
    required this.initialTab,
    this.initialItemKey,
  });
  final int initialTab;
  final String? initialItemKey;
  @override
  ConsumerState<_ReceiptWorkspace> createState() => _ReceiptWorkspaceState();
}

class _ReceiptWorkspaceState extends ConsumerState<_ReceiptWorkspace> {
  late int _tab = widget.initialTab;
  final _quantity = TextEditingController();
  final _count = TextEditingController(text: '1');
  final _note = TextEditingController();
  final _scan = TextEditingController();
  final _actual = TextEditingController();
  UnifiedItem? _item;
  Map<String, dynamic>? _newMaterial;
  List<LabMaterial> _materials = [];
  int? _templateId;
  List<PendingReceipt> _records = [];
  PendingReceipt? _resolved;
  List<Map<String, dynamic>> _recommendations = [];
  int? _locationId;
  String? _error;
  String? _notice;
  bool _busy = false;
  bool _loaded = false;
  bool _showProcessed = false;
  int _scanCycle = 0;
  Map<String, dynamic>? _createAttempt;
  Map<String, dynamic>? _confirmAttempt;

  LabApiClient get _api => ref.read(labApiProvider);

  @override
  void initState() {
    super.initState();
    Future.microtask(
      () => _run(() async {
        await _reload();
        final key = widget.initialItemKey;
        if (!mounted || key == null || key.isEmpty) return;
        final detail = await _api.detail(key);
        if (!mounted) return;
        setState(() {
          _item = detail.item ?? UnifiedItem.fromJson({'item_key': key});
          _materials = detail.materials;
          _templateId = _materials.length == 1
              ? _materials.single.templateId
              : null;
        });
      }),
    );
  }

  @override
  void dispose() {
    for (final c in [_quantity, _count, _note, _scan, _actual]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> _run(Future<void> Function() action) async {
    if (!mounted || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });
    try {
      await action();
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = describeLabError(e);
          if (e is LabApiException &&
              const {
                'VALIDATION_ERROR',
                'PRECONDITION_FAILED',
                'FORBIDDEN',
                'NOT_FOUND',
                'AMBIGUOUS_MATERIAL',
              }.contains(e.code)) {
            _createAttempt = null;
            _confirmAttempt = null;
          }
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          _busy = false;
          if (_tab == 1 && _resolved == null) _scanCycle++;
        });
      }
    }
  }

  Future<void> _load() => _run(_reload);

  Future<void> _reload() async {
    final records = await _api.pendingReceipts();
    if (mounted) {
      setState(() {
        _records = records;
        _loaded = true;
      });
    }
  }

  Future<void> _pickItem() async {
    final item = await ItemPickerDialog.show(context);
    if (item == null || !mounted) return;
    await _run(() async {
      final detail = await _api.detail(item.itemKey);
      if (!mounted) return;
      setState(() {
        _item = item;
        _newMaterial = null;
        _materials = detail.materials;
        _templateId = _materials.length == 1
            ? _materials.single.templateId
            : null;
        _createAttempt = null;
      });
    });
  }

  Future<void> _newItem() async {
    final material = await showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (context) => const _NewMaterialSheet(),
    );
    if (material == null || !mounted) return;
    setState(() {
      _newMaterial = material;
      _item = null;
      _materials = [];
      _templateId = null;
      _createAttempt = null;
    });
  }

  Future<void> _create() => _run(() async {
    if (_createAttempt == null) {
      final quantity = double.tryParse(_quantity.text);
      final count = int.tryParse(_count.text);
      if ((_item == null && _newMaterial == null) ||
          quantity == null ||
          !quantity.isFinite ||
          quantity <= 0 ||
          count == null ||
          count < 1 ||
          count > 100) {
        throw StateError('请选择器件，填写每袋数量和袋数（1～100）。');
      }
      if (_materials.length > 1 && _templateId == null) {
        throw StateError('请选择本次制袋对应的内部档案。');
      }
      _createAttempt = {
        'request_key': newRequestKey(),
        if (_item != null) 'item_key': _item!.itemKey,
        if (_newMaterial != null) 'material': _newMaterial,
        'quantity': quantity,
        'count': count,
        'note': _note.text.trim(),
        if (_templateId != null) 'product_template_id': _templateId,
      };
    }
    final result = await _api.createPending(_createAttempt!);
    if (!mounted) return;
    _createAttempt = null;
    if (_newMaterial != null) {
      // Subsequent bags must reuse the just-created archive, not create it again.
      final first = asMapList(result['records']).first;
      _item = UnifiedItem.fromJson({
        'item_key': first['item_key'],
        'name': first['name'],
      });
      _templateId = firstInt(first, const ['product_template_id']);
      _newMaterial = null;
    }
    _quantity.clear();
    _note.clear();
    _count.text = '1';
    setState(
      () => _notice = '已生成 ${asMapList(result['records']).length} 个袋码，可继续添加。',
    );
    // Keep creation success distinct from a subsequent list refresh failure.
    await _reload();
  });

  Future<void> _resolve(String raw) => _run(() async {
    _confirmAttempt = null;
    setState(() {
      _resolved = null;
      _recommendations = [];
      _locationId = null;
    });
    final data = await _api.resolvePending(raw);
    if (!mounted) return;
    final record = asMap(data['record']);
    if (record.isEmpty) {
      final bag = asMap(data['bag']);
      setState(() => _notice = '该袋已入库：${bag['trace_code'] ?? ''}，不会重复入库。');
      return;
    }
    final resolved = PendingReceipt.fromJson(record);
    setState(() {
      _resolved = resolved;
      _actual.text = '${resolved.quantity}';
      _recommendations = asMapList(data['recommendations']);
    });
  });

  Future<void> _confirm() async {
    if (_resolved == null || !_resolved!.isPending || _busy) return;
    if (_confirmAttempt == null) {
      final quantity = double.tryParse(_actual.text);
      if (_locationId == null ||
          quantity == null ||
          !quantity.isFinite ||
          quantity <= 0) {
        setState(() => _error = '请填写有效数量并选择内部库位。');
        return;
      }
      final approved = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('确认入库'),
          content: Text(
            '${_resolved!.name}\n袋码 ${_resolved!.traceCode}\n数量 $quantity\n'
            '库位 ${ref.read(inventoryLocationsProvider).valueOrNull?.where((l) => l.id == _locationId).map((l) => l.display).join('') ?? ''}\n确认后将增加实际库存。',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('返回核对'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('确认入库'),
            ),
          ],
        ),
      );
      if (approved != true || !mounted) return;
      _confirmAttempt = {
        'request_key': newRequestKey(),
        'pending_id': _resolved!.id,
        'quantity': quantity,
        'location_id': _locationId,
      };
    }
    await _run(() async {
      final data = await _api.confirmPending(_confirmAttempt!);
      if (!mounted) return;
      ref
          .read(dataRevisionProvider.notifier)
          .bump(inventory: data['inventory_revision']?.toString());
      final code = _resolved!.traceCode;
      setState(() {
        _resolved = null;
        _confirmAttempt = null;
        _locationId = null;
        _scan.clear();
        _notice = '$code 已入库，请扫描下一袋。';
      });
      await _reload();
    });
  }

  Future<void> _cancel(PendingReceipt record) async {
    final approved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('取消待入库袋？'),
        content: Text('${record.name}\n${record.traceCode}\n取消后不能再使用此码入库。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('保留'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('取消此袋'),
          ),
        ],
      ),
    );
    if (approved != true || !mounted) return;
    await _run(() async {
      await _api.updatePending(record.id, cancel: true);
      if (mounted) await _reload();
    });
  }

  void _print() {
    final ids = _records
        .where((r) => r.selected && !r.isCancelled && (_showProcessed || r.isPending))
        .map((r) => r.id)
        .join(',');
    context.push(
      Uri(
        path: UnifiedRoutes.labels,
        queryParameters: {'kind': 'pending', 'ids': ids},
      ).toString(),
    );
  }

  Widget _section(List<Widget> children) => Card(
    color: Theme.of(context).colorScheme.surfaceContainerLow,
    elevation: 0,
    margin: const EdgeInsets.only(bottom: 20),
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: children,
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final locations = ref.watch(inventoryLocationsProvider);
    final selectedCount = _records
        .where((r) => r.selected && !r.isCancelled && (_showProcessed || r.isPending))
        .length;
    final attempt = _tab == 0 ? _createAttempt : _confirmAttempt;
    return Scaffold(
      backgroundColor: theme.colorScheme.surface,
      appBar: AppBar(
        title: const Text('采购入库'),
        backgroundColor: theme.colorScheme.surface,
        foregroundColor: theme.colorScheme.onSurface,
        leading: const LabBackButton(fallbackLocation: UnifiedRoutes.catalog),
        actions: [
          IconButton(
            tooltip: '刷新待入库记录',
            onPressed: _busy ? null : _load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: SafeArea(
        child: Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 760),
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [
                Text(
                  _tab == 0 ? '先贴码，再上架' : '逐袋核对入库',
                  style: theme.textTheme.headlineMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 8),
                Text(
                  _tab == 0 ? '集中准备标签，贴到对应实物袋。' : '扫描袋码，核对数量和库位后确认。',
                  style: theme.textTheme.bodyLarge,
                ),
                const SizedBox(height: 20),
                if (MediaQuery.textScalerOf(context).scale(16) > 22)
                  DropdownButtonFormField<int>(
                    value: _tab,
                    isExpanded: true,
                    items: const [
                      DropdownMenuItem(value: 0, child: Text('1  制袋贴标')),
                      DropdownMenuItem(value: 1, child: Text('2  扫码上架')),
                    ],
                    onChanged: _busy
                        ? null
                        : (value) {
                            if (value != null) setState(() => _tab = value);
                          },
                  )
                else
                  CupertinoSlidingSegmentedControl<int>(
                    groupValue: _tab,
                    children: const {
                      0: Padding(
                        padding: EdgeInsets.all(12),
                        child: Text('1  制袋贴标'),
                      ),
                      1: Padding(
                        padding: EdgeInsets.all(12),
                        child: Text('2  扫码上架'),
                      ),
                    },
                    disabledChildren: _busy ? const {0, 1} : const {},
                    onValueChanged: (value) {
                      if (!_busy && value != null) setState(() => _tab = value);
                    },
                  ),
                const SizedBox(height: 20),
                if (_busy)
                  const Padding(
                    padding: EdgeInsets.only(bottom: 16),
                    child: LinearProgressIndicator(),
                  ),
                if (_error != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: Semantics(
                      liveRegion: true,
                      child: Text(
                        _error!,
                        style: theme.textTheme.bodyLarge?.copyWith(
                          color: theme.colorScheme.error,
                        ),
                      ),
                    ),
                  ),
                if (_notice != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: Semantics(
                      liveRegion: true,
                      child: Text(_notice!, style: theme.textTheme.bodyLarge),
                    ),
                  ),
                if (attempt != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: Text(
                      '上次提交结果待确认。请重试以取回结果；使用相同请求不会重复生成或入库。',
                      style: theme.textTheme.bodyMedium,
                    ),
                  ),
                if (_tab == 0) ...[
                  _section([
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(
                        _item?.title ??
                            _newMaterial?['name']?.toString() ??
                            '选择元器件',
                      ),
                      subtitle: Text(
                        _item == null ? '搜索型号、参数或立创编号' : '核对型号和规格后制袋',
                      ),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: _busy || attempt != null ? null : _pickItem,
                    ),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton(
                        onPressed: _busy || attempt != null ? null : _newItem,
                        child: const Text('资料库没有？新建器件'),
                      ),
                    ),
                    if (_materials.length > 1)
                      DropdownButtonFormField<int>(
                        value: _templateId,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: '内部档案 / SN',
                        ),
                        items: _materials
                            .map(
                              (m) => DropdownMenuItem(
                                value: m.templateId,
                                child: Text(m.display),
                              ),
                            )
                            .toList(),
                        onChanged: _busy || attempt != null
                            ? null
                            : (v) => setState(() => _templateId = v),
                      ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _quantity,
                      enabled: !_busy && attempt == null,
                      keyboardType: const TextInputType.numberWithOptions(
                        decimal: true,
                      ),
                      decoration: const InputDecoration(
                        labelText: '每袋初始数量',
                        hintText: '例如 100',
                      ),
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _count,
                      enabled: !_busy && attempt == null,
                      keyboardType: TextInputType.number,
                      decoration: const InputDecoration(
                        labelText: '实物袋数',
                        helperText: '每袋独立编号；不同数量请分次添加。',
                      ),
                    ),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _note,
                      enabled: !_busy && attempt == null,
                      maxLines: 2,
                      decoration: const InputDecoration(labelText: '备注（选填）'),
                    ),
                    const SizedBox(height: 20),
                    FilledButton.icon(
                      onPressed: _busy ? null : _create,
                      icon: const Icon(Icons.add),
                      label: Text(attempt == null ? '生成袋码并加入待打印' : '重试生成袋码'),
                    ),
                    const SizedBox(height: 8),
                    const Text('此步骤仅创建待入库记录，不增加库存。'),
                  ]),
                  Text('待入库与打印', style: theme.textTheme.titleLarge),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('显示已入库和已取消记录'),
                    value: _showProcessed,
                    onChanged: (value) =>
                        setState(() => _showProcessed = value),
                  ),
                  const SizedBox(height: 12),
                  if (_loaded && _records.isEmpty)
                    _section([const Text('还没有待入库袋。选择器件后，生成第一批标签。')]),
                  for (final record in _records.where(
                    (r) => _showProcessed || r.isPending,
                  ))
                    _section([
                      Text(record.name, style: theme.textTheme.titleMedium),
                      const SizedBox(height: 6),
                      SelectableText(
                        record.traceCode,
                        style: theme.textTheme.bodyLarge,
                      ),
                      Text('${record.status} · 数量 ${record.quantity}'),
                      if (!record.isCancelled)
                        CheckboxListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('加入待打印'),
                          value: record.selected,
                          onChanged: _busy
                              ? null
                              : (value) => _run(() async {
                                  await _api.updatePending(
                                    record.id,
                                    selected: value,
                                  );
                                  if (mounted) await _reload();
                                }),
                        ),
                      if (record.isPending)
                        Align(
                          alignment: Alignment.centerRight,
                          child: TextButton(
                            onPressed: _busy ? null : () => _cancel(record),
                            child: const Text('取消此袋'),
                          ),
                        ),
                    ]),
                  if (selectedCount > 200) const Text('一次最多打印 200 袋，请分批选择。'),
                  FilledButton.icon(
                    onPressed:
                        _busy || selectedCount == 0 || selectedCount > 200
                        ? null
                        : _print,
                    icon: const Icon(Icons.print_outlined),
                    label: Text('预览并打印（$selectedCount 袋）'),
                  ),
                ] else ...[
                  _section([
                    ScanInputField(
                      key: ValueKey(_scanCycle),
                      controller: _scan,
                      enabled: !_busy && attempt == null,
                      label: '扫描袋追溯码',
                      onSubmit: _resolve,
                    ),
                    if (_resolved != null) ...[
                      const SizedBox(height: 20),
                      Text(_resolved!.name, style: theme.textTheme.titleLarge),
                      SelectableText(
                        '${_resolved!.traceCode} · ${_resolved!.status}',
                      ),
                      Text(
                        [
                          _resolved!.raw['package'],
                          _resolved!.raw['sn'],
                        ].where((v) => v != null && v != '').join(' · '),
                      ),
                      for (final p in asMapList(_resolved!.raw['parameters']))
                        Text(
                          '${p['name'] ?? p['key'] ?? ''}：${p['value'] ?? ''}',
                        ),
                      if (_resolved!.isPending) ...[
                        const SizedBox(height: 20),
                        TextField(
                          controller: _actual,
                          enabled: !_busy && attempt == null,
                          keyboardType: const TextInputType.numberWithOptions(
                            decimal: true,
                          ),
                          decoration: const InputDecoration(
                            labelText: '实际入库数量',
                          ),
                        ),
                        const SizedBox(height: 16),
                        for (final loc in _recommendations)
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text('${loc['name']}'),
                            subtitle: Text('推荐 · ${loc['reason']}'),
                            trailing: _locationId == loc['id']
                                ? const Icon(Icons.check)
                                : null,
                            onTap: _busy || attempt != null
                                ? null
                                : () => setState(
                                    () => _locationId = loc['id'] as int,
                                  ),
                          ),
                        locations.when(
                          loading: () => const LinearProgressIndicator(),
                          error: (e, s) => TextButton(
                            onPressed: () =>
                                ref.invalidate(inventoryLocationsProvider),
                            child: const Text('库位加载失败，点击重试'),
                          ),
                          data: (items) => DropdownButtonFormField<int>(
                            value: items.any((l) => l.id == _locationId)
                                ? _locationId
                                : null,
                            isExpanded: true,
                            decoration: const InputDecoration(
                              labelText: '入库库位',
                            ),
                            items: items
                                .map(
                                  (l) => DropdownMenuItem(
                                    value: l.id,
                                    child: Text(l.display),
                                  ),
                                )
                                .toList(),
                            onChanged: _busy || attempt != null
                                ? null
                                : (value) =>
                                      setState(() => _locationId = value),
                          ),
                        ),
                        const SizedBox(height: 16),
                        ScanInputField(
                          enabled: !_busy && attempt == null,
                          autofocus: false,
                          label: '或扫描库位码',
                          onSubmit: (raw) => _run(() async {
                            final code = await _api.resolveCode(raw);
                            if (!mounted) return;
                            if (!code.isLocation) throw StateError('请扫描库位标签。');
                            setState(() => _locationId = code.location!.id);
                          }),
                        ),
                        const SizedBox(height: 20),
                        FilledButton(
                          onPressed: _busy ? null : _confirm,
                          child: Text(attempt == null ? '确认入库' : '重试确认入库'),
                        ),
                      ],
                    ],
                  ]),
                  TextButton(
                    onPressed: _busy
                        ? null
                        : () => context.push(UnifiedRoutes.receipt),
                    child: const Text('未制袋标签？直接入库'),
                  ),
                ],
                const SizedBox(height: 24),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _NewMaterialSheet extends StatefulWidget {
  const _NewMaterialSheet();
  @override
  State<_NewMaterialSheet> createState() => _NewMaterialSheetState();
}

class _NewMaterialSheetState extends State<_NewMaterialSheet> {
  final _fields = {
    for (final key in ['name', 'mpn', 'package', 'brand', 'specification'])
      key: TextEditingController(),
  };
  final _form = GlobalKey<FormState>();
  @override
  void dispose() {
    for (final c in _fields.values) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
    child: SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Form(
        key: _form,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('新建器件', style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 16),
            for (final field in const {
              'name': '名称',
              'mpn': '型号（选填）',
              'package': '封装（选填）',
              'brand': '品牌（选填）',
              'specification': '关键参数（选填）',
            }.entries)
              Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: TextFormField(
                  controller: _fields[field.key],
                  decoration: InputDecoration(labelText: field.value),
                  validator: field.key == 'name'
                      ? (value) => value == null || value.trim().isEmpty
                            ? '请输入器件名称'
                            : null
                      : null,
                ),
              ),
            FilledButton(
              onPressed: () {
                if (_form.currentState!.validate())
                  Navigator.pop(context, {
                    for (final field in _fields.entries)
                      field.key: field.value.text.trim(),
                  });
              },
              child: const Text('使用此器件'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('取消'),
            ),
          ],
        ),
      ),
    ),
  );
}
