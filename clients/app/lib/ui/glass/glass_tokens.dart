import 'package:flutter/material.dart';

/// Colours, radii, blur strengths and timings of the glass design system.
///
/// Two palettes exist: the shipped one is DARK (near-black backdrop with a
/// fluorescent-lime accent, matching the team-warehouse web UI tokens in
/// `lab_team_web/static/src/css/team.css`). The light palette is kept so a
/// screen pumped with a plain light `ThemeData` (widget tests do exactly that)
/// still renders with sensible contrast instead of dark-on-dark text.
///
/// Nothing here may be a per-screen literal: business screens read the tokens
/// through [GlassTokens.of] so one change repaints the whole app.
@immutable
class GlassPalette {
  const GlassPalette({
    required this.brightness,
    required this.backdrop,
    required this.backdropSoft,
    required this.panel,
    required this.panelStrong,
    required this.text,
    required this.textSoft,
    required this.muted,
    required this.accent,
    required this.accentSoft,
    required this.onAccent,
    required this.danger,
    required this.warning,
    required this.success,
    required this.hairline,
    required this.hairlineStrong,
    required this.glassEdge,
    required this.glassFill,
    required this.glassFillProminent,
    required this.glassShadow,
    required this.glowPrimary,
    required this.glowSecondary,
  });

  final Brightness brightness;

  /// Page background, painted by `GlassBackdrop`.
  final Color backdrop;
  final Color backdropSoft;

  /// Card / sheet / input fill (already translucent where it needs to be).
  final Color panel;
  final Color panelStrong;

  final Color text;
  final Color textSoft;
  final Color muted;

  final Color accent;
  final Color accentSoft;
  final Color onAccent;

  final Color danger;
  final Color warning;
  final Color success;

  /// 0.5px separators between content blocks.
  final Color hairline;
  final Color hairlineStrong;

  /// 0.5px highlight around a glass surface. Keep it: it is what sells the
  /// material instead of a grey rounded rectangle.
  final Color glassEdge;

  /// Alpha of the white gradient that fills a glass surface.
  final double glassFill;
  final double glassFillProminent;

  final Color glassShadow;

  /// Light sources behind the glass. Static, never animated.
  final Color glowPrimary;
  final Color glowSecondary;

  static const dark = GlassPalette(
    brightness: Brightness.dark,
    backdrop: Color(0xFF070809),
    backdropSoft: Color(0xFF0B0D10),
    panel: Color(0xFF111418),
    panelStrong: Color(0xFF161A20),
    text: Color(0xFFF2F4EE),
    textSoft: Color(0xD1F2F4EE),
    muted: Color(0xFF9AA199),
    accent: Color(0xFFC9FF3F),
    accentSoft: Color(0x24C9FF3F),
    onAccent: Color(0xFF0A0D06),
    danger: Color(0xFFFF4B3E),
    warning: Color(0xFFD9B46A),
    success: Color(0xFF7FE7B0),
    hairline: Color(0x1FF2F4EE),
    hairlineStrong: Color(0x42F2F4EE),
    glassEdge: Color(0x47FFFFFF),
    glassFill: 0.10,
    glassFillProminent: 0.94,
    glassShadow: Color(0x52000000),
    glowPrimary: Color(0xFFC9FF3F),
    glowSecondary: Color(0xFF4FD1C5),
  );

