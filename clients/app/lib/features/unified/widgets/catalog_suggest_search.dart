import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/lab_api_exception.dart';
import '../models/catalog_query.dart';
import '../models/identity.dart';
import '../models/unified_item.dart';
import '../providers/lab_errors.dart';
import '../providers/unified_providers.dart';

/// Search term sent to '/lab/api/catalog/search' for one raw field value.
///
/// The receipt screen doubles as a scan target, so the same field may receive a
/// bag/location payload or an 'lcsc:' prefixed code. Neither prefix belongs in a
/// catalog query: 'LABB:'/'LABL:' payloads are unwrapped (the server resolves
/// those through the scan path, not here) and 'lcsc:C123' becomes 'C123'.
/// Anything that is not a usable C-code stays exactly as typed, because the
/// operator may be searching a model number or a name.
String catalogSuggestTerm(String raw) {
  final folded = toHalfWidth(raw).trim();
  // 'LABB:'/'LABL:' is a scan payload. The scan field resolves it through the
  // server; the suggestion query would only answer "no match" and, worse, could
  // commit whatever the trace code happens to collide with.
  if (RegExp(r'^LAB[BL]\s*:', caseSensitive: false).hasMatch(folded)) return '';
  var text = unwrapPayload(folded).trim();
  text = text.replaceFirst(RegExp(r'^lcsc\s*:\s*', caseSensitive: false), '');
  text = text.trim();
  final code = normalizeCatalogCode(text);
  if (isUsableCatalogCode(code)) return code;
  return text;
}

/// One suggestion row: every visible variant of the SAME identity, grouped.
///
/// A C number must present its local archives and its supplier row together.
/// Grouping happens client-side as well because the server may return a local
/// card ('lab:*') and a catalog card for the same part in the same page, or two
/// rows carrying the same 'catalog_code'.
///
/// Two invariants are enforced here, not in the UI:
///   * local stock is 'lab_quantity' only - [catalogStock] (mall stock) is a
///     separate number and is labelled as supplier stock;
///   * displayed text never contains the internal 'lcsc:' / 'lab:' prefixes.
class CatalogSuggestionGroup {
  CatalogSuggestionGroup(this.items) : assert(items.isNotEmpty, 'empty group');

  /// The same-identity variants, local archive first.
  final List<UnifiedItem> items;

  /// The variant a selection commits: the local one when it exists.
  UnifiedItem get primary => items.first;

  late final String code = () {
    for (final item in items) {
      final value = displayCatalogCode(item.catalogCode);
      if (value.isNotEmpty) return value;
    }
    return '';
  }();

  late final String title = () {
    for (final item in items) {
      if (item.name.trim().isNotEmpty) return item.name.trim();
    }
    for (final item in items) {
      if (item.mpn.trim().isNotEmpty) return item.mpn.trim();
    }
    if (code.isNotEmpty) return code;
    return '本地物料';
  }();

  /// Model / package / brand, never a bare identity prefix.
  late final String meta = () {
    final parts = <String>[];
    final model = _firstNonEmpty((item) => item.mpn.trim());
    final package = _firstNonEmpty((item) => item.packageName.trim());
    final brand = _firstNonEmpty((item) => item.brand.trim());
    if (model.isNotEmpty && model != title) parts.add('型号 $model');
    if (package.isNotEmpty) parts.add('封装 $package');
    if (brand.isNotEmpty) parts.add(brand);
    return parts.join(' · ');
  }();

  /// Union of local archives behind every variant of this identity.
  late final Set<int> templateIds = {
    for (final item in items) ...item.labTemplateIds,
  };

  late final Set<String> snCodes = {
    for (final item in items)
      for (final sn in item.snCodes)
        if (sn.trim().isNotEmpty) sn.trim(),
  };

  late final int archiveCount = () {
    var count = templateIds.length;
    // An archive identified only by its SN still counts once.
    if (count == 0) count = snCodes.length;
    return count;
  }();

  /// Local on-hand quantity: the largest variant, NEVER mall stock.
  late final double labQuantity = items
      .map((item) => item.labQuantity)
      .fold<double>(0, math.max);

