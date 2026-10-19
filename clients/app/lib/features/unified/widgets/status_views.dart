import 'package:flutter/material.dart';

/// Failure state with the server's actionable Chinese message.
///
/// This widget exists so a network / permission / session failure is displayed
/// as a failure. It is never replaced by an empty list: showing "没有资料" when
/// the request actually failed would misinform the operator about stock.
class ErrorView extends StatelessWidget {
  const ErrorView({
    super.key,
    required this.message,
    this.code,
    this.onRetry,
    this.compact = false,
    this.retryLabel = '重试',
  });

  final String message;
  final String? code;
  final VoidCallback? onRetry;
  final bool compact;
  final String retryLabel;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hint = _hintFor(code);

    return Center(
      child: Padding(
        padding: EdgeInsets.all(compact ? 12 : 24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(
              Icons.error_outline,
              size: compact ? 32 : 48,
              color: theme.colorScheme.error,
            ),
            SizedBox(height: compact ? 8 : 12),
            Text(
              message,
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyMedium,
            ),
            if (hint != null) ...<Widget>[
              const SizedBox(height: 8),
              Text(
                hint,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
            if (onRetry != null) ...<Widget>[
              const SizedBox(height: 12),
              FilledButton.tonalIcon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: Text(retryLabel),
              ),
            ],
          ],
        ),
      ),
    );
  }

  static String? _hintFor(String? code) {
    switch (code) {
      case 'NETWORK_ERROR':
      case 'TRANSPORT_ERROR':
        return '请检查网络连接和服务器地址；恢复后点“重试”即可，已输入的内容不会丢失。';
      case 'SESSION_INVALID':
      case 'NOT_AUTHENTICATED':
        return '登录状态已失效，请重新登录后继续。';
      case 'ACCESS_DENIED':
      case 'PERMISSION_DENIED':
        return '当前账号没有该操作的权限，请联系库存管理员。';
      case 'CONFLICT':
        return '服务端检测到重复或冲突数据，请刷新后重试。';
      default:
        return null;
    }
  }
}

/// There is genuinely nothing to show (the server returned zero rows).
class EmptyView extends StatelessWidget {
  const EmptyView({
    super.key,
    this.title = '没有匹配的器件',
    this.subtitle,
    this.icon = Icons.inbox_outlined,
    this.action,
  });

  final String title;
  final String? subtitle;
  final IconData icon;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(icon, size: 48, color: theme.colorScheme.outline),
            const SizedBox(height: 12),
            Text(title, style: theme.textTheme.titleMedium),
            if (subtitle != null) ...<Widget>[
              const SizedBox(height: 6),
              Text(
                subtitle!,
                textAlign: TextAlign.center,
                style: theme.textTheme.bodySmall
                    ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
              ),
            ],
            if (action != null) ...<Widget>[
              const SizedBox(height: 12),
              action!,
            ],
          ],
        ),
      ),
    );
  }
}

/// Centred progress indicator.
class LoadingView extends StatelessWidget {
  const LoadingView({super.key, this.label});

  final String? label;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          const CircularProgressIndicator(),
          if (label != null) ...<Widget>[
            const SizedBox(height: 12),
            Text(label!, style: Theme.of(context).textTheme.bodySmall),
          ],
        ],
      ),
    );
  }
}