  /// Fallback for a light `ThemeData` (older widget tests and any host that
  /// does not install the glass theme).
  static const light = GlassPalette(
    brightness: Brightness.light,
    backdrop: Color(0xFFEFF3F7),
    backdropSoft: Color(0xFFF8FAFC),
    panel: Color(0xFFFCFDFE),
    panelStrong: Color(0xFFFFFFFF),
    text: Color(0xFF10151C),
    textSoft: Color(0xD910151C),
    muted: Color(0xFF5B6472),
    accent: Color(0xFF3D7A00),
    accentSoft: Color(0x1A3D7A00),
    onAccent: Color(0xFFFFFFFF),
    danger: Color(0xFFC0261B),
    warning: Color(0xFF8A5A00),
    success: Color(0xFF1F7A4D),
    hairline: Color(0x1F0B1220),
    hairlineStrong: Color(0x3D0B1220),
    glassEdge: Color(0xB3FFFFFF),
    glassFill: 0.62,
    glassFillProminent: 0.94,
    glassShadow: Color(0x1A000000),
    glowPrimary: Color(0xFF9BD13A),
    glowSecondary: Color(0xFF4FD1C5),
  );

  static GlassPalette of(Brightness brightness) =>
      brightness == Brightness.dark ? dark : light;
}

/// The theme extension every glass widget reads.
@immutable
class GlassTokens extends ThemeExtension<GlassTokens> {
  const GlassTokens({
    required this.palette,
    required this.radiusCard,
    required this.radiusField,
    required this.radiusPanel,
    required this.radiusSheet,
    required this.blurChrome,
    required this.blurOverlay,
    required this.blurCard,
    required this.padCard,
    required this.padScreen,
    required this.fast,
    required this.normal,
    required this.pressScale,
    required this.minTapTarget,
  });

  final GlassPalette palette;

  final double radiusCard;
  final double radiusField;
  final double radiusPanel;
  final double radiusSheet;

  /// Blur for the app bar / toolbars. Kept inside 12–24: below 12 it reads as
  /// a flat tint, above 24 it turns to mud and costs frame time.
  final double blurChrome;

  /// Blur for floating panels, dialogs and sheets.
  final double blurOverlay;

  /// Cards and list rows are deliberately NOT blurred: a `BackdropFilter` per
  /// list item is the one thing that makes scrolling glass jank.
  final double blurCard;

  final EdgeInsets padCard;
  final EdgeInsets padScreen;

  final Duration fast;
  final Duration normal;
  final double pressScale;
  final double minTapTarget;

  static const dark = GlassTokens(
    palette: GlassPalette.dark,
    radiusCard: 22,
    radiusField: 16,
    radiusPanel: 24,
    radiusSheet: 28,
    blurChrome: 24,
    blurOverlay: 20,
    blurCard: 0,
    padCard: EdgeInsets.all(16),
    padScreen: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
    fast: Duration(milliseconds: 120),
    normal: Duration(milliseconds: 180),
    pressScale: 0.97,
    minTapTarget: 44,
  );

  static const light = GlassTokens(
    palette: GlassPalette.light,
    radiusCard: 22,
    radiusField: 16,
    radiusPanel: 24,
    radiusSheet: 28,
    blurChrome: 20,
    blurOverlay: 18,
    blurCard: 0,
    padCard: EdgeInsets.all(16),
    padScreen: EdgeInsets.symmetric(horizontal: 16, vertical: 12),
    fast: Duration(milliseconds: 120),
    normal: Duration(milliseconds: 180),
    pressScale: 0.97,
    minTapTarget: 44,
  );

  static GlassTokens of(Brightness brightness) =>
      brightness == Brightness.dark ? dark : light;

  /// Reads the installed extension, falling back to the palette that matches
  /// the ambient brightness. Screens are pumped under a bare `ThemeData` in
  /// several tests, and they must not crash or turn invisible for it.
  static GlassTokens ofContext(BuildContext context) {
    final theme = Theme.of(context);
    final installed = theme.extension<GlassTokens>();
    if (installed != null) return installed;
    return of(theme.brightness);
  }

