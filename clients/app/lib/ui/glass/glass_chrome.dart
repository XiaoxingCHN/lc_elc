import 'package:flutter/material.dart';

import 'glass_surface.dart';
import 'glass_tokens.dart';

/// The page background: a near-black base with two static light sources.
///
/// Glass only reads as glass when there is something behind it to blur, so the
/// backdrop carries colour. Nothing here animates: a moving full-screen glow
/// would repaint every glass surface on every frame for no information.
class GlassBackdrop extends StatelessWidget {
  const GlassBackdrop({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final palette = GlassTokens.ofContext(context).palette;
    return ColoredBox(
      color: palette.backdrop,
      child: Stack(
        fit: StackFit.expand,
        children: [
          DecoratedBox(
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  palette.backdrop,
                  palette.backdropSoft,
                  palette.backdrop,
                ],
              ),
            ),
          ),
          // Static, non-interactive, isolated: it never needs a new layer.
          RepaintBoundary(
            child: IgnorePointer(
              child: Stack(
                children: [
                  Positioned(
                    top: -140,
                    left: -100,
                    child: _Glow(color: palette.glowPrimary, size: 420),
                  ),
                  Positioned(
                    bottom: -180,
                    right: -120,
                    child: _Glow(color: palette.glowSecondary, size: 520),
                  ),
                ],
              ),
            ),
          ),
          child,
        ],
      ),
    );
  }
}

class _Glow extends StatelessWidget {
  const _Glow({required this.color, required this.size});

  final Color color;
  final double size;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: size,
      height: size,
      child: DecoratedBox(
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          gradient: RadialGradient(
            colors: [
              color.withValues(alpha: 0.18),
              color.withValues(alpha: 0.06),
              color.withValues(alpha: 0),
            ],
            stops: const [0, 0.45, 1],
          ),
        ),
      ),
    );
  }
}

/// Toolbar glass. Full-bleed, square corners, one bottom hairline and no
/// shadow, so scrollable content passes underneath the blur instead of being
/// framed by a floating bar.
class GlassAppBarSurface extends StatelessWidget {
  const GlassAppBarSurface({super.key});

  @override
  Widget build(BuildContext context) {
    final tokens = GlassTokens.ofContext(context);
    return GlassSurface(
      blur: tokens.blurChrome,
      radius: 0,
      padding: EdgeInsets.zero,
      showEdge: false,
      showShadow: false,
      child: DecoratedBox(
        decoration: BoxDecoration(
          border: Border(
            bottom: BorderSide(
              color: tokens.palette.hairlineStrong,
              width: 0.5,
            ),
          ),
        ),
        child: const SizedBox.expand(),
      ),
    );
  }
}

/// A content surface. It is fill-only by default; floating overlays explicitly
/// pass [blur] so scrolling content never pays for a BackdropFilter per panel.
class GlassPanel extends StatelessWidget {
  const GlassPanel({
    super.key,
    required this.child,
    this.padding,
    this.prominent = false,
    this.radius,
    this.blur,
  });

  final Widget child;
  final EdgeInsetsGeometry? padding;
  final bool prominent;
  final double? radius;
  final double? blur;

  @override
  Widget build(BuildContext context) {
    final tokens = GlassTokens.ofContext(context);
    return GlassSurface(
      blur: blur ?? tokens.blurCard,
      prominent: prominent,
      radius: radius ?? tokens.radiusPanel,
      padding: padding ?? tokens.padCard,
      child: child,
    );
  }
}

/// Glass shell for a bottom sheet / dialog body. Rounded at the top only, so it
/// sits flush against the bottom edge on phones.
class GlassSheetSurface extends StatelessWidget {
  const GlassSheetSurface({
    super.key,
    required this.child,
    this.padding = const EdgeInsets.fromLTRB(20, 12, 20, 20),
  });

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    final tokens = GlassTokens.ofContext(context);
    final radius = Radius.circular(tokens.radiusSheet);
    return GlassSurface(
      blur: tokens.blurOverlay,
      borderRadius: BorderRadius.vertical(top: radius),
      padding: padding,
      showShadow: false,
      child: child,
    );
  }
}
