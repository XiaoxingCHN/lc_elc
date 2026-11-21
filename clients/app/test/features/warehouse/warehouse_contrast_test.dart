import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/warehouse/widgets/stat_tile.dart';
import 'package:lab_inventory_client/ui/glass/glass_chrome.dart';
import 'package:lab_inventory_client/ui/glass/glass_tokens.dart';
import 'package:lab_inventory_client/widgets/lab_ui.dart';

/// WCAG relative luminance / contrast, computed here so the assertion does not
/// depend on a helper that could itself drift.
double _luminance(Color c) {
  double channel(double v) =>
      v <= 0.03928 ? v / 12.92 : math.pow((v + 0.055) / 1.055, 2.4).toDouble();
  return 0.2126 * channel(c.r) +
      0.7152 * channel(c.g) +
      0.0722 * channel(c.b);
}

double contrast(Color a, Color b) {
  final la = _luminance(a);
  final lb = _luminance(b);
  final hi = math.max(la, lb);
  final lo = math.min(la, lb);
  return (hi + 0.05) / (lo + 0.05);
}

/// Text over the fill a surface actually paints.
///
/// `GlassSurface` paints its base colour at `glassFill` / `glassFillProminent`
/// alpha over whatever is behind it, so the readable contrast is measured
/// against the COMPOSITE, not against the pure palette colour.
Color composite(Color fill, double alpha, Color behind) => Color.from(
      alpha: 1,
      red: fill.r * alpha + behind.r * (1 - alpha),
      green: fill.g * alpha + behind.g * (1 - alpha),
      blue: fill.b * alpha + behind.b * (1 - alpha),
    );

void main() {
  group('glass palette contrast (both themes)', () {
    for (final palette in <GlassPalette>[
      GlassPalette.dark,
      GlassPalette.light,
    ]) {
      final name = palette.brightness.name;

      test('$name: body text on the panel clears AA (4.5:1)', () {
        final panel = composite(palette.panel, 1.0, palette.backdrop);
        expect(contrast(palette.text, panel), greaterThanOrEqualTo(4.5));
        expect(contrast(palette.textSoft, panel), greaterThanOrEqualTo(4.5));
      });

      test('$name: muted hints still clear AA for small text', () {
        final panel = composite(palette.panel, 1.0, palette.backdrop);
        // `muted` is used for hints and captions at labelSmall - it must not be
        // the barely-visible grey that made the old cards unreadable.
        expect(contrast(palette.muted, panel), greaterThanOrEqualTo(4.5),
            reason: 'muted must stay legible, not decorative');
      });

      test('$name: onAccent on the accent fill clears AA', () {
        final fill = composite(
          palette.accent,
          palette.glassFillProminent,
          palette.backdrop,
        );
        expect(contrast(palette.onAccent, fill), greaterThanOrEqualTo(4.5));
      });

      test('$name: onSurface text would NOT be legible on that fill', () {
        // This is the exact combination the 作业 cards shipped with, and why
        // they were unreadable. Pinned so nobody re-introduces it.
        final fill = composite(
          palette.accent,
          palette.glassFillProminent,
          palette.backdrop,
        );
        expect(contrast(palette.text, fill), lessThan(4.5),
            reason: 'this is why a prominent card may never use onSurface text');
      });
    }
  });

  group('NavCard', () {
    Future<void> pump(WidgetTester tester, {bool enabled = true}) async {
      tester.view.physicalSize = const Size(900, 1200);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        MaterialApp(
          theme: LabTheme.dark,
          home: Scaffold(
            body: Center(
              child: SizedBox(
                width: 520,
                child: NavCard(
                  title: '入库',
                  subtitle: '制袋贴标 · 扫码上架 · 直接入库',
                  icon: Icons.qr_code_scanner,
                  enabled: enabled,
                  disabledReason: '当前账号没有入库权限，请联系库存管理员。',
                  onTap: () {},
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('never paints a prominent (accent-filled) panel', (tester) async {
      await pump(tester);

      final panels = tester.widgetList<GlassPanel>(find.byType(GlassPanel));
      expect(panels, isNotEmpty);
      for (final panel in panels) {
        expect(panel.prominent, isFalse,
            reason: 'GlassSurface documents "at most one prominent per screen"; '
                'a list of them put onSurface text on a lime fill (1.2:1)');
      }
    });

    testWidgets('title and subtitle stay readable', (tester) async {
      await pump(tester);
      final palette = GlassPalette.dark;
      final panel = composite(palette.panel, 1.0, palette.backdrop);

      final title = tester.widget<Text>(find.text('入库'));
      expect(contrast(title.style!.color!, panel), greaterThanOrEqualTo(4.5));

      final subtitle =
          tester.widget<Text>(find.text('制袋贴标 · 扫码上架 · 直接入库'));
      expect(contrast(subtitle.style!.color!, panel),
          greaterThanOrEqualTo(4.5));
    });

    testWidgets('a disabled card still explains itself in readable text',
        (tester) async {
      await pump(tester, enabled: false);
      final palette = GlassPalette.dark;
      final panel = composite(palette.panel, 1.0, palette.backdrop);

      final reason =
          tester.widget<Text>(find.text('当前账号没有入库权限，请联系库存管理员。'));
      expect(contrast(reason.style!.color!, panel), greaterThanOrEqualTo(4.5));
    });
  });
}
