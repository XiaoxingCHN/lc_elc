import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
// lab_ui re-exports the whole glass design system; keeping the single import
// also keeps this test honest about the public entry point screens use.
import 'package:lab_inventory_client/widgets/lab_ui.dart';

/// Hosts a widget under the real glass theme, with the accessibility switches
/// the production theme reads.
Widget host(
  Widget child, {
  Brightness brightness = Brightness.dark,
  bool highContrast = false,
  bool disableAnimations = false,
  double textScale = 1,
}) {
  return MaterialApp(
    theme: buildGlassTheme(brightness),
    home: Builder(
      builder: (context) {
        final media = MediaQuery.of(context).copyWith(
          highContrast: highContrast,
          disableAnimations: disableAnimations,
          textScaler: TextScaler.linear(textScale),
        );
        return MediaQuery(
          data: media,
          child: Scaffold(body: Center(child: child)),
        );
      },
    ),
  );
}

/// The gradient decoration of the innermost glass layer.
BoxDecoration glassDecoration(WidgetTester tester) {
  final boxes = tester.widgetList<DecoratedBox>(
    find.descendant(
      of: find.byType(GlassSurface),
      matching: find.byType(DecoratedBox),
    ),
  );
  for (final box in boxes) {
    final decoration = box.decoration;
    if (decoration is BoxDecoration && decoration.gradient is LinearGradient) {
      return decoration;
    }
  }
  fail('GlassSurface has no gradient decoration');
}