  late final bool hasLocalStock = labQuantity > 0;

  /// Mall stock, informational only, null when no variant carries it.
  late final double? catalogStock = () {
    double? value;
    for (final item in items) {
      final stock = item.catalogStock;
      if (stock == null) continue;
      value = value == null ? stock : math.max(value, stock);
    }
    return value;
  }();

  bool get hasLocalArchives => archiveCount > 0;

  /// Text written back into the field after a pick (the code when there is one).
  String get displayLabel => code.isNotEmpty ? code : title;

  /// Badges in operator vocabulary: local state first, supplier state last.
  List<String> get badges {
    final local = formatSuggestionQuantity(labQuantity);
    final supplier = catalogStock == null
        ? ''
        : formatSuggestionQuantity(catalogStock!);
    return <String>[
      hasLocalStock ? '本地库存 $local' : '本地无库存',
      hasLocalArchives ? '已有档案 $archiveCount 个' : '暂无档案',
      if (catalogStock != null) '供货 $supplier（非本地库存）',
    ];
  }

  /// Screen-reader label for one row.
  String get semanticsLabel => <String>[
    if (code.isNotEmpty) code,
    title,
    if (meta.isNotEmpty) meta,
    ...badges,
  ].join('，');

  String _firstNonEmpty(String Function(UnifiedItem) read) {
    for (final item in items) {
      final value = read(item);
      if (value.isNotEmpty) return value;
    }
    return '';
  }
}

/// Formats a quantity without a trailing '.0' (operator-facing text).
String formatSuggestionQuantity(double value) => value == value.roundToDouble()
    ? value.toInt().toString()
    : value.toStringAsFixed(2);

/// Groups [items] by human identity, local-first, capped at [limit].
///
/// Ordering rules (mirroring the verified web combobox):
///   * a group with a local archive ranks above one without;
///   * within a group the local archive variant is the primary one;
///   * in-stock before out-of-stock, then the larger local quantity.
List<CatalogSuggestionGroup> groupCatalogSuggestions(
  List<UnifiedItem> items, {
  int limit = 8,
}) {
  final byIdentity = <String, List<UnifiedItem>>{};
  for (final item in items) {
    final code = displayCatalogCode(item.catalogCode);
    final key = code.isNotEmpty ? 'code:$code' : 'key:${item.itemKey}';
    byIdentity.putIfAbsent(key, () => <UnifiedItem>[]).add(item);
  }
  final groups = byIdentity.values.map((variants) {
    variants.sort((a, b) {
      int rank(UnifiedItem item) =>
          (item.hasLocalArchives ? 2 : 0) +
          (item.hasStock || item.labQuantity > 0 ? 1 : 0);
      final byRank = rank(b).compareTo(rank(a));
      if (byRank != 0) return byRank;
      final byQuantity = b.labQuantity.compareTo(a.labQuantity);
      if (byQuantity != 0) return byQuantity;
      return a.itemKey.compareTo(b.itemKey);
    });
    return CatalogSuggestionGroup(variants);
  }).toList();

  groups.sort((a, b) {
    final byArchive = (b.hasLocalArchives ? 1 : 0).compareTo(
      a.hasLocalArchives ? 1 : 0,
    );
    if (byArchive != 0) return byArchive;
    final byStock = (b.hasLocalStock ? 1 : 0).compareTo(
      a.hasLocalStock ? 1 : 0,
    );
    if (byStock != 0) return byStock;
    final byQuantity = b.labQuantity.compareTo(a.labQuantity);
    if (byQuantity != 0) return byQuantity;
    return a.displayLabel.compareTo(b.displayLabel);
  });
  return groups.take(limit).toList(growable: false);
}

