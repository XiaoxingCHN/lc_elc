import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/providers/unified_providers.dart';
import 'package:lab_inventory_client/features/unified/widgets/item_picker.dart';
import 'package:lab_inventory_client/features/unified/screens/pending_receipt_screen.dart';
import 'package:lab_inventory_client/features/unified/models/session_scope.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';

import 'support/fake_lab_api.dart';

void main() {
  testWidgets(
    'opening picker keeps header and first catalog row inside dialog',
    (tester) async {
      tester.view.physicalSize = const Size(393, 852);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final fake = FakeLabApi(
        onCall: (path, params) async => {
          'items': [
            itemJson(itemKey: 'catalog:C100001', catalogCode: 'C100001'),
          ],
          'total': 1,
        },
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [labApiProvider.overrideWithValue(fake.client)],
          child: MaterialApp(
            home: Scaffold(
              body: Builder(
                builder: (context) => TextButton(
                  onPressed: () => ItemPickerDialog.show(context),
                  child: const Text('打开选择器'),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('打开选择器'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.textContaining('C100001'), findsOneWidget);
      final dialog = tester.getRect(find.byType(Dialog));
      final search = tester.getRect(find.byType(TextField));
      expect(dialog.contains(search.center), isTrue);
      expect(find.textContaining('C100001').hitTestable(), findsOneWidget);
    },
  );
  for (final scenario in [
    (const Size(320, 852), 2.0, 300.0, Brightness.light),
    (const Size(320, 852), 2.0, 300.0, Brightness.dark),
    (const Size(800, 393), 1.0, 0.0, Brightness.light),
    (const Size(1280, 900), 2.0, 0.0, Brightness.dark),
  ]) {
    testWidgets('picker list and custom action survive $scenario', (
      tester,
    ) async {
      tester.view.physicalSize = scenario.$1;
      tester.view.devicePixelRatio = 1;
      tester.view.viewInsets = FakeViewPadding(bottom: scenario.$3);
      addTearDown(tester.view.reset);
      final fake = FakeLabApi(
        onCall: (path, params) async => {
          'items': [
            itemJson(itemKey: 'catalog:C100001', catalogCode: 'C100001'),
          ],
          'total': 1,
        },
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [labApiProvider.overrideWithValue(fake.client)],
          child: MaterialApp(
            theme: ThemeData(brightness: scenario.$4),
            builder: (context, child) => MediaQuery(
              data: MediaQuery.of(context)
                  .copyWith(textScaler: TextScaler.linear(scenario.$2)),
              child: child!,
            ),
            home: Scaffold(
              body: Builder(
                builder: (context) => TextButton(
                  onPressed: () =>
                      ItemPickerDialog.show(context, onCreate: () async {}),
                  child: const Text('打开选择器'),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('打开选择器'));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      expect(find.text('自定义 / 新建器件').hitTestable(), findsOneWidget);
      expect(find.textContaining('C100001').hitTestable(), findsOneWidget);
      await tester.tap(find.byTooltip('关闭'));
      await tester.pumpAndSettle();
    });
  }

  testWidgets(
    'catalog search, failure retry and row selection use server results',
    (tester) async {
      var fail = true;
      final fake = FakeLabApi(
        onCall: (path, params) async {
          if (fail) throw businessFailure('NETWORK_ERROR', '资料读取失败');
          return {
            'items': [
              itemJson(itemKey: 'catalog:C100001', catalogCode: 'C100001'),
            ],
            'total': 1,
          };
        },
      );
      String? selected;
      await tester.pumpWidget(
        ProviderScope(
          overrides: [labApiProvider.overrideWithValue(fake.client)],
          child: MaterialApp(
            home: Scaffold(
              body: Builder(
                builder: (context) => TextButton(
                  onPressed: () async =>
                      selected = (await ItemPickerDialog.show(context))
                          ?.itemKey,
                  child: const Text('打开选择器'),
                ),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('打开选择器'));
      await tester.pumpAndSettle();
      expect(find.text('重试').hitTestable(), findsOneWidget);
      fail = false;
      await tester.tap(find.text('重试'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), 'C100001');
      await tester.testTextInput.receiveAction(TextInputAction.search);
      await tester.pumpAndSettle();
      expect(fake.calls.last.params['query'], 'C100001');
      await tester.tap(
        find.descendant(
          of: find.byType(ListTile),
          matching: find.textContaining('C100001'),
        ),
      );
      await tester.pumpAndSettle();
      expect(selected, 'lcsc:C100001');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'receipt opens custom form from picker and returns chosen material',
    (tester) async {
      final fake = FakeLabApi(
        onCall: (path, params) async => path == LabApiRoutes.pendingList
            ? {'records': []}
            : {'items': [], 'total': 0},
      );
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            labApiProvider.overrideWithValue(fake.client),
            sessionScopeSourceProvider.overrideWithValue(
              const LabSessionScope(uid: 7),
            ),
          ],
          child: const MaterialApp(home: PendingReceiptScreen()),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('选择元器件'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('自定义 / 新建器件'));
      await tester.pumpAndSettle();
      expect(find.byType(ItemPickerDialog), findsNothing);
      expect(find.text('新建器件'), findsOneWidget);
      await tester.enterText(find.byType(TextFormField).first, '自制传感器');
      await tester.ensureVisible(find.text('使用此器件'));
      await tester.tap(find.text('使用此器件'));
      await tester.pumpAndSettle();
      expect(find.text('自制传感器'), findsOneWidget);
      expect(fake.countFor(LabApiRoutes.pendingCreate), 0);
      expect(tester.takeException(), isNull);
    },
  );
}