  @override
  GlassTokens copyWith({
    GlassPalette? palette,
    double? radiusCard,
    double? radiusField,
    double? radiusPanel,
    double? radiusSheet,
    double? blurChrome,
    double? blurOverlay,
    double? blurCard,
    EdgeInsets? padCard,
    EdgeInsets? padScreen,
    Duration? fast,
    Duration? normal,
    double? pressScale,
    double? minTapTarget,
  }) {
    return GlassTokens(
      palette: palette ?? this.palette,
      radiusCard: radiusCard ?? this.radiusCard,
      radiusField: radiusField ?? this.radiusField,
      radiusPanel: radiusPanel ?? this.radiusPanel,
      radiusSheet: radiusSheet ?? this.radiusSheet,
      blurChrome: blurChrome ?? this.blurChrome,
      blurOverlay: blurOverlay ?? this.blurOverlay,
      blurCard: blurCard ?? this.blurCard,
      padCard: padCard ?? this.padCard,
      padScreen: padScreen ?? this.padScreen,
      fast: fast ?? this.fast,
      normal: normal ?? this.normal,
      pressScale: pressScale ?? this.pressScale,
      minTapTarget: minTapTarget ?? this.minTapTarget,
    );
  }

  @override
  GlassTokens lerp(ThemeExtension<GlassTokens>? other, double t) {
    if (other is! GlassTokens) return this;
    final a = palette;
    final b = other.palette;
    return GlassTokens(
      palette: GlassPalette(
        brightness: t < 0.5 ? a.brightness : b.brightness,
        backdrop: Color.lerp(a.backdrop, b.backdrop, t)!,
        backdropSoft: Color.lerp(a.backdropSoft, b.backdropSoft, t)!,
        panel: Color.lerp(a.panel, b.panel, t)!,
        panelStrong: Color.lerp(a.panelStrong, b.panelStrong, t)!,
        text: Color.lerp(a.text, b.text, t)!,
        textSoft: Color.lerp(a.textSoft, b.textSoft, t)!,
        muted: Color.lerp(a.muted, b.muted, t)!,
        accent: Color.lerp(a.accent, b.accent, t)!,
        accentSoft: Color.lerp(a.accentSoft, b.accentSoft, t)!,
        onAccent: Color.lerp(a.onAccent, b.onAccent, t)!,
        danger: Color.lerp(a.danger, b.danger, t)!,
        warning: Color.lerp(a.warning, b.warning, t)!,
        success: Color.lerp(a.success, b.success, t)!,
        hairline: Color.lerp(a.hairline, b.hairline, t)!,
        hairlineStrong: Color.lerp(a.hairlineStrong, b.hairlineStrong, t)!,
        glassEdge: Color.lerp(a.glassEdge, b.glassEdge, t)!,
        glassFill: a.glassFill + (b.glassFill - a.glassFill) * t,
        glassFillProminent:
            a.glassFillProminent +
            (b.glassFillProminent - a.glassFillProminent) * t,
        glassShadow: Color.lerp(a.glassShadow, b.glassShadow, t)!,
        glowPrimary: Color.lerp(a.glowPrimary, b.glowPrimary, t)!,
        glowSecondary: Color.lerp(a.glowSecondary, b.glowSecondary, t)!,
      ),
      radiusCard: radiusCard + (other.radiusCard - radiusCard) * t,
      radiusField: radiusField + (other.radiusField - radiusField) * t,
      radiusPanel: radiusPanel + (other.radiusPanel - radiusPanel) * t,
      radiusSheet: radiusSheet + (other.radiusSheet - radiusSheet) * t,
      blurChrome: blurChrome + (other.blurChrome - blurChrome) * t,
      blurOverlay: blurOverlay + (other.blurOverlay - blurOverlay) * t,
      blurCard: blurCard + (other.blurCard - blurCard) * t,
      padCard: EdgeInsets.lerp(padCard, other.padCard, t)!,
      padScreen: EdgeInsets.lerp(padScreen, other.padScreen, t)!,
      fast: fast,
      normal: normal,
      pressScale: pressScale + (other.pressScale - pressScale) * t,
      minTapTarget: minTapTarget + (other.minTapTarget - minTapTarget) * t,
    );
  }
}