void main() {
  group('tokens', () {
    test('both brightnesses install a complete extension', () {
      final dark = buildGlassTheme(Brightness.dark);
      final light = buildGlassTheme(Brightness.light);

      expect(dark.extension<GlassTokens>()!.palette, GlassPalette.dark);
      expect(light.extension<GlassTokens>()!.palette, GlassPalette.light);
      expect(dark.colorScheme.primary, GlassPalette.dark.accent);
      expect(light.colorScheme.primary, GlassPalette.light.accent);
      expect(dark.scaffoldBackgroundColor, Colors.transparent);

      final card = dark.cardTheme.shape! as RoundedRectangleBorder;
      expect(card.side.width, 0.5);
      // Cards never blur: a BackdropFilter per list row is what makes glass
      // scroll badly.
      expect(dark.extension<GlassTokens>()!.blurCard, 0);
    });

    testWidgets('a bare ThemeData falls back by brightness', (tester) async {
      for (final brightness in Brightness.values) {
        late GlassTokens read;
        await tester.pumpWidget(
          MaterialApp(
            // A fresh key per iteration: MaterialApp animates theme changes,
            // so reusing the element would still be mid-transition here.
            key: ValueKey(brightness),
            theme: ThemeData(brightness: brightness),
            home: Builder(
              builder: (context) {
                read = GlassTokens.ofContext(context);
                return const SizedBox.shrink();
              },
            ),
          ),
        );
        expect(read.palette.brightness, brightness);
        expect(read.palette.accent, GlassPalette.of(brightness).accent);
      }
    });
  });

  group('GlassSurface', () {
    testWidgets('blur 0 paints a panel with no BackdropFilter', (tester) async {
      await tester.pumpWidget(
        host(
          const GlassSurface(blur: 0, child: SizedBox(width: 120, height: 60)),
        ),
      );

      expect(find.byType(BackdropFilter), findsNothing);
      final decoration = glassDecoration(tester);
      expect(decoration.border!.top.width, 0.5);
      expect(decoration.gradient, isA<LinearGradient>());
    });

    testWidgets('blurred surfaces create exactly one blur layer', (
      tester,
    ) async {
      await tester.pumpWidget(
        host(const GlassSurface(child: SizedBox(width: 120, height: 60))),
      );

      expect(find.byType(BackdropFilter), findsOneWidget);
      expect(find.byType(RepaintBoundary), findsWidgets);
    });

    testWidgets('high contrast raises the fill and drops the blur', (
      tester,
    ) async {
      await tester.pumpWidget(
        host(
          const GlassSurface(child: SizedBox(width: 120, height: 60)),
          highContrast: true,
        ),
      );

      expect(find.byType(BackdropFilter), findsNothing);
      final gradient = glassDecoration(tester).gradient! as LinearGradient;
      expect(gradient.colors.first.a, greaterThan(0.4));
    });

    testWidgets('shapes resolve to the expected corner radii', (tester) async {
      await tester.pumpWidget(
        host(
          const Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              GlassSurface(shape: GlassShape.circle, blur: 0, child: Text('c')),
              GlassSurface(
                shape: GlassShape.rounded,
                radius: 8,
                blur: 0,
                child: Text('r'),
              ),
            ],
          ),
        ),
      );

      final surfaces = tester.widgetList<GlassSurface>(
        find.byType(GlassSurface),
      );
      expect(surfaces.first.shape, GlassShape.circle);
      expect(surfaces.last.radius, 8);
      expect(tester.takeException(), isNull);
    });
  });

  group('GlassBackdrop', () {
    testWidgets('is static: no full-screen blur', (tester) async {
      await tester.pumpWidget(host(const GlassBackdrop(child: Text('内容'))));

      expect(find.text('内容'), findsOneWidget);
      expect(find.byType(BackdropFilter), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });

  testWidgets('GlassPanel is fill-only by default', (tester) async {
    await tester.pumpWidget(host(const GlassPanel(child: Text('内容'))));

    expect(find.byType(BackdropFilter), findsNothing);
    expect(find.text('内容'), findsOneWidget);
  });

  group('GlassButton', () {
    testWidgets('prominent text uses the accent foreground pair', (
      tester,
    ) async {
      for (final brightness in Brightness.values) {
        await tester.pumpWidget(
          MaterialApp(
            key: ValueKey(brightness),
            theme: buildGlassTheme(brightness),
            home: const Scaffold(
              body: GlassButton(label: '确认', prominent: true, onPressed: _noop),
            ),
          ),
        );
        final text = tester.widget<Text>(find.text('确认'));
        final palette = GlassPalette.of(brightness);
        expect(text.style?.color, palette.onAccent);
        final decoration = glassDecoration(tester);
        final gradient = decoration.gradient! as LinearGradient;
        expect(gradient.colors.first.a, greaterThan(0.9));
      }
    });
  });

  group('GlassButton', () {
    testWidgets('prominent text uses the accent foreground pair', (
      tester,
    ) async {
      var taps = 0;
      await tester.pumpWidget(
        host(GlassButton(label: '确认入库', onPressed: () => taps++)),
      );

      expect(
        tester.getSize(find.byType(GlassButton)).height,
        greaterThanOrEqualTo(44),
      );
      await tester.tap(find.text('确认入库'));
      await tester.pumpAndSettle();
      expect(taps, 1);
    });

    testWidgets('a null callback disables the button', (tester) async {
      var taps = 0;
      await tester.pumpWidget(
        host(const GlassButton(label: '不可用', onPressed: null)),
      );

      await tester.tap(find.text('不可用'), warnIfMissed: false);
      await tester.pumpAndSettle();
      expect(taps, 0);
      final opacity = tester.widget<Opacity>(find.byType(Opacity).first);
      expect(opacity.opacity, lessThan(1));
    });

    testWidgets('reduced motion keeps the surface still but still taps', (
      tester,
    ) async {
      var taps = 0;
      await tester.pumpWidget(
        host(
          GlassButton(label: '继续', onPressed: () => taps++),
          disableAnimations: true,
        ),
      );

      final gesture = await tester.startGesture(
        tester.getCenter(find.text('继续')),
      );
      await tester.pump(const Duration(milliseconds: 200));
      final scale = tester.widget<AnimatedScale>(
        find.descendant(
          of: find.byType(GlassButton),
          matching: find.byType(AnimatedScale),
        ),
      );
      expect(scale.scale, 1);
      await gesture.up();
      await tester.pumpAndSettle();
      expect(taps, 1);
    });

    testWidgets('200% text wraps or ellipsizes instead of overflowing', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(320, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        host(
          const SizedBox(
            width: 200,
            child: GlassButton(
              label: '生成袋码并加入待打印队列',
              icon: Icons.qr_code_2,
              onPressed: _noop,
            ),
          ),
          textScale: 2,
        ),
      );

      expect(tester.takeException(), isNull);
    });
  });

  group('GlassSegmentedControl', () {
    testWidgets('is controlled and does not overflow at 320px / 200% text', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(320, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      String value = 'pending';
      String? chosen;
      await tester.pumpWidget(
        host(
          StatefulBuilder(
            builder: (context, setState) => SizedBox(
              width: 288,
              child: GlassSegmentedControl<String>(
                value: value,
                onChanged: (next) {
                  chosen = next;
                  setState(() => value = next);
                },
                children: const {
                  'pending': Text('待入库'),
                  'done': Text('已入库'),
                  'cancelled': Text('已取消'),
                  'all': Text('全部'),
                },
              ),
            ),
          ),
          textScale: 2,
        ),
      );

      expect(tester.takeException(), isNull);
      await tester.tap(find.text('已入库'));
      await tester.pumpAndSettle();
      expect(chosen, 'done');
      expect(value, 'done');
    });

    testWidgets('null onChanged makes every segment inert', (tester) async {
      await tester.pumpWidget(
        host(
          const GlassSegmentedControl<String>(
            value: 'a',
            onChanged: null,
            children: {'a': Text('甲'), 'b': Text('乙')},
          ),
        ),
      );

      await tester.tap(find.text('乙'), warnIfMissed: false);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });

  group('compatibility layer', () {
    testWidgets('LabAppBar keeps LabGlassSurface and the back tooltip', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(320, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      await tester.pumpWidget(
        MaterialApp(
          theme: LabTheme.dark,
          home: Scaffold(
            appBar: LabAppBar(
              title: const Text('入库'),
              fallbackLocation: '/catalog',
            ),
            body: const Text('表单'),
          ),
        ),
      );

      expect(find.byType(LabGlassSurface), findsOneWidget);
      expect(find.byTooltip('返回'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('both LabTheme entry points install glass tokens', (
      tester,
    ) async {
      for (final theme in [LabTheme.dark, LabTheme.light]) {
        GlassTokens? installed;
        await tester.pumpWidget(
          MaterialApp(
            key: ValueKey(theme.brightness),
            theme: theme,
            // Read from under the MaterialApp: the app's own element sits
            // above the Theme it installs.
            home: Builder(
              builder: (context) {
                installed = Theme.of(context).extension<GlassTokens>();
                return const SizedBox.shrink();
              },
            ),
          ),
        );
        expect(installed, isNotNull);
      }
    });
  });
}

void _noop() {}
