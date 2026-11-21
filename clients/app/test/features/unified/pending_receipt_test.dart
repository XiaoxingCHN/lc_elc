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
import 'package:lab_inventory_client/features/unified/widgets/catalog_suggest_search.dart';
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

  test('queue filters are sent to the server, not applied locally', () async {
    FakeLabApi fake() => FakeLabApi(
      onCall: (path, params) async => path == LabApiRoutes.pendingList
          ? <String, dynamic>{'records': <Map<String, dynamic>>[], 'cursor': null}
          : <String, dynamic>{},
    );

    final filtered = fake();
    await filtered.client.pendingReceipts(query: ' 10R ', state: 'done');
    final sent = filtered.onlyParams(LabApiRoutes.pendingList);
    expect(sent['query'], '10R');
    expect(sent['state'], 'done');
    expect(sent.containsKey('cursor'), isFalse);

    // No filters -> no filter keys, so old servers keep their behavior.
    final unfiltered = fake();
    await unfiltered.client.pendingReceipts();
    final plain = unfiltered.onlyParams(LabApiRoutes.pendingList);
    expect(plain.containsKey('query'), isFalse);
    expect(plain.containsKey('state'), isFalse);
  });

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

  testWidgets('a zero-result search fetches from LCSC inside the form', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    Map<String, dynamic> status(String state, {String message = ''}) {
      return <String, dynamic>{
        'request_id': 11,
        'state': state,
        'query': 'C32445874',
        'query_kind': 'c_code',
        'catalog_code': state == 'done' ? 'C32445874' : '',
        'item_key': state == 'done' ? 'lcsc:C32445874' : '',
        'message': message,
        'candidates': <Map<String, dynamic>>[],
      };
    }

    final fake = FakeLabApi(
      onCall: (path, params) async {
        switch (path) {
          case LabApiRoutes.pendingList:
            return <String, dynamic>{'records': <Map<String, dynamic>>[]};
          case LabApiRoutes.catalogSearch:
            return <String, dynamic>{
              'items': <Map<String, dynamic>>[],
              'total': 0,
              'fetch_suggestion': <String, dynamic>{
                'kind': 'c_code',
                'query': 'C32445874',
                'can_fetch': true,
                'message': '本地库暂无该 C 编号，可立即从立创商城抓取。',
              },
            };
          case LabApiRoutes.catalogFetch:
            return status('queued');
          case LabApiRoutes.catalogFetchStatus:
            return status('done', message: '已收录，正在刷新。');
          case LabApiRoutes.inventoryLocations:
            return <String, dynamic>{'locations': <Map<String, dynamic>>[]};
          default:
            throw StateError(path);
        }
      },
    );
    addTearDown(fake.calls.clear);

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

    final field = find.descendant(
      of: find.byType(CatalogSuggestField),
      matching: find.byType(TextField),
    );
    await tester.enterText(field, 'C32445874');
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 260));
    await tester.pump();

    expect(find.text('立即从立创商城抓取'), findsOneWidget);
    await tester.tap(find.text('立即从立创商城抓取'));
    await tester.pump();
    await tester.pump();

    final fetch = fake.onlyParams(LabApiRoutes.catalogFetch);
    expect(fetch['query'], 'C32445874');
    expect(fetch.containsKey('refresh'), isFalse);
    expect(find.text('已加入抓取队列'), findsOneWidget);

    await tester.pump(const Duration(seconds: 1));
    await tester.pump();
    await tester.pump();
    expect(find.text('已抓取并入库'), findsOneWidget);
    expect(find.text('已收录，正在刷新。'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'scan the shelf ONCE, then keep scanning bags into it',
    (tester) async {
      // The operator's flow chart: 扫描库位二维码 -> 是 -> 录库界面 -> 连续扫袋码.
      // A bag scan must never clear the chosen shelf, or the operator is forced
      // back to the location scan for every single bag.
      final fake = FakeLabApi(
        onCall: (path, params) async {
          if (path == LabApiRoutes.pendingList) return {'records': []};
          if (path == LabApiRoutes.inventoryLocations) {
            return {
              'locations': [
                {'id': 17, 'code': 'K000004', 'name': 'R1', 'path': 'WH/库存/R区/R1'},
              ],
            };
          }
          if (path == LabApiRoutes.inventoryResolveCode) {
            final raw = (params['raw'] ?? '').toString();
            if (raw.startsWith('LABL:')) {
              return {
                'kind': 'location',
                'location': {
                  'id': 17,
                  'code': 'K000004',
                  'name': 'R1',
                  'path': 'WH/库存/R区/R1',
                },
              };
            }
            return {
              'kind': 'bag',
              'bag': {
                'id': 42,
                'trace_code': raw,
                'location_id': 17,
                'location_code': 'K000004',
                'quantity': 100.0,
              },
              'item_key': 'lab:99',
            };
          }
          if (path == LabApiRoutes.pendingResolve) {
            return {
              'record': {
                'id': 7,
                'trace_code': (params['raw'] ?? '').toString(),
                'name': 'GH1.25 端子 3P',
                'quantity': 100,
                'state': 'pending',
              },
              'recommendations': [],
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
          child: const MaterialApp(home: PendingReceiptScreen(initialTab: 1)),
        ),
      );
      await tester.pumpAndSettle();

      // Step 1: the screen asks for the shelf, not a bag.
      expect(find.text('第 1 步 · 扫描库位码'), findsOneWidget);

      await tester.enterText(find.byType(TextField).first, 'LABL:K000004');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pumpAndSettle();

      // The shelf is now sticky and the field switched to bag mode.
      expect(find.textContaining('入库库位：K000004'), findsOneWidget);
      expect(find.text('扫描袋追溯码'), findsOneWidget);

      // Step 2: a bag scan resolves the bag and must NOT clear the shelf.
      await tester.enterText(find.byType(TextField).first, 'TRC00000001');
      await tester.testTextInput.receiveAction(TextInputAction.done);
      await tester.pumpAndSettle();

      expect(find.textContaining('入库库位：K000004'), findsOneWidget,
          reason: '扫描袋码后库位必须保留，否则每袋都要重扫库位');
      expect(find.text('第 1 步 · 扫描库位码'), findsNothing);
    },
  );
}
