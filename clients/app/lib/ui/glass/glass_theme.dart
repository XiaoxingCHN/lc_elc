import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'glass_tokens.dart';

/// Builds the Material 3 theme the glass widgets sit in.
///
/// Scope: this styles every Material surface in the app EXCEPT the ones that
/// need real blur - those use `GlassSurface` directly. Cards, inputs, dialogs,
/// sheets and bars get the glass *look* (translucent fill, hairline edge,
/// large radius) with zero `BackdropFilter`, because a blur inside a scrolling
/// list is the one thing that makes this design janky.
///
/// Both brightnesses are complete: the app ships dark, while a screen pumped
/// under a bare light `ThemeData` in a widget test still gets the light tokens.
ThemeData buildGlassTheme(Brightness brightness) {
  final tokens = GlassTokens.of(brightness);
  final p = tokens.palette;
  final dark = brightness == Brightness.dark;

  final scheme =
      ColorScheme.fromSeed(
        seedColor: p.accent,
        brightness: brightness,
      ).copyWith(
        primary: p.accent,
        onPrimary: p.onAccent,
        primaryContainer: dark
            ? const Color(0xFF243309)
            : const Color(0xFFE8F6CE),
        onPrimaryContainer: dark
            ? const Color(0xFFE9FFC2)
            : const Color(0xFF22320A),
        secondary: p.glowSecondary,
        onSecondary: dark ? const Color(0xFF06201C) : Colors.white,
        secondaryContainer: p.accentSoft,
        onSecondaryContainer: p.text,
        surface: p.backdrop,
        onSurface: p.text,
        surfaceContainerLowest: p.backdrop,
        surfaceContainerLow: p.backdropSoft,
        surfaceContainer: p.panel,
        surfaceContainerHigh: p.panel,
        surfaceContainerHighest: p.panelStrong,
        onSurfaceVariant: p.textSoft,
        outline: p.hairlineStrong,
        outlineVariant: p.hairline,
        error: p.danger,
        onError: dark ? const Color(0xFF200301) : Colors.white,
        shadow: p.glassShadow,
        scrim: Colors.black,
      );

  final base = ThemeData(
    brightness: brightness,
    useMaterial3: true,
    colorScheme: scheme,
  );

  final fieldRadius = BorderRadius.circular(tokens.radiusField);
  final fieldBorder = OutlineInputBorder(
    borderRadius: fieldRadius,
    borderSide: BorderSide(color: p.hairlineStrong),
  );

  final textTheme = base.textTheme
      .apply(bodyColor: p.text, displayColor: p.text)
      .copyWith(
        titleLarge: base.textTheme.titleLarge?.copyWith(
          color: p.text,
          fontWeight: FontWeight.w600,
        ),
        titleMedium: base.textTheme.titleMedium?.copyWith(
          color: p.text,
          fontWeight: FontWeight.w600,
        ),
        bodyMedium: base.textTheme.bodyMedium?.copyWith(
          color: p.text,
          height: 1.45,
        ),
        bodySmall: base.textTheme.bodySmall?.copyWith(color: p.muted),
        labelLarge: base.textTheme.labelLarge?.copyWith(
          color: p.text,
          fontWeight: FontWeight.w600,
        ),
      );

  final cardFill = p.panel.withValues(alpha: dark ? 0.78 : 0.88);

  return base.copyWith(
    scaffoldBackgroundColor: Colors.transparent,
    canvasColor: p.backdrop,
    textTheme: textTheme,
    iconTheme: IconThemeData(color: p.textSoft, size: 22),
    primaryIconTheme: IconThemeData(color: p.onAccent, size: 22),
    appBarTheme: AppBarTheme(
      backgroundColor: Colors.transparent,
      surfaceTintColor: Colors.transparent,
      foregroundColor: p.text,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        fontSize: 20,
        fontWeight: FontWeight.w600,
        color: p.text,
      ),
      iconTheme: IconThemeData(color: p.textSoft),
      actionsIconTheme: IconThemeData(color: p.textSoft),
      systemOverlayStyle: dark
          ? SystemUiOverlayStyle.light
          : SystemUiOverlayStyle.dark,
    ),
    cardTheme: CardThemeData(
      color: cardFill,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: const EdgeInsets.symmetric(vertical: 6, horizontal: 4),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(tokens.radiusCard),
        side: BorderSide(color: p.glassEdge, width: 0.5),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: p.panel.withValues(alpha: dark ? 0.62 : 0.72),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      hintStyle: TextStyle(color: p.muted),
      labelStyle: TextStyle(color: p.textSoft),
      floatingLabelStyle: TextStyle(color: p.accent),
      prefixIconColor: p.muted,
      suffixIconColor: p.muted,
      border: fieldBorder,
      enabledBorder: fieldBorder,
      focusedBorder: OutlineInputBorder(
        borderRadius: fieldRadius,
        borderSide: BorderSide(color: p.accent, width: 1),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: fieldRadius,
        borderSide: BorderSide(color: p.danger),
      ),
      focusedErrorBorder: OutlineInputBorder(
        borderRadius: fieldRadius,
        borderSide: BorderSide(color: p.danger, width: 1),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: p.accent,
        foregroundColor: p.onAccent,
        disabledBackgroundColor: p.panelStrong.withValues(alpha: 0.5),
        disabledForegroundColor: p.muted,
        elevation: 0,
        minimumSize: const Size(44, 44),
        shape: RoundedRectangleBorder(borderRadius: fieldRadius),
        textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
      ),
    ),
    elevatedButtonTheme: ElevatedButtonThemeData(
      style: ElevatedButton.styleFrom(
        backgroundColor: p.panelStrong,
        foregroundColor: p.text,
        elevation: 0,
        shadowColor: Colors.transparent,
        minimumSize: const Size(44, 44),
        shape: RoundedRectangleBorder(borderRadius: fieldRadius),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: p.text,
        minimumSize: const Size(44, 44),
        side: BorderSide(color: p.hairlineStrong),
        shape: RoundedRectangleBorder(borderRadius: fieldRadius),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: p.accent,
        minimumSize: const Size(44, 44),
        shape: RoundedRectangleBorder(borderRadius: fieldRadius),
      ),
    ),
    floatingActionButtonTheme: FloatingActionButtonThemeData(
      backgroundColor: p.accent,
      foregroundColor: p.onAccent,
      elevation: 2,
      focusElevation: 2,
      hoverElevation: 2,
      highlightElevation: 2,
      extendedTextStyle: const TextStyle(
        fontSize: 15,
        fontWeight: FontWeight.w600,
      ),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
    ),
    dividerTheme: DividerThemeData(color: p.hairline, thickness: 0.5, space: 1),
    drawerTheme: DrawerThemeData(
      backgroundColor: p.panel.withValues(alpha: 0.96),
      surfaceTintColor: Colors.transparent,
      scrimColor: Colors.black.withValues(alpha: 0.5),
      endShape: RoundedRectangleBorder(
        borderRadius: BorderRadius.horizontal(
          left: Radius.circular(tokens.radiusPanel),
        ),
      ),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.horizontal(
          right: Radius.circular(tokens.radiusPanel),
        ),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: p.panel.withValues(alpha: 0.98),
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(tokens.radiusPanel),
        side: BorderSide(color: p.glassEdge, width: 0.5),
      ),
      titleTextStyle: TextStyle(
        color: p.text,
        fontSize: 19,
        fontWeight: FontWeight.w600,
      ),
      contentTextStyle: TextStyle(color: p.textSoft, fontSize: 15),
    ),
    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: p.panel.withValues(alpha: 0.98),
      modalBackgroundColor: p.panel.withValues(alpha: 0.98),
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      modalElevation: 0,
      showDragHandle: false,
      dragHandleColor: p.hairlineStrong,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(
          top: Radius.circular(tokens.radiusSheet),
        ),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      backgroundColor: p.panelStrong,
      contentTextStyle: TextStyle(color: p.text, fontSize: 14),
      actionTextColor: p.accent,
      behavior: SnackBarBehavior.floating,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: p.hairlineStrong, width: 0.5),
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: p.panel.withValues(alpha: 0.7),
      selectedColor: p.accentSoft,
      disabledColor: p.panel.withValues(alpha: 0.4),
      side: BorderSide(color: p.hairline),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      labelStyle: TextStyle(color: p.textSoft, fontSize: 12),
      secondaryLabelStyle: TextStyle(color: p.text, fontSize: 12),
      checkmarkColor: p.accent,
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
    ),
    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
        (states) =>
            states.contains(WidgetState.selected) ? p.onAccent : p.muted,
      ),
      trackColor: WidgetStateProperty.resolveWith(
        (states) =>
            states.contains(WidgetState.selected) ? p.accent : p.panelStrong,
      ),
      trackOutlineColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected)
            ? Colors.transparent
            : p.hairlineStrong,
      ),
    ),
    checkboxTheme: CheckboxThemeData(
      fillColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected)
            ? p.accent
            : Colors.transparent,
      ),
      checkColor: WidgetStatePropertyAll(p.onAccent),
      side: BorderSide(color: p.hairlineStrong, width: 1.5),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(5)),
    ),
    radioTheme: RadioThemeData(
      fillColor: WidgetStateProperty.resolveWith(
        (states) => states.contains(WidgetState.selected) ? p.accent : p.muted,
      ),
    ),
    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: p.accent,
      linearTrackColor: p.hairline,
      circularTrackColor: p.hairline,
    ),
    scrollbarTheme: ScrollbarThemeData(
      thumbColor: WidgetStatePropertyAll(p.hairlineStrong),
      radius: const Radius.circular(8),
      thickness: const WidgetStatePropertyAll(6),
      crossAxisMargin: 2,
    ),
    textSelectionTheme: TextSelectionThemeData(
      cursorColor: p.accent,
      selectionColor: p.accentSoft,
      selectionHandleColor: p.accent,
    ),
    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(
        color: p.panelStrong,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: p.hairlineStrong, width: 0.5),
      ),
      textStyle: TextStyle(color: p.text, fontSize: 12),
      waitDuration: const Duration(milliseconds: 400),
    ),
    listTileTheme: ListTileThemeData(
      iconColor: p.textSoft,
      textColor: p.text,
      subtitleTextStyle: TextStyle(color: p.muted, fontSize: 13),
    ),
    popupMenuTheme: PopupMenuThemeData(
      color: p.panelStrong,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(tokens.radiusField),
        side: BorderSide(color: p.hairlineStrong, width: 0.5),
      ),
      textStyle: TextStyle(color: p.text, fontSize: 14),
    ),
    extensions: [tokens],
  );
}
