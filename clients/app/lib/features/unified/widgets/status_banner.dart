import 'package:flutter/material.dart';

/// The meaning of a [StatusBanner]. Kept separate from [Color] so a screen
/// states what happened and the banner decides how to draw it.
enum StatusTone { error, warning, notice, success, info }

/// A message strip for errors, notices and success feedback.
///
/// Deliberately not a Material container colour: on the glass backdrop a solid
/// `errorContainer` card reads as an opaque slab, and its text colour is
/// inherited from `onSurface` rather than the container. Here the fill is the
/// semantic tone at 12%, the 0.5px edge and the icon carry the same tone, and
/// the text stays `onSurface`, so the state is legible in dark and light alike
/// and is never signalled by colour alone.
class StatusBanner extends StatelessWidget {
  const StatusBanner({
    super.key,
    required this.message,
    this.tone = StatusTone.info,
    this.icon,
    this.action,
    this.dense = false,
  });

  final String message;
  final StatusTone tone;

  /// Overrides the tone's default icon; the text always stays.
  final IconData? icon;

  /// Optional trailing control, e.g. a retry button.
  final Widget? action;

  /// Compact spacing for the middle of a scrolling list.
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final color = switch (tone) {
      StatusTone.error => scheme.error,
      StatusTone.warning => scheme.tertiary,
      StatusTone.notice => scheme.tertiary,
      StatusTone.success => scheme.secondary,
      StatusTone.info => scheme.primary,
    };
    final resolvedIcon =
        icon ??
        switch (tone) {
          StatusTone.error => Icons.error_outline,
          StatusTone.warning => Icons.warning_amber_rounded,
          StatusTone.notice => Icons.info_outline,
          StatusTone.success => Icons.check_circle_outline,
          StatusTone.info => Icons.info_outline,
        };
    return Container(
      width: double.infinity,
      padding: dense
          ? const EdgeInsets.symmetric(horizontal: 12, vertical: 6)
          : const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.40), width: 0.5),
      ),
      child: Row(
        children: <Widget>[
          Icon(resolvedIcon, size: 18, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              message,
              style:
                  (dense
                          ? theme.textTheme.labelSmall
                          : theme.textTheme.bodySmall)
                      ?.copyWith(color: scheme.onSurface),
            ),
          ),
          if (action != null) ...<Widget>[const SizedBox(width: 4), action!],
        ],
      ),
    );
  }
}
