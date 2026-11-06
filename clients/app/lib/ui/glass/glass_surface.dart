import 'dart:ui' show ImageFilter;

import 'package:flutter/material.dart';

import 'glass_tokens.dart';

/// Outline of a glass surface.
enum GlassShape { capsule, rounded, circle }

/// The ONE place in this app allowed to create a `BackdropFilter`.
///
/// Apple's Liquid Glass is a blur of what is *behind* a surface plus a tint,
/// a specular edge and a soft shadow. Flutter can approximate the blur, tint
/// and edge; it cannot do refraction, edge bending or adaptive light without a
/// fragment shader, so this is deliberately an approximation, not parity.
///
/// Rules that keep it readable and cheap:
///   * one blur layer per visual group - never one per list row;
///   * [blur] <= 0 paints a plain translucent panel (that is what cards use);
///   * sigma stays in 12..24 (below reads as a tint, above turns to mud);
///   * high-contrast mode raises the fill and drops the blur.
class GlassSurface extends StatelessWidget {
  const GlassSurface({
    super.key,
    required this.child,
    this.blur,
    this.shape = GlassShape.rounded,
    this.radius,
    this.borderRadius,
    this.tint,
    this.prominent = false,
    this.padding = const EdgeInsets.all(16),
    this.showEdge = true,
    this.showShadow = true,
  });

  final Widget child;

  /// Blur strength. Omit to use [GlassTokens.blurOverlay]; pass 0 for cards and
  /// any content that scrolls.
  final double? blur;

  final GlassShape shape;
  final double? radius;

  /// Exact corners, overriding [shape] + [radius] (e.g. a sheet that is only
  /// rounded at the top).
  final BorderRadius? borderRadius;

  /// Gradient base colour. Neutral glass uses white on dark and a pale panel
  /// on light; the prominent variant uses the accent so `onAccent` stays valid.
  final Color? tint;

  /// The stronger variant: more fill, brighter edge. At most one per screen.
  final bool prominent;

  final EdgeInsetsGeometry padding;

  /// The 0.5px highlight. Keep it on for glass; turn it off for a full-bleed
  /// app bar where only the bottom hairline should show.
  final bool showEdge;

  final bool showShadow;

  @override
  Widget build(BuildContext context) {
    final tokens = GlassTokens.ofContext(context);
    final palette = tokens.palette;
    final media = MediaQuery.maybeOf(context);
    final highContrast = media?.highContrast ?? false;

    final corners = borderRadius ?? _corners(tokens);
    final base =
        tint ??
        (prominent
            ? palette.accent
            : (palette.brightness == Brightness.dark
                  ? Colors.white
                  : palette.panelStrong));
    final fill = highContrast
        ? (prominent ? 1.0 : 0.72)
        : (prominent ? palette.glassFillProminent : palette.glassFill);
    final sigma = highContrast ? 0.0 : (blur ?? tokens.blurOverlay);

    final glass = DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: corners,
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            base.withValues(alpha: fill),
            base.withValues(alpha: fill * 0.35),
          ],
        ),
        border: showEdge
            ? Border.all(
                color: palette.glassEdge.withValues(
                  alpha: highContrast ? 0.75 : palette.glassEdge.a,
                ),
                width: 0.5,
              )
            : null,
      ),
      child: Padding(padding: padding, child: child),
    );

    Widget surface = ClipRRect(
      borderRadius: corners,
      child: sigma > 0
          ? BackdropFilter(
              filter: ImageFilter.blur(sigmaX: sigma, sigmaY: sigma),
              child: glass,
            )
          : glass,
    );

    if (showShadow) {
      // Painted outside the clip, otherwise the clip eats the shadow.
      surface = DecoratedBox(
        decoration: BoxDecoration(
          borderRadius: corners,
          boxShadow: [
            BoxShadow(
              color: palette.glassShadow,
              blurRadius: 28,
              offset: const Offset(0, 10),
            ),
          ],
        ),
        child: surface,
      );
    }

    return sigma > 0 ? RepaintBoundary(child: surface) : surface;
  }

  BorderRadius _corners(GlassTokens tokens) {
    return switch (shape) {
      GlassShape.capsule || GlassShape.circle => BorderRadius.circular(999),
      GlassShape.rounded => BorderRadius.circular(radius ?? tokens.radiusCard),
    };
  }
}
