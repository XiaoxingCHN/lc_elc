import 'package:flutter/material.dart';

import '../models/unified_item.dart';

/// Shown while the CREATE request itself runs, before any status exists.
///
/// The server answers this call only after trying the fetch inline, so it can
/// legitimately take up to ~20 seconds.
class CatalogFetchRunning extends StatelessWidget {
  const CatalogFetchRunning({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: <Widget>[
            const SizedBox(
              width: 18,
              height: 18,
              child: CircularProgressIndicator(strokeWidth: 2),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                '正在从立创商城抓取，通常 20 秒内完成…',
                style: theme.textTheme.bodyMedium,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Progress and result of ONE on-demand LCSC fetch.
///
/// Shared by the catalog search screen, both receipt forms and the item detail.
/// Every state pairs its colour with an icon and words; candidates are real
/// buttons because the server only lists variants whose MPN matched exactly.
class CatalogFetchPanel extends StatelessWidget {
  const CatalogFetchPanel({
    super.key,
    required this.status,
    required this.onChoose,
    this.onQueryAgain,
  });

  final CatalogFetchStatus status;
  final ValueChanged<CatalogFetchCandidate> onChoose;

  /// Asks the server about a task this client stopped following. Only rendered
  /// when the status is still queryable and the caller wired an action.
  final VoidCallback? onQueryAgain;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final running = status.isActive;
    final (IconData icon, Color tone) = switch (status.state) {
      'done' => (Icons.check_circle_outline, theme.colorScheme.primary),
      'failed' || 'not_found' => (
          Icons.error_outline,
          theme.colorScheme.error,
        ),
      'skipped_non_electronic' => (
          Icons.block,
          theme.colorScheme.onSurfaceVariant,
        ),
      'review' => (Icons.fact_check_outlined, theme.colorScheme.tertiary),
      CatalogFetchStatus.stillRunningState => (
          Icons.schedule,
          theme.colorScheme.tertiary,
        ),
      _ => (Icons.hourglass_top, theme.colorScheme.primary),
    };

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Icon(icon, size: 20, color: tone),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    _title(status.state),
                    style: theme.textTheme.titleSmall,
                  ),
                ),
              ],
            ),
            if (running) ...<Widget>[
              const SizedBox(height: 12),
              const LinearProgressIndicator(),
              const SizedBox(height: 8),
              Text(
                status.state == 'queued'
                    ? '排队等待后台处理，通常一分钟内开始。可离开本页，稍后回来再查。'
                    : '正在读取立创商城的中文详情页，请稍候…',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
            if (!running && status.message.isNotEmpty) ...<Widget>[
              const SizedBox(height: 8),
              Text(status.message, style: theme.textTheme.bodySmall),
            ],
            if (status.isStillRunning && onQueryAgain != null) ...<Widget>[
              const SizedBox(height: 8),
              Align(
                alignment: Alignment.centerLeft,
                child: OutlinedButton.icon(
                  onPressed: onQueryAgain,
                  icon: const Icon(Icons.refresh),
                  label: const Text('重新查询任务状态'),
                ),
              ),
            ],
            if (status.isDone && status.message.isEmpty) ...<Widget>[
              const SizedBox(height: 8),
              Text('已写入器件库，正在刷新检索结果…',
                  style: theme.textTheme.bodySmall),
            ],
            if (status.isCandidates && status.candidates.isNotEmpty) ...<Widget>[
              const SizedBox(height: 12),
              Text(
                '以下是立创商城的搜索结果。选定一个之后才会抓取它的完整资料：',
                style: theme.textTheme.bodyMedium,
              ),
              const SizedBox(height: 4),
              ...status.candidates.map(
                (candidate) => ListTile(
                  dense: true,
                  contentPadding: EdgeInsets.zero,
                  title: Text(candidate.label),
                  trailing: TextButton(
                    onPressed: () => onChoose(candidate),
                    child: const Text('选这个'),
                  ),
                ),
              ),
              Text(
                '候选只含名称、型号、封装和 C 码，尚未写入器件库；'
                '不确定时请先核对封装，避免把同系列不同封装的参数写进同一条记录。',
                style: theme.textTheme.bodySmall?.copyWith(
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  static String _title(String state) {
    switch (state) {
      case 'queued':
        return '已加入抓取队列';
      case 'resolving':
        return '正在立创商城匹配型号';
      case 'fetching':
        return '正在抓取中文详情';
      case 'done':
        return '已抓取并入库';
      case 'failed':
        return '抓取失败';
      case 'skipped_non_electronic':
        return '已跳过：非电子元器件';
      case 'review':
        return '已记录，分类需人工复核';
      case 'not_found':
        return '立创商城未找到完全匹配的型号';
      case 'candidates':
        return '在立创商城找到多个候选';
      case CatalogFetchStatus.stillRunningState:
        return '抓取任务仍在后台处理';
      default:
        return '抓取状态';
    }
  }
}
