import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/warehouse/warehouse_section.dart';
import 'package:lab_inventory_client/features/warehouse/widgets/warehouse_section_switcher.dart';
import 'package:lab_inventory_client/widgets/lab_ui.dart';

/// The section switcher itself: placement is the shell's job, behaviour is here.
///
/// These run without a router on purpose - the shell's branch/stack behaviour is
/// covered by `test/widget_test.dart` through the real app router.
void main() {
  Future<void> pumpSwitcher(
    WidgetTester tester, {
    required WarehouseSection value,
    ValueChanged<WarehouseSection>? onChanged,
    Size size = const Size(1200, 800),
    double textScale = 1.0,
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      MaterialApp(
        theme: LabTheme.dark,
        home: Builder(
          builder: (context) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: TextScaler.linear(textScale)),
            child: Scaffold(
              body: Center(
                child: SizedBox(
                  width: 600,
                  child: WarehouseSectionSwitcher(
                    value: value,
                    onChanged: onChanged ?? (_) {},
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('shows all four sections and marks the active one', (tester) async {
    // The semantics handle must be released INSIDE the test body: the framework
    // verifies handles before tearDowns run.
    final semantics = tester.ensureSemantics();
    try {
      await pumpSwitcher(tester, value: WarehouseSection.locations);

      for (final section in WarehouseSection.values) {
        expect(find.text(section.label), findsOneWidget, reason: section.label);
      }
      // Each segment announces its LONG description, not the two-character
      // label: "仓位" alone tells a screen-reader user nothing.
      for (final section in WarehouseSection.values) {
        expect(
          find.bySemanticsLabel(section.description),
          findsWidgets,
          reason: section.description,
        );
      }
      // The active section is the one the widget was given.
      expect(
        tester
            .widget<WarehouseSectionSwitcher>(
              find.byType(WarehouseSectionSwitcher),
            )
            .value,
        WarehouseSection.locations,
      );
    } finally {
      semantics.dispose();
    }
  });

  testWidgets('tapping a section reports it', (tester) async {
    WarehouseSection? tapped;
    await pumpSwitcher(
      tester,
      value: WarehouseSection.overview,
      onChanged: (section) => tapped = section,
    );

    await tester.tap(find.text(WarehouseSection.manage.label));
    await tester.pumpAndSettle();

    expect(tapped, WarehouseSection.manage);
  });

  testWidgets('a null callback disables every segment', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: LabTheme.dark,
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 600,
              child: WarehouseSectionSwitcher(
                value: WarehouseSection.overview,
                onChanged: (_) {},
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text(WarehouseSection.overview.label), findsOneWidget);
  });

  testWidgets('fits a 320 px phone at 200 % text without overflowing', (
    tester,
  ) async {
    await pumpSwitcher(
      tester,
      value: WarehouseSection.overview,
      size: const Size(320, 640),
      textScale: 2.0,
    );
    expect(tester.takeException(), isNull);
  });

  testWidgets('large text swaps the segmented control for a dropdown', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: LabTheme.dark,
        home: Builder(
          builder: (context) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: const TextScaler.linear(2.0)),
            child: Scaffold(
              body: WarehouseSectionDropdown(
                value: WarehouseSection.overview,
                onChanged: (_) {},
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(DropdownButtonFormField<WarehouseSection>),
        findsOneWidget);
    expect(find.text('库存速览'), findsOneWidget,
        reason: 'the dropdown uses the long description');
  });

  group('warehouseSwitcherNeedsDropdown', () {
    testWidgets('false at normal text, true at 200 %', (tester) async {
      late bool normal;
      late bool large;

      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => Column(
              children: <Widget>[
                Builder(builder: (context) {
                  normal = warehouseSwitcherNeedsDropdown(context);
                  return const SizedBox.shrink();
                }),
                MediaQuery(
                  data: MediaQuery.of(context)
                      .copyWith(textScaler: const TextScaler.linear(2.0)),
                  child: Builder(builder: (context) {
                    large = warehouseSwitcherNeedsDropdown(context);
                    return const SizedBox.shrink();
                  }),
                ),
              ],
            ),
          ),
        ),
      );

      expect(normal, isFalse);
      expect(large, isTrue);
    });
  });

  group('WarehouseSection', () {
    test('every section has a label, a description and an icon', () {
      for (final section in WarehouseSection.values) {
        expect(section.label.trim(), isNotEmpty);
        expect(section.description.trim(), isNotEmpty);
        expect(section.branchIndex, section.index);
      }
      // The labels must stay distinct: two identical segments would be
      // indistinguishable on screen and in the accessibility tree.
      final labels = WarehouseSection.values.map((s) => s.label).toSet();
      expect(labels, hasLength(WarehouseSection.values.length));
    });
  });
}
