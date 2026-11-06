import 'package:flutter/cupertino.dart';
import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../ui/glass/glass_chrome.dart';
import '../ui/glass/glass_theme.dart';

// The glass design system lives in lib/ui/glass/. Re-exported here so screens
// keep a single import for chrome, surfaces, controls and tokens.
export '../ui/glass/glass_chrome.dart';
export '../ui/glass/glass_controls.dart';
export '../ui/glass/glass_surface.dart';
export '../ui/glass/glass_theme.dart';
export '../ui/glass/glass_tokens.dart';

/// The app bar's glass. Kept as its own widget (and its own type) because the
/// navigation tests assert on it; the blur itself lives in [GlassSurface].
class LabGlassSurface extends StatelessWidget {
  const LabGlassSurface({super.key});

  @override
  Widget build(BuildContext context) => const GlassAppBarSurface();
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

/// Per-screen app bar on glass.
///
/// There is deliberately no global navigation shell in this app: fifteen
/// screens build their own bar, and restyling this one widget is what changes
/// all of them. `flexibleSpace` must stay a [LabGlassSurface] instance.
class LabAppBar extends AppBar {
  LabAppBar({
    super.key,
    super.title,
    super.actions,
    Widget? leading,
    super.automaticallyImplyLeading,
    super.centerTitle,
    super.bottom,
    super.toolbarHeight,
    super.leadingWidth,
    String? fallbackLocation,
  }) : super(
         leading:
             leading ??
             (fallbackLocation == null
                 ? null
                 : LabBackButton(fallbackLocation: fallbackLocation)),
         flexibleSpace: const LabGlassSurface(),
         backgroundColor: Colors.transparent,
         surfaceTintColor: Colors.transparent,
         elevation: 0,
         scrolledUnderElevation: 0,
       );
}

/// A directly opened business page must also respond to Android system Back.
class LabPageFrame extends StatelessWidget {
  const LabPageFrame({
    super.key,
    required this.child,
    this.fallbackLocation = '/catalog',
  });
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

/// Theme entry points kept for the existing screens and tests.
///
/// [dark] is what the app ships; [light] stays complete so a screen pumped
/// under a light theme still renders with readable tokens.
class LabTheme {
  /// Compatibility constant for callers that paint their own page background
  /// (the router tests do). It mirrors `GlassPalette.dark`; the live background
  /// is [GlassBackdrop], which also carries the light sources.
  static const background = BoxDecoration(
    gradient: LinearGradient(
      begin: Alignment.topLeft,
      end: Alignment.bottomRight,
      colors: [Color(0xFF070809), Color(0xFF0B0D10), Color(0xFF0A1410)],
    ),
  );

  static ThemeData get light => buildGlassTheme(Brightness.light);

  static ThemeData get dark => buildGlassTheme(Brightness.dark);
}
