import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/labels.dart';
import 'package:lab_inventory_client/features/unified/models/session_scope.dart';
import 'package:lab_inventory_client/features/unified/providers/unified_providers.dart';
import 'package:lab_inventory_client/features/unified/screens/pending_receipt_screen.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';
import 'package:lab_inventory_client/features/unified/widgets/scan_input.dart';

import 'support/fake_lab_api.dart';

void main() {
  test(
    'pagination restores server queue and uses stable pending identity',
    () async {
      final fake = FakeLabApi(
        onCall: (path, params) async {
          if (path == LabApiRoutes.pendingList) {
            return {
              'records': [
                {
                  'id': params['cursor'] == null ? 5 : 4,
                  'trace_code': 'TRC-5',
                  'state': 'pending',
                  'quantity': 10,
                  'selected': true,
                },
              ],
              'cursor': params['cursor'] == null ? 5 : null,
            };
          }
          return {};
        },
      );
      final rows = await fake.client.pendingReceipts();
      expect(rows.map((r) => r.id), [5, 4]);
      expect(rows.first.payload, 'LABB:TRC-5');
      await fake.client.confirmPending({
        'request_key': 'stable-key',
        'pending_id': 5,
        'quantity': 10,
        'location_id': 2,
      });
      expect(fake.onlyParams(LabApiRoutes.pendingConfirm)['pending_id'], 5);
      expect(fake.countFor(LabApiRoutes.inventoryReceipt), 0);
    },
  );

  test('pending label defaults omit volatile location and quantity', () {
    final fields = LabelKind.pending.defaultFields;
    expect(
      fields,
      containsAll(['trace_code', 'mpn', 'name', 'package', 'parameters']),
    );
    expect(fields, isNot(contains('location')));
    expect(fields, isNot(contains('initial_quantity')));
    expect(LabelKind.pending.payloadPrefix, 'LABB:');
  });

  for (final brightness in Brightness.values) {
    for (final width in [320.0, 1280.0]) {
      testWidgets('prepare screen at $width $brightness with 200% text', (
        tester,
      ) async {
        tester.view.physicalSize = Size(width, 900);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final fake = FakeLabApi(
          onCall: (path, params) async => path == LabApiRoutes.pendingList
              ? {'records': []}
              : {'locations': []},
        );
        await tester.pumpWidget(
          ProviderScope(
            overrides: [
              labApiProvider.overrideWithValue(fake.client),
              sessionScopeSourceProvider.overrideWithValue(
                const LabSessionScope(uid: 7),
              ),
            ],
            child: MaterialApp(
              theme: ThemeData(brightness: brightness),
              home: MediaQuery(
                data: MediaQueryData(
                  size: Size(width, 900),
                  textScaler: const TextScaler.linear(2),
                ),
                child: const PendingReceiptScreen(),
              ),
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('先贴码，再上架'), findsOneWidget);
        expect(tester.takeException(), isNull);
        expect(fake.countFor(LabApiRoutes.inventoryReceipt), 0);
      });
    }
  }

  testWidgets('late queue response is discarded after account switch', (
    tester,
  ) async {
    final first = Completer<Map<String, dynamic>>();
    var calls = 0;
    final fake = FakeLabApi(
      onCall: (path, params) async => path == LabApiRoutes.pendingList
          ? (++calls == 1 ? first.future : {'records': []})
          : {'locations': []},
    );
    final container = ProviderContainer(
      overrides: [
        labApiProvider.overrideWithValue(fake.client),
        sessionScopeSourceProvider.overrideWithValue(
          const LabSessionScope(uid: 7),
        ),
      ],
    );
    addTearDown(container.dispose);
    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: PendingReceiptScreen()),
      ),
    );
    await tester.pump();
    container.read(companyScopeProvider.notifier).state = 'another-company';
    await tester.pump();
    first.complete({
      'records': [
        {'id': 9, 'name': 'previous-account-private-bag', 'state': 'pending'},
      ],
    });
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('previous-account-private-bag'), findsNothing);
  });

  testWidgets(
    'scan confirmation retries identical submission and returns to next scan',
    (tester) async {
      final output = Platform.environment['LAB_UI_EVIDENCE'];
      if (output != null) {
        await tester.runAsync(() async {
          final font = File(
            '../../server/ubuntu22.04/odoo_addons/lab_workflow/static/fonts/NotoSansSC-VF.ttf',
          );
          final loader = FontLoader('Evidence')
            ..addFont(
              Future.value(ByteData.sublistView(await font.readAsBytes())),
            );
          await loader.load();
          final icons = File(
            '../../dependencies/sdk/windows/flutter/bin/cache/artifacts/material_fonts/materialicons-regular.otf',
          );
          final iconLoader = FontLoader('MaterialIcons')
            ..addFont(
              Future.value(ByteData.sublistView(await icons.readAsBytes())),
            );
          await iconLoader.load();
        final cupertinoLoader = FontLoader('packages/cupertino_icons/CupertinoIcons')
          ..addFont(rootBundle.load('packages/cupertino_icons/assets/CupertinoIcons.ttf'));
        await cupertinoLoader.load();
        });
      }
      tester.view.physicalSize = const Size(390, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final record = {
        'id': 8,
        'trace_code': 'TRC-00008',
        'mpn': 'R-10K',
        'name': '贴片电阻',
        'package': '0603',
        'state': 'pending',
        'quantity': 100,
        'selected': true,
        'parameters': [
          {'name': '阻值', 'value': '10kΩ'},
        ],
      };
      var attempts = 0;
      final fake = FakeLabApi(
        onCall: (path, params) async {
          if (path == LabApiRoutes.pendingList)
            return {
              'records': [record],
            };
          if (path == LabApiRoutes.inventoryLocations)
            return {
              'locations': [
                {'id': 3, 'name': 'R01', 'code': 'K000003'},
              ],
            };
          if (path == LabApiRoutes.pendingResolve)
            return {
              'record': record,
              'recommendations': [
                {'id': 3, 'name': 'R01', 'reason': '相同器件'},
              ],
            };
          if (path == LabApiRoutes.pendingConfirm) {
            if (++attempts == 1) throw TimeoutException('模拟服务器已提交但响应丢失');
            return {
              'record': {...record, 'state': 'done'},
              'inventory_revision': 'after-receipt',
            };
          }
          throw StateError(path);
        },
      );
      final boundaryKey = GlobalKey();
      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            labApiProvider.overrideWithValue(fake.client),
            sessionScopeSourceProvider.overrideWithValue(
              const LabSessionScope(uid: 7),
            ),
          ],
          child: RepaintBoundary(
            key: boundaryKey,
            child: MaterialApp(
              theme: ThemeData(
                fontFamily: output == null ? null : 'Evidence',
                colorScheme: ColorScheme.fromSeed(
                  seedColor: const Color(0xFF007AFF),
                ),
              ),
              home: const PendingReceiptScreen(initialTab: 1),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      tester
          .widget<ScanInputField>(find.byType(ScanInputField).first)
          .onSubmit('LABB:TRC-00008');
      await tester.pumpAndSettle();
      await tester.tap(find.text('R01').first);
      await tester.pumpAndSettle();
      expect(fake.countFor(LabApiRoutes.pendingConfirm), 0);
      if (output != null) {
        await tester.runAsync(() async {
          final image =
              await (boundaryKey.currentContext!.findRenderObject()!
                      as RenderRepaintBoundary)
                  .toImage();
          final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
          await Directory(output).create(recursive: true);
          await File('$output/scan-confirm.png')
              .writeAsBytes(bytes!.buffer.asUint8List());
          image.dispose();
        });
      }
      await tester.ensureVisible(find.text('确认入库').first);
      await tester.tap(find.text('确认入库').first);
      await tester.pumpAndSettle();
      expect(find.textContaining('库位 K000003 · R01'), findsOneWidget);
      await tester.tap(find.text('确认入库').last);
      await tester.pumpAndSettle();
      expect(find.text('重试确认入库'), findsOneWidget);
      await tester.ensureVisible(find.text('重试确认入库'));
      await tester.tap(find.text('重试确认入库'));
      await tester.pumpAndSettle();
      final calls = fake.callsFor(LabApiRoutes.pendingConfirm);
      expect(calls.length, 2);
      expect(calls[0].params, calls[1].params);
      expect(find.textContaining('已入库，请扫描下一袋'), findsOneWidget);
      expect(fake.countFor(LabApiRoutes.inventoryReceipt), 0);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'manual preparation retries safely then reuses its archive for more bags',
    (tester) async {
      tester.view.physicalSize = const Size(390, 1100);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var creates = 0;
      final fake = FakeLabApi(
        onCall: (path, params) async {
          if (path == LabApiRoutes.pendingList) return {'records': []};
          if (path == LabApiRoutes.inventoryLocations) return {'locations': []};
          if (path == LabApiRoutes.pendingCreate) {
            if (++creates == 1) throw TimeoutException('模拟响应丢失');
            return {
              'records': [
                {
                  'id': 9,
                  'trace_code': 'TRC-9',
                  'item_key': 'lab:99',
                  'product_template_id': 99,
                  'name': '手工电阻',
                  'quantity': 10,
                  'state': 'pending',
                },
              ],
            };
          }
          throw StateError(path);
        },
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
      await tester.ensureVisible(find.text('资料库没有？新建器件'));
      await tester.tap(find.text('资料库没有？新建器件'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField).first, '手工电阻');
      await tester.ensureVisible(find.text('使用此器件'));
      await tester.tap(find.text('使用此器件'));
      await tester.pumpAndSettle();
      final quantity = find.byWidgetPredicate(
        (w) => w is TextField && w.decoration?.labelText == '每袋初始数量',
      );
      await tester.enterText(quantity, '10');
      await tester.ensureVisible(find.text('生成袋码并加入待打印'));
      await tester.tap(find.text('生成袋码并加入待打印'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.text('重试生成袋码'));
      await tester.tap(find.text('重试生成袋码'));
      await tester.pumpAndSettle();
      var calls = fake.callsFor(LabApiRoutes.pendingCreate);
      expect(calls[0].params, calls[1].params);
      await tester.ensureVisible(quantity);
      await tester.enterText(quantity, '15');
      await tester.ensureVisible(find.text('生成袋码并加入待打印'));
      await tester.tap(find.text('生成袋码并加入待打印'));
      await tester.pumpAndSettle();
      calls = fake.callsFor(LabApiRoutes.pendingCreate);
      expect(calls.length, 3);
      expect(calls.last.params['product_template_id'], 99);
      expect(calls.last.params['item_key'], 'lab:99');
      expect(calls.last.params.containsKey('material'), isFalse);
      expect(fake.countFor(LabApiRoutes.inventoryReceipt), 0);
    },
  );
}
