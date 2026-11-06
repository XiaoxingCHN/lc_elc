import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'glass_surface.dart';
import 'glass_tokens.dart';

/// A tappable glass capsule.
///
/// Keeps the exact contract of a Material button where it matters:
///   * [onPressed] == null disables it (no tap, reduced opacity, no focus);
///   * 44x44 minimum target;
///   * Enter / Space activate it from the keyboard;
///   * the label ellipsizes instead of overflowing at 200% text.
///
/// The press reaction is a 0.97 scale plus the stronger fill, and it is
/// suppressed when the platform asks for reduced motion.
class GlassButton extends StatefulWidget {
  const GlassButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.icon,
    this.prominent = false,
    this.expand = true,
    this.semanticLabel,
  });

  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool prominent;

  /// Fill the parent width. Set false for a compact inline action.
  final bool expand;
  final String? semanticLabel;

  @override
  State<GlassButton> createState() => _GlassButtonState();
}

class _GlassButtonState extends State<GlassButton> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    final tokens = GlassTokens.ofContext(context);
    final palette = tokens.palette;
    final reducedMotion =
        MediaQuery.maybeOf(context)?.disableAnimations ?? false;
    final enabled = widget.onPressed != null;
    final pressed = _pressed && enabled && !reducedMotion;
    final emphasized = widget.prominent || pressed;
    final fg = emphasized ? palette.onAccent : palette.text;

    final content = Row(
      mainAxisSize: widget.expand ? MainAxisSize.max : MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        if (widget.icon != null) ...[
          Icon(widget.icon, size: 18, color: fg),
          const SizedBox(width: 8),
        ],
        Flexible(
          child: Text(
            widget.label,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: fg,
              fontSize: 15,
              fontWeight: FontWeight.w600,
              height: 1.25,
            ),
          ),
        ),
      ],
    );

    return Opacity(
      opacity: enabled ? 1 : .45,
      child: Semantics(
        button: true,
        enabled: enabled,
        label: widget.semanticLabel ?? widget.label,
        child: FocusableActionDetector(
          enabled: enabled,
          mouseCursor: enabled
              ? SystemMouseCursors.click
              : SystemMouseCursors.basic,
          shortcuts: const <ShortcutActivator, Intent>{
            SingleActivator(LogicalKeyboardKey.enter): ActivateIntent(),
            SingleActivator(LogicalKeyboardKey.space): ActivateIntent(),
          },
          actions: <Type, Action<Intent>>{
            ActivateIntent: CallbackAction<ActivateIntent>(
              onInvoke: (_) {
                widget.onPressed?.call();
                return null;
              },
            ),
          },
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTapDown: enabled ? (_) => setState(() => _pressed = true) : null,
            onTapCancel: enabled
                ? () => setState(() => _pressed = false)
                : null,
            onTapUp: enabled ? (_) => setState(() => _pressed = false) : null,
            onTap: widget.onPressed,
            child: AnimatedScale(
              scale: pressed ? tokens.pressScale : 1,
              duration: reducedMotion ? Duration.zero : tokens.fast,
              curve: Curves.easeOut,
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  minWidth: tokens.minTapTarget,
                  minHeight: tokens.minTapTarget,
                ),
                child: GlassSurface(
                  blur: 0,
                  radius: tokens.radiusField,
                  prominent: emphasized,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 18,
                    vertical: 12,
                  ),
                  showShadow: widget.prominent,
                  child: content,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// A circular glass icon action with a tooltip and a 44x44 target.
class GlassIconButton extends StatefulWidget {
  const GlassIconButton({
    super.key,
    required this.icon,
    required this.tooltip,
    required this.onPressed,
    this.size = 44,
  });

  final IconData icon;
  final String tooltip;
  final VoidCallback? onPressed;
  final double size;

  @override
  State<GlassIconButton> createState() => _GlassIconButtonState();
}

class _GlassIconButtonState extends State<GlassIconButton> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    final tokens = GlassTokens.ofContext(context);
    final palette = tokens.palette;
    final reducedMotion =
        MediaQuery.maybeOf(context)?.disableAnimations ?? false;
    final enabled = widget.onPressed != null;
    final pressed = _pressed && enabled && !reducedMotion;

    return Tooltip(
      message: widget.tooltip,
      child: Semantics(
        button: true,
        enabled: enabled,
        label: widget.tooltip,
        child: FocusableActionDetector(
          enabled: enabled,
          mouseCursor: enabled
              ? SystemMouseCursors.click
              : SystemMouseCursors.basic,
          shortcuts: const <ShortcutActivator, Intent>{
            SingleActivator(LogicalKeyboardKey.enter): ActivateIntent(),
            SingleActivator(LogicalKeyboardKey.space): ActivateIntent(),
          },
          actions: <Type, Action<Intent>>{
            ActivateIntent: CallbackAction<ActivateIntent>(
              onInvoke: (_) {
                widget.onPressed?.call();
                return null;
              },
            ),
          },
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTapDown: enabled ? (_) => setState(() => _pressed = true) : null,
            onTapCancel: enabled
                ? () => setState(() => _pressed = false)
                : null,
            onTapUp: enabled ? (_) => setState(() => _pressed = false) : null,
            onTap: widget.onPressed,
            child: AnimatedScale(
              scale: pressed ? tokens.pressScale : 1,
              duration: reducedMotion ? Duration.zero : tokens.fast,
              curve: Curves.easeOut,
              child: SizedBox(
                width: widget.size < tokens.minTapTarget
                    ? tokens.minTapTarget
                    : widget.size,
                height: widget.size < tokens.minTapTarget
                    ? tokens.minTapTarget
                    : widget.size,
                child: GlassSurface(
                  blur: 0,
                  shape: GlassShape.circle,
                  padding: EdgeInsets.zero,
                  prominent: pressed,
                  showShadow: false,
                  child: Center(
                    child: Icon(
                      widget.icon,
                      size: 22,
                      color: enabled ? palette.text : palette.muted,
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// iOS-style segmented control on glass.
///
/// Controlled: the caller owns [value] and reacts in [onChanged]. The row
/// scrolls horizontally instead of overflowing, which is what keeps it usable
/// at 320px with 200% text; labels ellipsize rather than clip.
class GlassSegmentedControl<T> extends StatelessWidget {
  const GlassSegmentedControl({
    super.key,
    required this.value,
    required this.onChanged,
    required this.children,
    this.expanded = true,
  });

  final T value;
  final ValueChanged<T>? onChanged;

  /// Segment order is the map's insertion order.
  final Map<T, Widget> children;

  final bool expanded;

  @override
  Widget build(BuildContext context) {
    final tokens = GlassTokens.ofContext(context);
    final palette = tokens.palette;
    final enabled = onChanged != null;

    return GlassSurface(
      blur: 0,
      shape: GlassShape.capsule,
      padding: const EdgeInsets.all(4),
      showShadow: false,
      child: LayoutBuilder(
        builder: (context, constraints) {
          final row = Row(
            mainAxisSize: MainAxisSize.min,
            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
            children: [
              for (final entry in children.entries)
                _Segment(
                  selected: entry.key == value,
                  enabled: enabled,
                  onTap: enabled ? () => onChanged!(entry.key) : null,
                  palette: palette,
                  minHeight: tokens.minTapTarget - 8,
                  label: entry.value,
                ),
            ],
          );
          return SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: ConstrainedBox(
              constraints: BoxConstraints(
                minWidth: expanded ? constraints.maxWidth : 0,
              ),
              child: row,
            ),
          );
        },
      ),
    );
  }
}

class _Segment extends StatelessWidget {
  const _Segment({
    required this.selected,
    required this.enabled,
    required this.onTap,
    required this.palette,
    required this.minHeight,
    required this.label,
  });

  final bool selected;
  final bool enabled;
  final VoidCallback? onTap;
  final GlassPalette palette;
  final double minHeight;
  final Widget label;

  @override
  Widget build(BuildContext context) {
    final text = DefaultTextStyle.merge(
      style: TextStyle(
        color: selected ? palette.onAccent : palette.textSoft,
        fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
        fontSize: 14,
      ),
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      child: label,
    );
    return Semantics(
      button: true,
      selected: selected,
      enabled: enabled,
      inMutuallyExclusiveGroup: true,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTap: onTap,
        child: ConstrainedBox(
          constraints: BoxConstraints(minHeight: minHeight, minWidth: 88),
          child: selected
              ? GlassSurface(
                  blur: 0,
                  shape: GlassShape.capsule,
                  prominent: true,
                  showShadow: false,
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 8,
                  ),
                  child: Center(child: text),
                )
              : Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 8,
                  ),
                  child: Center(child: text),
                ),
        ),
      ),
    );
  }
}
