import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../widgets/lab_ui.dart';
import '../../unified/models/detail_models.dart';
import '../../unified/models/unified_item.dart';
import '../../unified/providers/inventory_providers.dart';
import '../../unified/widgets/status_views.dart';
import '../warehouse_routes.dart';

/// 仓位速览: the real location hierarchy, with what is physically in each one.
///
/// The list is the whole point of the section - before this the only way to see
/// a location's contents was to open a component's detail page and read its
/// distribution, i.e. you had to know WHAT you were looking for before you could
/// ask WHERE it was. Here the question is asked the other way round.
///
/// Figures come from `locations(with_stats: true)`: `bag_count` counts bags with
/// a non-zero quantity at that exact location, `quantity` sums `stock.quant`.
/// A location that was never counted shows `—`, never `0`.
///
/// The hierarchy comes from the same rows' `parent_id` plus the `view` folders
/// the server returns in `ancestors`. A `view` folder groups real locations and
/// is never enterable, never printed and never counted. When an older host
/// answers without `parent_id` the screen falls back to the flat list it used
/// to show rather than inventing a hierarchy.
class LocationOverviewScreen extends ConsumerStatefulWidget {
  const LocationOverviewScreen({super.key});

  @override
  ConsumerState<LocationOverviewScreen> createState() =>
      _LocationOverviewScreenState();
}

