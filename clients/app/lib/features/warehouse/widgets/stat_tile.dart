import 'package:flutter/material.dart';

import '../../../ui/glass/glass_chrome.dart';
import '../../../ui/glass/glass_tokens.dart';

/// One figure in a 速览 row: a small label over a large value.
///
/// Lifted from the item detail screen's private `_Metric` so the overview and
/// the detail page show numbers the same way. [muted] is what an unknown or
/// not-yet-loaded figure uses - it must never render as a confident "0", which
/// is why the caller passes `—` rather than a zero it did not measure.
class StatTile extends StatelessWidget {
  const StatTile({
    super.key,
    required this.label,
    required this.value,
    this.subtitle,
    this.icon,
    this.highlight = false,
    this.muted = false,
  });

  final String label;
  final String value;
  final String? subtitle;
  final IconData? icon;
  final bool highlight;
  final bool muted;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final tokens = GlassTokens.ofContext(context);
    final palette = tokens.palette;
    final valueColor = muted
        ? palette.muted
        : (highlight ? theme.colorScheme.primary : theme.colorScheme.onSurface);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: <Widget>[
        Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            if (icon != null) ...<Widget>[
              Icon(icon, size: 14, color: palette.muted),
              const SizedBox(width: 4),
            ],
            Text(label, style: theme.textTheme.labelSmall),
          ],
        ),
        const SizedBox(height: 2),
        Text(
          value,
          style: theme.textTheme.titleMedium?.copyWith(
            fontWeight: FontWeight.w700,
            color: valueColor,
          ),
        ),
        if (subtitle != null) ...<Widget>[
          const SizedBox(height: 2),
          Text(
            subtitle!,
            style: theme.textTheme.labelSmall?.copyWith(color: palette.muted),
          ),
        ],
      ],
    );
  }
}

/// A row of [StatTile]s that wraps instead of overflowing.
///
/// Wrapping (not a fixed grid) is the house rule for anything that can overflow
/// at 320 px with long Chinese labels.
class StatRow extends StatelessWidget {
  const StatRow({super.key, required this.tiles, this.spacing = 24});

  final List<Widget> tiles;
  final double spacing;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: spacing,
      runSpacing: 12,
      crossAxisAlignment: WrapCrossAlignment.start,
      children: tiles,
    );
  }
}

/// A large tappable entry: icon, title, one-line description.
///
/// Used by 库存管理 for the five operations. Same visual language as the old
/// (now unreachable) home screen's `_ActionCard`, but it lives here so the
/// warehouse module owns its own chrome.
class NavCard extends StatelessWidget {
  const NavCard({
    super.key,
    required this.title,
    required this.subtitle,
    required this.icon,
    required this.onTap,
    this.enabled = true,
    this.disabledReason,
  });

  final String title;
  final String subtitle;
  final IconData icon;
  final VoidCallback onTap;

  /// False when the operator lacks the permission for this operation; the card
  /// still renders (so the flow is discoverable) but says why it cannot open.
  final bool enabled;
  final String? disabledReason;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final palette = GlassTokens.ofContext(context).palette;
    // NEUTRAL panel, accent icon. `GlassSurface.prominent` fills the whole card
    // with the fluorescent accent, and its own doc says "at most one per
    // screen" - a list of five such cards put onSurface text on a bright lime
    // fill, which is unreadable. The accent stays as the icon and the edge, the
    // text stays on the panel colour.
    final fg = enabled ? palette.accent : palette.muted;

    return Semantics(
      button: enabled,
      enabled: enabled,
      label: enabled
          ? '$title，$subtitle'
          : '$title，不可用：${disabledReason ?? ''}',
      child: InkWell(
        borderRadius: BorderRadius.circular(22),
        onTap: enabled ? onTap : null,
        child: GlassPanel(
          child: Row(
            children: <Widget>[
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: fg.withValues(alpha: 0.14),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(icon, size: 24, color: fg),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    Text(
                      title,
                      style: theme.textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: theme.colorScheme.onSurface,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      enabled ? subtitle : (disabledReason ?? subtitle),
                      style: theme.textTheme.labelSmall?.copyWith(
                        color: palette.textSoft,
                      ),
                    ),
                  ],
                ),
              ),
              if (enabled)
                Icon(Icons.chevron_right, size: 20, color: palette.textSoft),
            ],
          ),
        ),
      ),
    );
  }
}