/// Inline, server-searched component suggestions for a receipt form.
///
/// Replaces a blocking "pick a component" dialog with a combobox that behaves
/// like the verified web one:
///   * ~250 ms debounce, an IMMEDIATE "正在检索" panel so typing never feels
///     dead, and at most one in-flight request that matters - every keystroke
///     bumps a sequence number, so a stale response is dropped instead of
///     overwriting newer input;
///   * IME-safe: no request fires while a composition is in progress;
///   * explicit loading / empty / error (with a real retry) states, and no
///     invented or cached results;
///   * Up/Down/Enter/Escape/Tab navigation, an outside-tap and blur close that
///     a late response cannot undo, and a panel rendered in the OVERLAY (never
///     clipped by the enclosing ListView);
///   * selecting a row commits [UnifiedItem.itemKey] and its archive ids as sent
///     by the server; nothing here writes inventory.
///
/// [onQueryChanged] fires for every real edit (not for the text written back
/// after a pick), letting the screen invalidate a previous selection before a
/// new one exists.
class CatalogSuggestField extends ConsumerStatefulWidget {
  const CatalogSuggestField({
    super.key,
    required this.onSelected,
    this.onQueryChanged,
    this.enabled = true,
    this.label = '搜索并选择器件',
    this.hintText = 'C 编号 / 型号 / 名称',
    this.helperText,
    this.autofocus = false,
    this.minQueryLength = 2,
    this.debounce = const Duration(milliseconds: 250),
    this.limit = 8,
  });

  final ValueChanged<UnifiedItem> onSelected;

  /// Called with the raw text on every operator edit, before searching.
  final ValueChanged<String>? onQueryChanged;

  /// When false the field is read-only and the panel closes (submission lock).
  final bool enabled;

  final String label;
  final String? hintText;
  final String? helperText;
  final bool autofocus;
  final int minQueryLength;
  final Duration debounce;
  final int limit;

  @override
  ConsumerState<CatalogSuggestField> createState() =>
      _CatalogSuggestFieldState();
}

enum _SuggestStatus { idle, loading, results, empty, error }

class _CatalogSuggestFieldState extends ConsumerState<CatalogSuggestField> {
  final TextEditingController _controller = TextEditingController();
  final FocusNode _focusNode = FocusNode(debugLabel: 'catalog-suggest');
  final LayerLink _link = LayerLink();
  final OverlayPortalController _overlay = OverlayPortalController();
  final GlobalKey _fieldKey = GlobalKey();
  final Object _tapGroup = Object();

  Timer? _debounce;

  /// Monotonic request/selection generation. Incremented by every edit, clear,
  /// close that invalidates, pick and disable, so late callbacks can compare.
  int _seq = 0;

  _SuggestStatus _status = _SuggestStatus.idle;
  List<CatalogSuggestionGroup> _groups = const <CatalogSuggestionGroup>[];
  List<GlobalKey> _rowKeys = const <GlobalKey>[];
  int? _active;
  bool _panelOpen = false;
  bool _openUp = false;
  double _anchorWidth = 320;
  double _panelMaxHeight = 320;
  String? _errorCode;
  String? _errorMessage;

  /// Suppresses the parent-facing query callback when the field writes text
  /// back itself after a pick (that write is not a new search).
  bool _writingText = false;

  @override
  void initState() {
    super.initState();
    _focusNode.addListener(_onFocusChanged);
    _focusNode.onKeyEvent = _onKeyEvent;
  }