class _LocationOverviewScreenState
    extends ConsumerState<LocationOverviewScreen> {
  /// Expanded branch ids. Empty until the first answer arrives, then the first
  /// two levels open so the operator sees the real shape without clicking.
  final Set<int> _expanded = <int>{};
  bool _seeded = false;

  /// A node to reveal (its ancestors expand) after the next reload - used after
  /// creating or moving a location so the operator lands where the change is.
  int? _revealId;

  String _query = '';

  @override
  Widget build(BuildContext context) {
    final tree = ref.watch(inventoryLocationTreeProvider);
    final bootstrap = ref.watch(inventoryBootstrapProvider);
    final permissions = bootstrap.valueOrNull?.permissions;
    // Write actions appear ONLY once the server has said this account manages
    // locations. While permissions are loading, unknown, signed out or offline
    // the screen stays read-only - the server would reject the write anyway.
    final canManage =
        permissions != null &&
        permissions.known &&
        permissions.canCreateLocation;
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: Colors.transparent,
      appBar: LabAppBar(
        title: const Text('仓位速览'),
        actions: <Widget>[
          if (canManage)
            IconButton(
              key: const ValueKey('location-create'),
              tooltip: '新建库位',
              onPressed: () => _createLocation(context, tree.valueOrNull),
              icon: const Icon(Icons.add_location_alt_outlined),
            ),
          IconButton(
            key: const ValueKey('location-refresh'),
            tooltip: '刷新',
            onPressed: () => ref.invalidate(inventoryLocationTreeProvider),
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: tree.when(
        loading: () => const LoadingView(label: '正在读取仓位…'),
        error: (error, _) => ErrorView(
          message: '仓位加载失败：$error',
          onRetry: () => ref.invalidate(inventoryLocationTreeProvider),
        ),
        data: (data) {
          if (data.isEmpty) {
            return EmptyView(
              title: '还没有仓位',
              subtitle: canManage
                  ? '新建一个库位后会生成库码，可打印库位标签贴到货架。'
                  : '请联系库存管理员创建库位。',
              icon: Icons.warehouse_outlined,
              action: canManage
                  ? FilledButton.tonalIcon(
                      onPressed: () => _createLocation(context, data),
                      icon: const Icon(Icons.add_location_alt_outlined),
                      label: const Text('新建库位'),
                    )
                  : null,
            );
          }

          final roots = _buildTree(data);
          _seedExpansion(roots);

          // Totals across every internal location exactly once. View folders are
          // not counted: they hold no stock and would inflate 仓位数.
          var bags = 0;
          var quantity = 0.0;
          for (final row in data.locations) {
            bags += row.bagCount ?? 0;
            quantity += row.quantity ?? 0;
          }

          final searching = _query.trim().isNotEmpty;
          final visible = _visibleRows(roots, searching);

          return Column(
            children: <Widget>[
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
                child: TextField(
                  key: const ValueKey('location-search'),
                  decoration: const InputDecoration(
                    isDense: true,
                    prefixIcon: Icon(Icons.search, size: 20),
                    hintText: '按库码、名称或路径搜索',
                    border: OutlineInputBorder(),
                  ),
                  onChanged: (value) => setState(() => _query = value),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 4),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    '${data.locations.length} 个库位 · $bags 袋 · '
                    '在库 ${UnifiedItem.formatQuantity(quantity)}',
                    style: theme.textTheme.labelSmall,
                  ),
                ),
              ),
              Expanded(
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
                  children: <Widget>[
                    for (final entry in visible)
                      _TreeRow(
                        key: ValueKey('location-row-${entry.node.loc.id}'),
                        node: entry.node,
                        depth: entry.depth,
                        expanded:
                            searching ||
                            (entry.node.loc.id != null &&
                                _expanded.contains(entry.node.loc.id)),
                        canManage: canManage,
                        onOpen: entry.node.loc.hasId && !entry.node.loc.isView
                            ? () => context.push(
                                WarehouseRoutes.locationContents(
                                  entry.node.loc.id!,
                                ),
                              )
                            : null,
                        onToggle:
                            entry.node.children.isEmpty ||
                                entry.node.loc.id == null
                            ? null
                            : () => _toggle(entry.node.loc.id!),
                        onMove: canManage && entry.node.loc.hasId
                            ? () => _moveLocation(context, data, entry.node.loc)
                            : null,
                      ),
                    const SizedBox(height: 8),
                    Text(
                      '袋数只算本库位（不含子库位）；在库数量按 stock.quant 合计。'
                      '目录节点只用于分组，不参与库存统计。',
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  void _seedExpansion(List<_TreeNode> roots) {
    final reveal = _revealId;
    if (reveal != null) {
      final path = _ancestorsOf(roots, reveal);
      if (path.isNotEmpty) {
        for (final node in path) {
          if (node.loc.id != null) _expanded.add(node.loc.id!);
        }
        _revealId = null;
      }
    }
    if (_seeded) return;
    _seeded = true;
    void walk(List<_TreeNode> nodes, int depth) {
      for (final node in nodes) {
        if (node.children.isEmpty) continue;
        if (depth < 2) _expanded.add(node.loc.id!);
        walk(node.children, depth + 1);
      }
    }

    walk(roots, 0);
  }

  void _toggle(int id) {
    setState(() {
      if (!_expanded.remove(id)) _expanded.add(id);
    });
  }

  // ---------------------------------------------------------------- tree maths

  List<_TreeNode> _buildTree(LabLocationTree data) {
    final byId = <int, _TreeNode>{};
    for (final row in <LabStockLocation>[
      ...data.ancestors,
      ...data.locations,
    ]) {
      final id = row.id;
      if (id == null) continue;
      byId[id] = _TreeNode(loc: row);
    }
    final roots = <_TreeNode>[];
    for (final node in byId.values) {
      final parent = byId[node.loc.parentId];
      // A parent that is not in the payload (filtered out, wrong company) makes
      // this a root: dropping the row would silently hide real stock.
      if (parent != null && parent != node) {
        parent.children.add(node);
      } else {
        roots.add(node);
      }
    }
    void sortAll(List<_TreeNode> nodes) {
      nodes.sort((a, b) => _naturalCompare(a.loc.name, b.loc.name));
      for (final node in nodes) {
        sortAll(node.children);
      }
    }

    sortAll(roots);
    return roots;
  }

  /// `M(2,1)` sorts before `M(10,1)`, the way Odoo's own location order reads.
  static int _naturalCompare(String a, String b) {
    final splitA = a.split(RegExp(r'(\d+)'));
    final splitB = b.split(RegExp(r'(\d+)'));
    for (
      var index = 0;
      index < splitA.length && index < splitB.length;
      index++
    ) {
      final left = splitA[index];
      final right = splitB[index];
      if (left == right) continue;
      final leftNumber = int.tryParse(left);
      final rightNumber = int.tryParse(right);
      if (leftNumber != null && rightNumber != null) {
        return leftNumber.compareTo(rightNumber);
      }
      return left.compareTo(right);
    }
    return splitA.length.compareTo(splitB.length);
  }

  bool _matches(LabStockLocation row, String needle) {
    if (needle.isEmpty) return true;
    final haystack = '${row.code} ${row.name} ${row.path}'.toLowerCase();
    return haystack.contains(needle);
  }

  /// Rows to render: a node shows when every ancestor is expanded (or a search
  /// is running). During a search the node also shows when a DESCENDANT
  /// matches, and the ancestor chain keeps its context.
  List<_TreeEntry> _visibleRows(List<_TreeNode> roots, bool searching) {
    final needle = _query.trim().toLowerCase();
    final rows = <_TreeEntry>[];

    bool subtreeMatches(_TreeNode node) {
      if (node.loc.isView || _matches(node.loc, needle)) return true;
      return node.children.any(subtreeMatches);
    }

    void walk(List<_TreeNode> nodes, int depth, bool ancestorsOpen) {
      for (final node in nodes) {
        final id = node.loc.id;
        final show = searching
            ? (needle.isEmpty || subtreeMatches(node))
            : ancestorsOpen;
        if (show) {
          rows.add(_TreeEntry(node: node, depth: depth));
          final open = searching || (id != null && _expanded.contains(id));
          if (node.children.isNotEmpty && open) {
            walk(node.children, depth + 1, true);
          }
        }
      }
    }

    walk(roots, 0, true);
    return rows;
  }

  List<_TreeNode> _ancestorsOf(List<_TreeNode> roots, int id) {
    final path = <_TreeNode>[];
    bool walk(List<_TreeNode> nodes) {
      for (final node in nodes) {
        path.add(node);
        if (node.loc.id == id) return true;
        if (walk(node.children)) return true;
        path.removeLast();
      }
      return false;
    }

    return walk(roots) ? List<_TreeNode>.of(path) : const <_TreeNode>[];
  }

  // ------------------------------------------------------------------ actions

  Future<void> _createLocation(
    BuildContext context,
    LabLocationTree? data,
  ) async {
    final roots = data == null ? const <_TreeNode>[] : _buildTree(data);
    final created = await showDialog<LabStockLocation>(
      context: context,
      builder: (context) => _CreateLocationDialog(roots: roots),
    );
    if (created == null || !mounted) return;
    _revealId = created.parentId;
    if (created.parentId != null) _expanded.add(created.parentId!);
    ref.invalidate(inventoryLocationTreeProvider);
    ref.invalidate(inventoryLocationsProvider);
    ref.invalidate(inventoryLocationsWithStatsProvider);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('已创建库位 ${created.display}（库码 ${created.code}）')),
    );
  }

  Future<void> _moveLocation(
    BuildContext context,
    LabLocationTree data,
    LabStockLocation location,
  ) async {
    final roots = _buildTree(data);
    final moved = await showDialog<LabStockLocation>(
      context: context,
      builder: (context) =>
          _MoveLocationDialog(location: location, roots: roots),
    );
    if (moved == null || !mounted) return;
    _revealId = moved.id;
    if (moved.parentId != null) _expanded.add(moved.parentId!);
    ref.invalidate(inventoryLocationTreeProvider);
    ref.invalidate(inventoryLocationsProvider);
    ref.invalidate(inventoryLocationsWithStatsProvider);
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text('已移动至 ${moved.path}')));
  }
}

class _TreeNode {
  _TreeNode({required this.loc});

  final LabStockLocation loc;
  final List<_TreeNode> children = <_TreeNode>[];
}

class _TreeEntry {
  const _TreeEntry({required this.node, required this.depth});

  final _TreeNode node;
  final int depth;
}

class _TreeRow extends StatelessWidget {
  const _TreeRow({
    super.key,
    required this.node,
    required this.depth,
    required this.expanded,
    required this.canManage,
    required this.onOpen,
    required this.onToggle,
    required this.onMove,
  });

  final _TreeNode node;
  final int depth;
  final bool expanded;
  final bool canManage;
  final VoidCallback? onOpen;
  final VoidCallback? onToggle;
  final VoidCallback? onMove;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final row = node.loc;
    final expandable = node.children.isNotEmpty;

    return Padding(
      padding: EdgeInsets.only(left: depth * 16.0, bottom: 6),
      child: GlassPanel(
        child: InkWell(
          borderRadius: BorderRadius.circular(22),
          onTap: onOpen,
          onLongPress: onMove,
          child: Row(
            children: <Widget>[
              SizedBox(
                width: 40,
                child: expandable
                    ? IconButton(
                        key: ValueKey('location-toggle-${row.id}'),
                        tooltip: expanded ? '折叠' : '展开',
                        onPressed: onToggle,
                        icon: Icon(
                          expanded ? Icons.expand_more : Icons.chevron_right,
                          size: 20,
                        ),
                      )
                    : Icon(
                        row.isView
                            ? Icons.folder_outlined
                            : Icons.location_on_outlined,
                        size: 20,
                        color: theme.colorScheme.primary,
                      ),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 10),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Text(
                        row.isView ? row.name : row.display,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.titleSmall,
                      ),
                      if (!row.isView &&
                          row.path.isNotEmpty &&
                          row.path != row.name)
                        Text(
                          row.path,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: theme.textTheme.labelSmall,
                        ),
                    ],
                  ),
                ),
              ),
              if (!row.isView)
                Padding(
                  padding: const EdgeInsets.only(right: 6),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      Text(
                        row.hasStats ? '${row.bagCount ?? 0} 袋' : '— 袋',
                        style: theme.textTheme.labelMedium?.copyWith(
                          color: theme.colorScheme.onSurface,
                        ),
                      ),
                      Text(
                        row.quantity == null
                            ? '—'
                            : UnifiedItem.formatQuantity(row.quantity!),
                        style: theme.textTheme.labelSmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                ),
              if (canManage && onMove != null)
                IconButton(
                  key: ValueKey('location-move-${row.id}'),
                  tooltip: '更改上级',
                  onPressed: onMove,
                  icon: const Icon(Icons.drive_file_move_outline, size: 20),
                ),
              if (onOpen != null)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: Icon(
                    Icons.chevron_right,
                    size: 18,
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The candidate parents a move may be sent to: every branch node except the
/// location itself, its descendants and its current parent (choosing the
/// current parent would be a no-op the server cannot replay meaningfully).
List<_Candidate> _moveCandidates(
  List<_TreeNode> roots,
  LabStockLocation target,
) {
  final forbidden = <int>{if (target.id != null) target.id!};
  void collect(_TreeNode node) {
    for (final child in node.children) {
      if (child.loc.id != null) forbidden.add(child.loc.id!);
      collect(child);
    }
  }

  final targetNode = _findNode(roots, target.id);
  if (targetNode != null) collect(targetNode);

  final out = <_Candidate>[];
  void walk(List<_TreeNode> nodes, int depth) {
    for (final node in nodes) {
      final id = node.loc.id;
      if (id != null && !forbidden.contains(id) && id != target.parentId) {
        out.add(_Candidate(location: node.loc, depth: depth));
      }
      walk(node.children, depth + 1);
    }
  }

  walk(roots, 0);
  return out;
}

_TreeNode? _findNode(List<_TreeNode> nodes, int? id) {
  for (final node in nodes) {
    if (node.loc.id == id) return node;
    final found = _findNode(node.children, id);
    if (found != null) return found;
  }
  return null;
}

class _Candidate {
  const _Candidate({required this.location, required this.depth});

  final LabStockLocation location;
  final int depth;
}

/// Result-unknown transport failures: the server may or may not have written.
const _unknownOutcomeCodes = <String>{
  'NETWORK_ERROR',
  'TRANSPORT_ERROR',
  'TIMEOUT_AMBIGUOUS',
  'AMBIGUOUS',
};

bool _isUnknownOutcome(String? code) =>
    code != null && _unknownOutcomeCodes.contains(code);

class _CreateLocationDialog extends ConsumerStatefulWidget {
  const _CreateLocationDialog({required this.roots});

  final List<_TreeNode> roots;

  @override
  ConsumerState<_CreateLocationDialog> createState() =>
      _CreateLocationDialogState();
}

class _CreateLocationDialogState extends ConsumerState<_CreateLocationDialog> {
  final TextEditingController _name = TextEditingController();
  int? _parentId;
  String? _error;
  bool _unknown = false;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(locationCreateProvider);
    final candidates = <_Candidate>[];
    void walk(List<_TreeNode> nodes, int depth) {
      for (final node in nodes) {
        if (!node.loc.isView && node.loc.id != null) {
          candidates.add(_Candidate(location: node.loc, depth: depth));
        }
        walk(node.children, depth + 1);
      }
    }

    walk(widget.roots, 0);

    return AlertDialog(
      title: const Text('新建库位'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          TextField(
            key: const ValueKey('location-create-name'),
            controller: _name,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: '库位名称（如 R01）',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<int?>(
            key: const ValueKey('location-create-parent'),
            initialValue: _parentId,
            isExpanded: true,
            decoration: const InputDecoration(
              labelText: '上级库位',
              border: OutlineInputBorder(),
            ),
            items: <DropdownMenuItem<int?>>[
              const DropdownMenuItem<int?>(
                value: null,
                child: Text('（根级，无上级）'),
              ),
              for (final candidate in candidates)
                DropdownMenuItem<int?>(
                  value: candidate.location.id,
                  child: Text(
                    '${'　' * candidate.depth}${candidate.location.display}',
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
            ],
            onChanged: state.submitting
                ? null
                : (value) => setState(() {
                    _parentId = value;
                    _unknown = false;
                    _error = null;
                  }),
          ),
          if (_error != null) ...<Widget>[
            const SizedBox(height: 12),
            Text(
              _error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
        ],
      ),
      actions: <Widget>[
        TextButton(
          onPressed: state.submitting ? null : () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          key: const ValueKey('location-create-submit'),
          onPressed: state.submitting || _unknown ? null : _submit,
          child: Text(state.submitting ? '创建中…' : '创建库位'),
        ),
      ],
    );
  }

  Future<void> _submit() async {
    final name = _name.text.trim();
    if (name.isEmpty) {
      setState(() => _error = '请输入库位名称。');
      return;
    }
    final created = await ref
        .read(locationCreateProvider.notifier)
        .create(name: name, parentId: _parentId);
    if (!mounted) return;
    if (created != null) {
      Navigator.pop(context, created);
      return;
    }
    final state = ref.read(locationCreateProvider);
    final unknown = _isUnknownOutcome(state.errorCode);
    setState(() {
      _error = unknown
          ? '提交结果未知：请先关闭并核对库位列表，确认没有该库位后再新建。'
          : (state.error ?? '新建库位失败。');
      // Creating has no server-side replay contract: after an unknown outcome
      // the operator must verify the tree, never let the button create twice.
      _unknown = unknown;
    });
    if (unknown) {
      // Show the real tree so the operator can check whether it landed.
      ref.invalidate(inventoryLocationTreeProvider);
    }
  }
}

class _MoveLocationDialog extends ConsumerStatefulWidget {
  const _MoveLocationDialog({required this.location, required this.roots});

  final LabStockLocation location;
  final List<_TreeNode> roots;

  @override
  ConsumerState<_MoveLocationDialog> createState() =>
      _MoveLocationDialogState();
}

class _MoveLocationDialogState extends ConsumerState<_MoveLocationDialog> {
  int? _parentId;
  bool _picked = false;

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(locationMoveProvider);
    final candidates = _moveCandidates(widget.roots, widget.location);
    final unresolved = state.attempt != null && state.error != null;

    return AlertDialog(
      title: const Text('更改上级'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            '当前：${widget.location.path}',
            style: Theme.of(context).textTheme.labelMedium,
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<int?>(
            key: const ValueKey('location-move-parent'),
            initialValue: _parentId,
            isExpanded: true,
            decoration: const InputDecoration(
              labelText: '新上级库位',
              border: OutlineInputBorder(),
            ),
            items: <DropdownMenuItem<int?>>[
              if (widget.location.parentId != null)
                const DropdownMenuItem<int?>(
                  value: null,
                  child: Text('（根级，无上级）'),
                ),
              for (final candidate in candidates)
                DropdownMenuItem<int?>(
                  value: candidate.location.id,
                  child: Text(
                    '${'　' * candidate.depth}${candidate.location.display}',
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
            ],
            onChanged: state.submitting
                ? null
                : (value) => setState(() {
                    _parentId = value;
                    _picked = true;
                  }),
          ),
          if (state.error != null) ...<Widget>[
            const SizedBox(height: 12),
            Text(
              state.error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ],
          if (unresolved) ...<Widget>[
            const SizedBox(height: 8),
            Text(
              '上次移动结果未知。请用「原样重试」以同一请求号重发，或核对库位树后放弃。',
              style: Theme.of(context).textTheme.labelSmall,
            ),
          ],
        ],
      ),
      actions: <Widget>[
        if (unresolved)
          TextButton(
            key: const ValueKey('location-move-discard'),
            onPressed: state.submitting
                ? null
                : () {
                    ref.read(locationMoveProvider.notifier).discardAttempt();
                    Navigator.pop(context);
                  },
            child: const Text('核对后放弃'),
          ),
        TextButton(
          onPressed: state.submitting ? null : () => Navigator.pop(context),
          child: const Text('取消'),
        ),
        FilledButton(
          key: const ValueKey('location-move-submit'),
          onPressed: state.submitting || (!_picked && !unresolved)
              ? null
              : () => _submit(unresolved),
          child: Text(
            state.submitting
                ? '移动中…'
                : unresolved
                ? '原样重试'
                : '确认移动',
          ),
        ),
      ],
    );
  }

  Future<void> _submit(bool retry) async {
    final target = widget.location.id;
    if (target == null) return;
    final parentId = retry
        ? ref.read(locationMoveProvider).attempt!.parentId
        : _parentId;
    final ok = await ref
        .read(locationMoveProvider.notifier)
        .move(locationId: target, parentId: parentId);
    if (!mounted) return;
    if (ok) {
      Navigator.pop(context, ref.read(locationMoveProvider).moved);
    }
  }
}
