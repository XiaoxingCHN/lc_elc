import 'dart:ui' show ImageFilter;
import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

/// A bounded frosted surface: blur is restricted to the toolbar, never the list.
class LabGlassSurface extends StatelessWidget {
  const LabGlassSurface({super.key});
  @override
  Widget build(BuildContext context) {
    final contrast = MediaQuery.maybeOf(context)?.highContrast ?? false;
    return ClipRect(
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: contrast ? 0 : 18, sigmaY: contrast ? 0 : 18),
        child: DecoratedBox(
          decoration: BoxDecoration(
            color: Colors.white.withValues(alpha: contrast ? 1 : .76),
            border: const Border(bottom: BorderSide(color: Color(0x99FFFFFF))),
          ),
          child: const SizedBox.expand(),
        ),
      ),
    );
  }
}

class LabBackButton extends StatelessWidget {
  const LabBackButton({super.key, this.fallbackLocation = '/catalog'});
  final String fallbackLocation;
  static void goBack(BuildContext context, String fallbackLocation) {
    final router = GoRouter.maybeOf(context);
    if (router != null && router.canPop()) {
      router.pop();
    } else if (Navigator.of(context).canPop()) {
      Navigator.of(context).pop();
    } else if (router != null) {
      router.go(fallbackLocation);
    }
  }
  @override
  Widget build(BuildContext context) => IconButton(
    tooltip: '返回',
    icon: const Icon(CupertinoIcons.chevron_back, size: 23),
    onPressed: () => goBack(context, fallbackLocation),
  );
}

class LabAppBar extends AppBar {
  LabAppBar({super.key, super.title, super.actions, Widget? leading,
    super.automaticallyImplyLeading, super.centerTitle, super.bottom,
    super.toolbarHeight, super.leadingWidth, String? fallbackLocation})
    : super(
        leading: leading ?? (fallbackLocation == null ? null : LabBackButton(fallbackLocation: fallbackLocation)),
        flexibleSpace: const LabGlassSurface(),
        backgroundColor: Colors.transparent,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
      );
}

/// A directly opened business page must also respond to Android system Back.
class LabPageFrame extends StatelessWidget {
  const LabPageFrame({super.key, required this.child, this.fallbackLocation = '/catalog'});
  final Widget child;
  final String fallbackLocation;
  @override
  Widget build(BuildContext context) {
    final router = GoRouter.maybeOf(context);
    return PopScope<Object?>(
      canPop: router?.canPop() ?? Navigator.of(context).canPop(),
      onPopInvokedWithResult: (didPop, result) {
        if (!didPop) LabBackButton.goBack(context, fallbackLocation);
      },
      child: child,
    );
  }
}

class LabTheme {
  static const background = BoxDecoration(
    gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight,
      colors: [Color(0xFFEAF2FF), Color(0xFFF6F5FB), Color(0xFFE7F3F1)]),
  );
  static ThemeData get light {
    final scheme = ColorScheme.fromSeed(seedColor: const Color(0xFF007AFF),
      surface: const Color(0xFFF8FAFE), brightness: Brightness.light);
    final radius = BorderRadius.circular(16);
    return ThemeData(
      useMaterial3: true, colorScheme: scheme,
      scaffoldBackgroundColor: Colors.transparent,
      appBarTheme: const AppBarTheme(foregroundColor: Color(0xFF18263B),
        titleTextStyle: TextStyle(fontSize: 20, fontWeight: FontWeight.w600, color: Color(0xFF18263B)),
        centerTitle: false),
      cardTheme: CardThemeData(color: const Color(0xEFFFFFFF), elevation: 0,
        margin: const EdgeInsets.symmetric(vertical: 6, horizontal: 4),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22),
          side: const BorderSide(color: Color(0xCCFFFFFF)))),
      inputDecorationTheme: InputDecorationTheme(filled: true, fillColor: const Color(0xDCFFFFFF),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        border: OutlineInputBorder(borderRadius: radius, borderSide: const BorderSide(color: Color(0xFFD8E2EF))),
        enabledBorder: OutlineInputBorder(borderRadius: radius, borderSide: const BorderSide(color: Color(0xFFD8E2EF)))),
      filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(
        shape: RoundedRectangleBorder(borderRadius: radius), minimumSize: const Size(44,44))),
      elevatedButtonTheme: ElevatedButtonThemeData(style: ElevatedButton.styleFrom(
        shape: RoundedRectangleBorder(borderRadius: radius), elevation: 0, minimumSize: const Size(44,44))),
      outlinedButtonTheme: OutlinedButtonThemeData(style: OutlinedButton.styleFrom(
        shape: RoundedRectangleBorder(borderRadius: radius), minimumSize: const Size(44,44))),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: scheme.primary, foregroundColor: Colors.white, elevation: 3,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22))),
      dividerTheme: const DividerThemeData(color: Color(0xFFE1E7EF)),
      drawerTheme: const DrawerThemeData(backgroundColor: Color(0xF5F8FAFF)),
    );
  }
}