  @override
  void didUpdateWidget(CatalogSuggestField oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!widget.enabled && oldWidget.enabled) {
      // didUpdateWidget runs mid-build: mark the panel closed for this frame and
      // hide the overlay once the frame is done, so a submission lock can never
      // trip "setState() called during build".
      _debounce?.cancel();
      _seq++;
      _panelOpen = false;
      _active = null;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && !widget.enabled) _overlay.hide();
      });
    }
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _focusNode
      ..removeListener(_onFocusChanged)
      ..dispose();
    _controller.dispose();
    super.dispose();
  }

  void _onFocusChanged() {
    if (_focusNode.hasFocus || !_panelOpen) return;
    // Close on blur, but only after this frame: tapping a suggestion moves the
    // primary focus away without requesting it, and that tap must still commit.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_panelOpen || _focusNode.hasFocus) return;
      _closePanel(invalidate: true);
    });
  }

  KeyEventResult _onKeyEvent(FocusNode node, KeyEvent event) {
    if (event is KeyUpEvent) return KeyEventResult.ignored;
    final key = event.logicalKey;
    if (key == LogicalKeyboardKey.escape) {
      if (!_panelOpen) return KeyEventResult.ignored;
      _closePanel(invalidate: true);
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.tab) {
      // Let traversal continue; just never leave a stale panel behind.
      if (_panelOpen) _closePanel(invalidate: true);
      return KeyEventResult.ignored;
    }
    if (!_panelOpen || _status != _SuggestStatus.results || _groups.isEmpty) {
      return KeyEventResult.ignored;
    }
    if (key == LogicalKeyboardKey.arrowDown) {
      _moveActive(1);
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.arrowUp) {
      _moveActive(-1);
      return KeyEventResult.handled;
    }
    if (key == LogicalKeyboardKey.enter ||
        key == LogicalKeyboardKey.numpadEnter) {
      final index = _active;
      if (index == null) return KeyEventResult.ignored;
      _commit(index);
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  void _moveActive(int delta) {
    final count = _groups.length;
    if (count == 0) return;
    final current = _active;
    final next = current == null
        ? (delta > 0 ? 0 : count - 1)
        : (current + delta).clamp(0, count - 1);
    setState(() => _active = next);
    final rowContext = next < _rowKeys.length
        ? _rowKeys[next].currentContext
        : null;
    if (rowContext != null && rowContext.mounted) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted) return;
        final context = next < _rowKeys.length
            ? _rowKeys[next].currentContext
            : null;
        if (context != null && context.mounted) {
          Scrollable.ensureVisible(
            context,
            alignmentPolicy: ScrollPositionAlignmentPolicy.keepVisibleAtEnd,
          );
        }
      });
    }
  }

  void _onChanged(String raw) {
    if (_writingText) return;
    _seq++;
    _debounce?.cancel();
    widget.onQueryChanged?.call(raw);
    if (!mounted) return;
    if (!widget.enabled || _controller.value.composing.isValid) {
      _resetResults();
      _closePanel(invalidate: false);
      return;
    }
    final term = catalogSuggestTerm(raw);
    if (term.runes.length < widget.minQueryLength) {
      _resetResults();
      _closePanel(invalidate: false);
      return;
    }
    final seq = _seq;
    setState(() {
      _resetResults();
      _status = _SuggestStatus.loading;
    });
    _openPanel();
    _debounce = Timer(widget.debounce, () => _search(seq, term));
  }

  Future<void> _search(int seq, String term) async {
    if (!mounted || seq != _seq || !widget.enabled) return;
    try {
      final page = await ref
          .read(labApiProvider)
          .search(CatalogQuery(text: term), limit: widget.limit);
      if (!mounted || seq != _seq || !widget.enabled) return;
      final groups = groupCatalogSuggestions(page.items, limit: widget.limit);
      setState(() {
        _groups = groups;
        _rowKeys = List<GlobalKey>.generate(groups.length, (_) => GlobalKey());
        _active = null;
        _errorCode = null;
        _errorMessage = null;
        _status = groups.isEmpty
            ? _SuggestStatus.empty
            : _SuggestStatus.results;
      });
      _openPanel();
    } on LabApiException catch (error) {
      if (!mounted || seq != _seq || !widget.enabled) return;
      setState(() {
        _resetResults();
        _status = _SuggestStatus.error;
        _errorCode = error.code;
        _errorMessage = error.message.trim().isNotEmpty
            ? error.message
            : describeLabError(error);
      });
      _openPanel();
    } catch (error) {
      if (!mounted || seq != _seq || !widget.enabled) return;
      setState(() {
        _resetResults();
        _status = _SuggestStatus.error;
        _errorCode = null;
        _errorMessage = describeLabError(error);
      });
      _openPanel();
    }
  }

  void _retry() {
    final term = catalogSuggestTerm(_controller.text);
    if (!widget.enabled || term.runes.length < widget.minQueryLength) return;
    final seq = ++_seq;
    setState(() {
      _resetResults();
      _status = _SuggestStatus.loading;
    });
    _openPanel();
    _search(seq, term);
  }

  void _clear() {
    if (!widget.enabled) return;
    _controller.clear();
    _onChanged('');
    _focusNode.requestFocus();
  }

  void _commit(int index) {
    if (index < 0 || index >= _groups.length) return;
    final group = _groups[index];
    _seq++;
    _debounce?.cancel();
    _closePanel(invalidate: false);
    _writingText = true;
    final label = group.displayLabel;
    _controller.value = TextEditingValue(
      text: label,
      selection: TextSelection.collapsed(offset: label.length),
    );
    _writingText = false;
    setState(_resetResults);
    _focusNode.requestFocus();
    widget.onSelected(group.primary);
  }

  void _resetResults() {
    _groups = const <CatalogSuggestionGroup>[];
    _rowKeys = const <GlobalKey>[];
    _active = null;
    _errorCode = null;
    _errorMessage = null;
    if (_status != _SuggestStatus.loading) _status = _SuggestStatus.idle;
  }

  /// Measures the field so the panel can flip up and never overflow the screen.
  void _measureAnchor() {
    final box = _fieldKey.currentContext?.findRenderObject();
    final size = MediaQuery.maybeSizeOf(context) ?? const Size(400, 800);
    if (box is! RenderBox || !box.hasSize) {
      _anchorWidth = size.width - 32;
      _openUp = false;
      _panelMaxHeight = 320;
      return;
    }
    final origin = box.localToGlobal(Offset.zero);
    _anchorWidth = box.size.width;
    final below = size.height - (origin.dy + box.size.height);
    final above = origin.dy;
    _openUp = below < 240 && above > below;
    final available = _openUp ? above : below;
    _panelMaxHeight = math.min(360.0, math.max(160.0, available - 8));
  }

  void _openPanel() {
    if (!mounted || !widget.enabled) return;
    _measureAnchor();
    if (!_panelOpen) {
      _panelOpen = true;
      _overlay.show();
    }
    setState(() {});
  }

  void _closePanel({required bool invalidate}) {
    _debounce?.cancel();
    if (invalidate) _seq++;
    if (!mounted) return;
    if (!_panelOpen) return;
    setState(() {
      _panelOpen = false;
      _active = null;
    });
    _overlay.hide();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final hasText = _controller.text.isNotEmpty;

    return OverlayPortal(
      controller: _overlay,
      overlayChildBuilder: (overlayContext) => _buildPanel(overlayContext),
      child: TapRegion(
        groupId: _tapGroup,
        onTapOutside: (event) {
          if (_panelOpen) _closePanel(invalidate: true);
        },
        child: CompositedTransformTarget(
          link: _link,
          child: TextField(
            key: _fieldKey,
            controller: _controller,
            focusNode: _focusNode,
            enabled: widget.enabled,
            readOnly: !widget.enabled,
            autofocus: widget.autofocus,
            textInputAction: TextInputAction.search,
            onChanged: _onChanged,
            onSubmitted: (_) {
              final index = _active;
              if (index != null && _panelOpen) _commit(index);
            },
            decoration: InputDecoration(
              labelText: widget.label,
              hintText: widget.hintText,
              helperText: widget.helperText,
              helperMaxLines: 2,
              prefixIcon: const Icon(Icons.search),
              filled: true,
              fillColor: scheme.surfaceContainerHighest,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: BorderSide(color: scheme.outlineVariant),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: BorderSide(color: scheme.outlineVariant),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(12),
                borderSide: BorderSide(color: scheme.primary, width: 2),
              ),
              suffixIcon: hasText
                  ? IconButton(
                      tooltip: '清空搜索',
                      onPressed: widget.enabled ? _clear : null,
                      icon: const Icon(Icons.close),
                    )
                  : null,
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildPanel(BuildContext overlayContext) {
    if (!_panelOpen || _status == _SuggestStatus.idle) {
      return const SizedBox.shrink();
    }
    final theme = Theme.of(overlayContext);
    final scheme = theme.colorScheme;
    final radius = BorderRadius.circular(12);
    final panel = Material(
      elevation: 8,
      borderRadius: radius,
      clipBehavior: Clip.antiAlias,
      color: scheme.surfaceContainerHigh,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          minWidth: _anchorWidth,
          maxWidth: _anchorWidth,
          maxHeight: _panelMaxHeight,
        ),
        child: SingleChildScrollView(
          primary: false,
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: _panelBody(theme),
        ),
      ),
    );

    final follower = CompositedTransformFollower(
      link: _link,
      showWhenUnlinked: false,
      targetAnchor: _openUp ? Alignment.topLeft : Alignment.bottomLeft,
      followerAnchor: _openUp ? Alignment.bottomLeft : Alignment.topLeft,
      offset: Offset(0, _openUp ? -4 : 4),
      child: TapRegion(groupId: _tapGroup, child: panel),
    );
    // No Semantics wrapper here: a semantics container around the follower
    // swallows the pointer route in widget tests (and can do so on device), so
    // the panel would paint but never receive taps. Rows carry their own labels.
    return Align(alignment: Alignment.topLeft, child: follower);
  }

  Widget _panelBody(ThemeData theme) {
    final scheme = theme.colorScheme;
    switch (_status) {
      case _SuggestStatus.idle:
        return const SizedBox.shrink();
      case _SuggestStatus.loading:
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Row(
            children: <Widget>[
              SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: scheme.primary,
                ),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text('正在检索器件资料…', style: theme.textTheme.bodyMedium),
              ),
            ],
          ),
        );
      case _SuggestStatus.empty:
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text('没有匹配的器件', style: theme.textTheme.titleSmall),
              const SizedBox(height: 4),
              Text('可以继续用编号 / SN 扫码，或新建器件。', style: theme.textTheme.bodySmall),
            ],
          ),
        );
      case _SuggestStatus.error:
        return Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Text(
                _errorCode != null && _errorCode!.isNotEmpty
                    ? '检索失败：$_errorCode'
                    : '检索失败',
                style: theme.textTheme.titleSmall?.copyWith(
                  color: scheme.error,
                ),
              ),
              if (_errorMessage != null &&
                  _errorMessage!.isNotEmpty) ...<Widget>[
                const SizedBox(height: 4),
                Text(_errorMessage!, style: theme.textTheme.bodySmall),
              ],
              const SizedBox(height: 4),
              TextButton.icon(
                onPressed: widget.enabled ? _retry : null,
                icon: const Icon(Icons.refresh, size: 18),
                label: const Text('重试检索'),
              ),
            ],
          ),
        );
      case _SuggestStatus.results:
        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            for (var index = 0; index < _groups.length; index++)
              _buildRow(theme, index),
          ],
        );
    }
  }

  Widget _buildRow(ThemeData theme, int index) {
    final group = _groups[index];
    final scheme = theme.colorScheme;
    final active = index == _active;
    return Semantics(
      button: true,
      selected: active,
      label: group.semanticsLabel,
      child: InkWell(
        key: index < _rowKeys.length ? _rowKeys[index] : null,
        canRequestFocus: false,
        onTap: () => _commit(index),
        onHover: (hovering) {
          if (hovering && _active != index) {
            setState(() => _active = index);
          }
        },
        child: Container(
          constraints: const BoxConstraints(minHeight: 48),
          color: active ? scheme.primaryContainer : null,
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              Row(
                children: <Widget>[
                  if (group.code.isNotEmpty) ...<Widget>[
                    Text(
                      group.code,
                      style: theme.textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(width: 8),
                  ],
                  Expanded(
                    child: Text(
                      group.title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodyMedium,
                    ),
                  ),
                ],
              ),
              if (group.meta.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text(
                    group.meta,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall,
                  ),
                ),
              Padding(
                padding: const EdgeInsets.only(top: 6),
                child: Wrap(
                  spacing: 6,
                  runSpacing: 4,
                  children: <Widget>[
                    for (final badge in group.badges)
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: scheme.surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(badge, style: theme.textTheme.labelSmall),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
