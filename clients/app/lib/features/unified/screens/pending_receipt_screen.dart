import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../models/lab_api_exception.dart';

import '../../../services/lab_api_client.dart';
import '../../../widgets/lab_ui.dart';
import '../models/detail_models.dart';
import '../models/inventory.dart';
import '../models/json_read.dart';
import '../models/pending_receipt.dart';
import '../models/unified_item.dart';
import '../providers/catalog_fetch_controller.dart';
import '../providers/inventory_providers.dart';
import '../providers/unified_providers.dart';
import '../unified_routes.dart';
import '../widgets/catalog_fetch_panel.dart';
import '../widgets/catalog_suggest_search.dart';
import '../widgets/item_picker.dart';
import '../widgets/scan_input.dart';
import '../widgets/status_banner.dart';

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

  /// The STICKY putaway location chosen by scanning a location code.
  ///
  /// The operator's flow chart is explicit: scan the shelf's QR once, then keep
  /// scanning bags into it until that shelf is done - "一直扫袋码入库一直到当前
  /// 仓库所属器件录完". This is the bin-first putaway pattern shipped by Oracle
  /// WMS Cloud (scan location 1/3, then LPN 2/3, location persists) and
  /// Acumatica ("put away another item from the current destination location?"
  /// loops back to the ITEM scan, never the location scan).
  ///
  /// Holding it separately from [_locationId] matters: [_locationId] is the
  /// per-bag choice the operator can still override, while this remembers what
  /// the shelf scan locked in. Null means "not in a putaway session yet", which
  /// is what makes the screen ask for a location code first.
  int? _putawayLocationId;
  String _putawayLocationLabel = '';

  String? _error;
  String? _notice;
  bool _busy = false;
  bool _loaded = false;
  int _scanCycle = 0;

  /// Server-side queue filters.  [state] uses the server's own vocabulary so
  /// the queue never has to download records it is about to hide.
  final _queueSearch = TextEditingController();
  String _stateFilter = 'pending';
  Timer? _queueDebounce;
  int _queueSeq = 0;
  Map<String, dynamic>? _createAttempt;
  Map<String, dynamic>? _confirmAttempt;

  /// The card committed by the LAST inline suggestion pick, so a subsequent
  /// keystroke can drop that selection instead of keeping it armed.
  String? _suggestPicked;

  /// True while [_item] came from a suggestion pick. The detail read may swap
  /// in an item with a DIFFERENT item_key (a supplier row resolves to a local
  /// archive), so "is the current card the picked one" cannot be decided by
  /// comparing keys; a later keystroke must still drop this selection.
  bool _selectionFromSuggestion = false;

  /// Handle on the suggestion field, so a finished fetch can re-run its search.
  final GlobalKey<CatalogSuggestFieldState> _suggestKey =
      GlobalKey<CatalogSuggestFieldState>();

  /// The ONE on-demand fetch this form can start (single exact C code / MPN).
  late final CatalogFetchController _fetch;

  /// Bumped on every keystroke / clear so an in-flight archive lookup cannot
  /// resurrect a selection the operator already replaced.
  int _selectionSeq = 0;

  /// True while the just-picked card's archives are being re-read. The pick is
  /// already committed; this only keeps create blocked until the archive list
  /// is known.
  bool _loadingArchives = false;

  LabApiClient get _api => ref.read(labApiProvider);

  @override
  void initState() {
    super.initState();
    _fetch = CatalogFetchController(
      api: _api,
      onDone: () async {
        _suggestKey.currentState?.research();
      },
    )..addListener(_onFetchChanged);
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

  void _onFetchChanged() {
    if (mounted) setState(() {});
  }

  void _startFetch(CatalogFetchSuggestion suggestion) {
    unawaited(_fetch.start(query: suggestion.query));
  }

  @override
  void dispose() {
    _fetch.dispose();
    _queueDebounce?.cancel();
    for (final c in [_quantity, _count, _note, _scan, _actual, _queueSearch]) {
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

  /// Reloads the queue with the current keyword/state filters applied by the
  /// server.  [seq] drops a response that a newer filter already superseded.
  Future<void> _reload() async {
    final seq = ++_queueSeq;
    final records = await _api.pendingReceipts(
      query: _queueSearch.text,
      state: _stateFilter,
    );
    if (!mounted || seq != _queueSeq) return;
    setState(() {
      _records = records;
      _loaded = true;
    });
  }

  /// Typing is debounced so one keystroke never costs one round trip.
  void _scheduleQueueReload() {
    _queueDebounce?.cancel();
    _queueDebounce = Timer(
      const Duration(milliseconds: 350),
      () => _run(_reload),
    );
  }

  Future<void> _pickItem() async {
    final item = await ItemPickerDialog.show(context, onCreate: _newItem);
    if (item == null || !mounted) return;
    await _run(() async {
      final detail = await _api.detail(item.itemKey);
      if (!mounted) return;
      setState(() {
        _item = item;
        _selectionFromSuggestion = false;
        _suggestPicked = null;
        _newMaterial = null;
        _materials = detail.materials;
        _templateId = _materials.length == 1
            ? _materials.single.templateId
            : null;
        _createAttempt = null;
        _error = null;
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
      _selectionFromSuggestion = false;
      _suggestPicked = null;
      _materials = [];
      _templateId = null;
      _createAttempt = null;
      _error = null;
    });
  }

  /// Commits an inline suggestion: loads its real archives and makes the
  /// operator pick one when the C code maps to several.
  ///
  /// The archives are always re-read from the service; a suggestion never
  /// carries an archive list that could be stale.
  Future<void> _selectSuggestion(UnifiedItem item) async {
    final token = ++_selectionSeq;
    _suggestPicked = item.itemKey;
    // Commit the pick in this frame. The suggestion row already carries the
    // identity, name and archive ids the create call needs, and waiting for the
    // archive read before showing anything made a tap look like nothing
    // happened (worse: a failed read used to discard the pick entirely). The
    // archive list is re-read from the service below and replaces this state.
    setState(() {
      _item = item;
      _selectionFromSuggestion = true;
      _newMaterial = null;
      _materials = const <LabMaterial>[];
      _templateId = null;
      _createAttempt = null;
      _confirmAttempt = null;
      _error = null;
      _notice = null;
      _loadingArchives = true;
    });
    try {
      final detail = await _api.detail(item.itemKey);
      if (!mounted || token != _selectionSeq) return;
      setState(() {
        _item = detail.item ?? item;
        _materials = detail.materials;
        _templateId = detail.materials.length == 1
            ? detail.materials.single.templateId
            : null;
        _loadingArchives = false;
      });
    } catch (error) {
      if (!mounted || token != _selectionSeq) return;
      setState(() {
        _loadingArchives = false;
        _notice = '已选择“${item.title}”，但读取内部档案失败：'
            '${describeLabError(error)}。可以先按当前资料制袋；'
            '需要选内部档案时请重新选择。';
      });
    }
  }

  /// Drops the selection while the operator edits the query again.
  ///
  /// A card left selected under a changed query is a stale commit: it could
  /// create bags for a component the field no longer names. Picks that were
  /// replaced by the picker / scan / reset are left alone.
  void _releaseSuggestion(String _) {
    _selectionSeq++;
    if (_suggestPicked == null) return;
    _suggestPicked = null;
    if (!_selectionFromSuggestion) return;
    _selectionFromSuggestion = false;
    setState(() {
      _item = null;
      _materials = [];
      _templateId = null;
      _createAttempt = null;
      _error = null;
      _loadingArchives = false;
    });
  }

  void _clearItem() {
    if (_busy) return;
    _selectionSeq++;
    setState(() {
      _item = null;
      _newMaterial = null;
      _loadingArchives = false;
      _materials = [];
      _templateId = null;
      _suggestPicked = null;
      _selectionFromSuggestion = false;
      _createAttempt = null;
      _error = null;
    });
  }

  bool get _ambiguousArchive => _materials.length > 1 && _templateId == null;

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
        setState(() => _error = '请选择器件，填写每袋数量和袋数（1～100）。');
        return;
      }
      if (_materials.length > 1 && _templateId == null) {
        setState(() => _error = '请选择本次制袋对应的内部档案。');
        return;
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
      _selectionFromSuggestion = false;
      _suggestPicked = null;
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

  /// One scan field serves BOTH steps, exactly as the flow chart draws it.
  ///
  /// Before a location is chosen the only thing a scan can usefully be is a
  /// shelf code, so it is interpreted that way; afterwards the same field takes
  /// bag codes and keeps the shelf. That avoids the "scan bag, then scan
  /// location, then scan bag again" ping-pong the operator rejected.
  Future<void> _handleScan(String raw) async {
    final text = raw.trim();
    if (text.isEmpty) return;

    // A `LABL:` payload is unambiguously a location, whatever the current step.
    final looksLikeLocation = text.toUpperCase().startsWith('LABL:');
    if (_putawayLocationId == null || looksLikeLocation) {
      final started = await _scanLocation(text);
      // If it was not a location code, fall through to the bag path so a
      // mistyped first scan still does something useful.
      if (started) return;
      if (looksLikeLocation) return;
    }
    await _resolve(text);
  }

  /// Reads a location code and enters (or re-targets) the putaway session.
  ///
  /// Returns true when [raw] really was a location, so the caller knows whether
  /// to fall back to treating it as a bag code.
  Future<bool> _scanLocation(String raw) async {
    ResolvedCode code;
    try {
      code = await _api.resolveCode(raw);
    } catch (_) {
      return false;
    }
    if (!code.isLocation || code.location == null) return false;
    final location = code.location!;
    if (!mounted) return true;
    setState(() {
      _putawayLocationId = location.id;
      _putawayLocationLabel = location.display;
      _locationId = location.id;
      _error = null;
      _notice = '已选定库位 ${location.display}，现在可以连续扫描袋码入库。';
      _scan.clear();
      _scanCycle++;
    });
    return true;
  }

  Future<void> _resolve(String raw) => _run(() async {
    _confirmAttempt = null;
    setState(() {
      _resolved = null;
      _recommendations = [];
      // The shelf scan is what persists across bags; do NOT clear it here or
      // the operator is forced back to scanning the location for every bag.
      _locationId = _putawayLocationId;
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
        // The shelf stays selected: this is the "keep scanning bags into the
        // same bin" loop (Oracle: location 1/3, then LPN 2/3, repeat).
        _locationId = _putawayLocationId;
        _scan.clear();
        _scanCycle++;
        _notice = _putawayLocationId == null
            ? '$code 已入库，请扫描下一袋。'
            : '$code 已入库到 $_putawayLocationLabel，请扫描下一袋。';
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
    // The server already applied the queue filters; cancelled bags are never
    // printed even when the operator filters for processed records.
    final ids = _records
        .where((r) => r.selected && !r.isCancelled)
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
        .where((r) => r.selected && !r.isCancelled)
        .length;
    final attempt = _tab == 0 ? _createAttempt : _confirmAttempt;
    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: LabAppBar(
        title: const Text('采购入库'),
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
                  GlassSegmentedControl<int>(
                    value: _tab,
                    onChanged: _busy
                        ? null
                        : (value) => setState(() => _tab = value),
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
                      child: StatusBanner(
                        message: _error!,
                        tone: StatusTone.error,
                      ),
                    ),
                  ),
                if (_notice != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: Semantics(
                      liveRegion: true,
                      child: StatusBanner(
                        message: _notice!,
                        tone: StatusTone.notice,
                      ),
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
                    CatalogSuggestField(
                      key: _suggestKey,
                      enabled: !_busy && attempt == null,
                      label: '搜索并选择元器件',
                      helperText: _item != null
                          ? '已选：${_item!.title}'
                          : '支持 C 编号（可带 lcsc:）、型号、名称或参数；也可用扫码或器件库选择。',
                      onSelected: _selectSuggestion,
                      onQueryChanged: _releaseSuggestion,
                      onFetchRequested: _startFetch,
                    ),
                    if (_fetch.busy || _fetch.status != null)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: _fetch.status == null
                            ? const CatalogFetchRunning()
                            : CatalogFetchPanel(
                                status: _fetch.status!,
                                onChoose: (candidate) => unawaited(
                                  _fetch.chooseCandidate(candidate),
                                ),
                                onQueryAgain: _fetch.hasQueryableTask
                                    ? () => unawaited(_fetch.resume())
                                    : null,
                              ),
                      ),
                    if (_item != null || _newMaterial != null)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(
                          _item != null ? Icons.memory : Icons.fiber_new,
                        ),
                        title: Text(
                          _item?.title ??
                              _newMaterial?['name']?.toString() ??
                              '已选元器件',
                        ),
                        subtitle: Text(
                          _loadingArchives
                              ? '已选中，正在读取内部档案…'
                              : _item != null
                              ? '核对型号和规格后制袋'
                              : '新建器件资料（随袋码一起创建）',
                        ),
                        trailing: IconButton(
                          tooltip: '清除选择',
                          onPressed: _busy || attempt != null
                              ? null
                              : _clearItem,
                          icon: const Icon(Icons.close),
                        ),
                      ),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Wrap(
                        spacing: 8,
                        children: <Widget>[
                          TextButton(
                            onPressed: _busy || attempt != null
                                ? null
                                : _pickItem,
                            child: const Text('从器件库选择'),
                          ),
                          TextButton(
                            onPressed: _busy || attempt != null
                                ? null
                                : _newItem,
                            child: const Text('资料库没有？新建器件'),
                          ),
                        ],
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
                    if (_ambiguousArchive)
                      Padding(
                        padding: const EdgeInsets.only(top: 8),
                        child: Text(
                          '此编号对应多个本地档案，请先选择本次制袋的档案。',
                          style: theme.textTheme.bodySmall,
                        ),
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
                      onPressed: _busy || _ambiguousArchive || _loadingArchives
                          ? null
                          : _create,
                      icon: const Icon(Icons.add),
                      label: Text(attempt == null ? '生成袋码并加入待打印' : '重试生成袋码'),
                    ),
                    const SizedBox(height: 8),
                    const Text('此步骤仅创建待入库记录，不增加库存。'),
                  ]),
                  Text('待入库与打印', style: theme.textTheme.titleLarge),
                  const SizedBox(height: 8),
                  LayoutBuilder(
                    builder: (context, constraints) {
                      final search = TextField(
                        controller: _queueSearch,
                        enabled: !_busy,
                        onChanged: (_) {
                          setState(() {});
                          _scheduleQueueReload();
                        },
                        decoration: InputDecoration(
                          isDense: true,
                          labelText: '筛选队列',
                          hintText: '袋码 / 名称 / 型号 / 封装 / SN',
                          prefixIcon: const Icon(Icons.search),
                          suffixIcon: _queueSearch.text.isEmpty
                              ? null
                              : IconButton(
                                  tooltip: '清空',
                                  icon: const Icon(Icons.clear),
                                  onPressed: () {
                                    setState(_queueSearch.clear);
                                    _scheduleQueueReload();
                                  },
                                ),
                          border: const OutlineInputBorder(),
                        ),
                      );
                      final state = DropdownButtonFormField<String>(
                        initialValue: _stateFilter,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: '记录状态',
                          isDense: true,
                        ),
                        onChanged: _busy
                            ? null
                            : (value) {
                                if (value == null) return;
                                setState(() => _stateFilter = value);
                                _run(_reload);
                              },
                        items: const <DropdownMenuItem<String>>[
                          DropdownMenuItem(
                            value: 'pending',
                            child: Text('待入库'),
                          ),
                          DropdownMenuItem(value: 'done', child: Text('已入库')),
                          DropdownMenuItem(
                            value: 'cancelled',
                            child: Text('已取消'),
                          ),
                          DropdownMenuItem(value: 'all', child: Text('全部')),
                        ],
                      );
                      if (constraints.maxWidth < 520) {
                        return Column(
                          children: [search, const SizedBox(height: 12), state],
                        );
                      }
                      return Row(
                        children: [
                          Expanded(child: search),
                          const SizedBox(width: 12),
                          SizedBox(width: 160, child: state),
                        ],
                      );
                    },
                  ),
                  const SizedBox(height: 12),
                  if (_loaded && _records.isEmpty)
                    _section([
                      Text(
                        _queueSearch.text.trim().isEmpty &&
                                _stateFilter == 'pending'
                            ? '还没有待入库袋。选择器件后，生成第一批标签。'
                            : '没有匹配的袋。换个关键词或状态再试。',
                      ),
                    ]),
                  for (final record in _records)
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
                  // ---- step 1 close-out ----------------------------------
                  //
                  // This step used to END at the print button: nothing told the
                  // operator the step was done, and nothing led to the next one,
                  // so "制袋贴标" had no finish line (the reported "没有完成按钮").
                  // The two buttons below are that finish line: print, then go
                  // receive the bags you just labelled.
                  _section([
                    Text('第 1 步 · 制袋贴标', style: theme.textTheme.titleMedium),
                    const SizedBox(height: 6),
                    Text(
                      selectedCount == 0
                          ? '队列里还没有勾选要打印的袋。生成袋码后，在每一条上勾选「加入待打印」。'
                          : '已选 $selectedCount 袋。打印后把标签贴到对应实物袋上，'
                                '再到「扫码上架」逐袋核对入库。',
                      style: theme.textTheme.bodySmall,
                    ),
                    const SizedBox(height: 12),
                    FilledButton.icon(
                      onPressed:
                          _busy || selectedCount == 0 || selectedCount > 200
                          ? null
                          : _print,
                      icon: const Icon(Icons.print_outlined),
                      label: Text('预览并打印（$selectedCount 袋）'),
                    ),
                    const SizedBox(height: 8),
                    OutlinedButton.icon(
                      onPressed: _busy
                          ? null
                          : () => setState(() {
                                _tab = 1;
                                _resolved = null;
                                _recommendations = [];
                                _locationId = null;
                                _scanCycle++;
                              }),
                      icon: const Icon(Icons.arrow_forward),
                      label: const Text('完成贴标，进入「扫码上架」'),
                    ),
                  ]),
                ] else ...[
                  _section([
                    // ---- step 1: the shelf (scanned ONCE) -------------------
                    if (_putawayLocationId == null) ...[
                      const Text('第 1 步 · 扫描库位码'),
                      const SizedBox(height: 6),
                      Text(
                        '先扫货架上的库位二维码，选定这次入库放到哪里。'
                        '选定后可以连续扫袋码，不用再扫库位。',
                        style: theme.textTheme.bodySmall,
                      ),
                      const SizedBox(height: 10),
                    ] else ...[
                      Row(
                        children: <Widget>[
                          Icon(Icons.location_on,
                              size: 18, color: theme.colorScheme.primary),
                          const SizedBox(width: 6),
                          Expanded(
                            child: Text(
                              '入库库位：$_putawayLocationLabel',
                              style: theme.textTheme.titleSmall,
                            ),
                          ),
                          TextButton(
                            onPressed: _busy || attempt != null
                                ? null
                                : () => setState(() {
                                      _putawayLocationId = null;
                                      _putawayLocationLabel = '';
                                      _locationId = null;
                                      _scan.clear();
                                      _scanCycle++;
                                    }),
                            child: const Text('换库位'),
                          ),
                        ],
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '继续扫描袋码即可，每袋确认后自动清空，直到这个库位录完。',
                        style: theme.textTheme.bodySmall,
                      ),
                      const SizedBox(height: 10),
                    ],
                    ScanInputField(
                      key: ValueKey(_scanCycle),
                      controller: _scan,
                      enabled: !_busy && attempt == null,
                      label: _putawayLocationId == null
                          ? '扫描库位码（如 LABL:K000004）'
                          : '扫描袋追溯码',
                      onSubmit: _handleScan,
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
                                : (value) => setState(() {
                                      _locationId = value;
                                      // Picking from the list starts the same
                                      // sticky session a shelf scan does, so the
                                      // next bag does not ask again.
                                      _putawayLocationId = value;
                                      _putawayLocationLabel = items
                                          .where((l) => l.id == value)
                                          .map((l) => l.display)
                                          .join();
                                    }),
                          ),
                        ),
                        // No second "scan a location" field here any more: the
                        // shelf is chosen once, at the top of this tab. A
                        // per-bag location scan was what made the operator
                        // re-scan the shelf for every bag.
                        if (_putawayLocationId == null) ...[
                          const SizedBox(height: 8),
                          Text(
                            '还没有选定库位：请在上方扫描库位码，或从上面的列表里选一个。',
                            style: theme.textTheme.bodySmall
                                ?.copyWith(color: theme.colorScheme.error),
                          ),
                        ],
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
