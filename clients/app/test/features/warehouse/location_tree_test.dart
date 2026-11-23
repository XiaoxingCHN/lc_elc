import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/detail_models.dart';
import 'package:lab_inventory_client/features/unified/models/inventory.dart';
import 'package:lab_inventory_client/features/unified/providers/inventory_providers.dart';
import 'package:lab_inventory_client/features/warehouse/screens/location_overview_screen.dart';
import 'package:lab_inventory_client/models/lab_api_exception.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';
import 'package:lab_inventory_client/widgets/lab_ui.dart';

import '../unified/support/fake_lab_api.dart';

/// The location hierarchy: server contract, idempotent move, and the screen.
///
/// The contract under test is `/lab/api/inventory/locations` with
/// `with_tree: true` and `/lab/api/inventory/location_update` with
/// `update_parent: true`. Everything here is a fake transport on top of the REAL
/// serialisation and the REAL parsing, so a payload regression fails the test.
void main() {
  // ---------------------------------------------------------------- contract

  group('locationsTree', () {
    test('asks for the tree and splits locations from view folders', () async {
      final fake = FakeLabApi();
      fake.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.inventoryLocations: <String, dynamic>{
          'locations': <Map<String, dynamic>>[
            <String, dynamic>{
              'id': 4,
              'code': 'K000899',
              'name': 'M(1,1)',
              'path': 'WH/库存/M区/M(1,1)',
              'usage': 'internal',
              'parent_id': 3,
              'bag_count': 2,
              'quantity': 12,
            },
          ],
          'ancestors': <Map<String, dynamic>>[
            <String, dynamic>{
              'id': 1,
              'name': 'WH',
              'path': 'WH',
              'usage': 'view',
              'parent_id': false,
            },
            <String, dynamic>{
              'id': 3,
              'name': 'M区',
              'path': 'WH/库存/M区',
              'usage': 'internal',
              'parent_id': 1,
            },
          ],
        },
      });

      final tree = await fake.client.locationsTree(withStats: true);

      expect(
        fake.onlyParams(LabApiRoutes.inventoryLocations),
        <String, dynamic>{'with_stats': true, 'with_tree': true},
      );
      expect(tree.locations.single.parentId, 3);
      expect(tree.locations.single.bagCount, 2);
      expect(tree.ancestors.map((row) => row.name), <String>['WH', 'M区']);
      expect(tree.ancestors.first.isView, isTrue);
      expect(tree.ancestors.first.hierarchyKnown, isTrue);
      expect(tree.hierarchy, isTrue);
    });

    test(
      'an older host without parent_id is reported as a flat answer',
      () async {
        final fake = FakeLabApi();
        fake.answerWith(<String, Map<String, dynamic>>{
          LabApiRoutes.inventoryLocations: <String, dynamic>{
            'locations': <Map<String, dynamic>>[
              <String, dynamic>{
                'id': 4,
                'code': 'K1',
                'name': 'R01',
                'path': 'R01',
              },
            ],
          },
        });

        final tree = await fake.client.locationsTree();
        expect(tree.hierarchy, isFalse);
        expect(tree.ancestors, isEmpty);
      },
    );
  });

  group('updateLocationParent', () {
    test(
      'sends update_parent, the key and an explicit false for the root',
      () async {
        final fake = FakeLabApi();
        fake.answerWith(<String, Map<String, dynamic>>{
          LabApiRoutes.inventoryLocationUpdate: <String, dynamic>{
            'location': <String, dynamic>{
              'id': 4,
              'name': 'R01',
              'parent_id': false,
            },
          },
        });

        await fake.client.updateLocationParent(
          locationId: 4,
          parentId: null,
          requestKey: 'move-key',
        );

        expect(
          fake.onlyParams(LabApiRoutes.inventoryLocationUpdate),
          <String, dynamic>{
            'location_id': 4,
            'parent_id': false,
            'update_parent': true,
            'request_key': 'move-key',
          },
        );
      },
    );
  });

  // ------------------------------------------------------------- move retry

  group('LocationMoveController', () {
    test('a retry of the SAME move reuses the frozen request key', () async {
      final fake = FakeLabApi();
      var attempt = 0;
      fake.onCall = (path, params) async {
        if (path != LabApiRoutes.inventoryLocationUpdate) {
          throw StateError('unexpected $path');
        }
        attempt += 1;
        if (attempt == 1) {
          throw const LabApiException(
            code: 'NETWORK_ERROR',
            message: '无法连接服务器。',
          );
        }
        return <String, dynamic>{
          'location': <String, dynamic>{
            'id': 4,
            'name': 'R01',
            'path': 'WH/库存/M区/R01',
            'parent_id': 3,
          },
        };
      };
      var keys = 0;
      final controller = LocationMoveController(
        api: fake.client,
        newRequestKey: () => 'key-${++keys}',
      );
      addTearDown(controller.dispose);

      expect(await controller.move(locationId: 4, parentId: 3), isFalse);
      expect(controller.state.error, contains('无法连接'));
      expect(controller.state.attempt?.requestKey, 'key-1');

      expect(await controller.move(locationId: 4, parentId: 3), isTrue);
      final keysSent = fake
          .callsFor(LabApiRoutes.inventoryLocationUpdate)
          .map((call) => call.params['request_key'])
          .toList();
      expect(keysSent, <String>['key-1', 'key-1']);
      // Success closes the attempt: the next move may start fresh.
      expect(controller.state.attempt, isNull);
      expect(controller.state.moved?.parentId, 3);
    });

    test('a DIFFERENT target gets a new key', () async {
      final fake = FakeLabApi();
      fake.onCall = (path, params) async {
        throw const LabApiException(code: 'NETWORK_ERROR', message: '断网');
      };
      var keys = 0;
      final controller = LocationMoveController(
        api: fake.client,
        newRequestKey: () => 'key-${++keys}',
      );
      addTearDown(controller.dispose);

      await controller.move(locationId: 4, parentId: 3);
      await controller.move(locationId: 5, parentId: 3);

      final keysSent = fake
          .callsFor(LabApiRoutes.inventoryLocationUpdate)
          .map((call) => call.params['request_key'])
          .toList();
      expect(keysSent, <String>['key-1', 'key-2']);
    });
  });

  // -------------------------------------------------------------------- screen

  group('仓位速览 tree', () {
    Future<void> pump(
      WidgetTester tester, {
      required LabLocationTree tree,
      required bool canManage,
      Size size = const Size(1200, 900),
    }) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);

      final bootstrap = InventoryBootstrap(
        locations: tree.locations,
        borrowers: const <Borrower>[],
        permissions: canManage
            ? const InventoryPermissions(
                canIssueForOthers: true,
                canReceipt: true,
                canIssue: true,
                canReturn: true,
                canCreateLocation: true,
                canPrintLabels: true,
                selfBorrowerId: null,
                uid: 1,
                known: true,
              )
            : const InventoryPermissions(
                canIssueForOthers: false,
                canReceipt: true,
                canIssue: true,
                canReturn: true,
                canCreateLocation: false,
                canPrintLabels: true,
                selfBorrowerId: null,
                uid: 2,
                known: true,
              ),
        inventoryRevision: '1',
      );

      await tester.pumpWidget(
        ProviderScope(
          overrides: <Override>[
            inventoryLocationTreeProvider.overrideWith((ref) async => tree),
            inventoryBootstrapProvider.overrideWith((ref) async => bootstrap),
          ],
          child: MaterialApp(
            theme: LabTheme.dark,
            home: const LocationOverviewScreen(),
          ),
        ),
      );
      await tester.pumpAndSettle();
    }

    LabStockLocation loc(
      int id,
      String name,
      String path, {
      int? parentId,
      String usage = 'internal',
      int? bags,
      double? quantity,
    }) {
      return LabStockLocation.fromJson(<String, dynamic>{
        'id': id,
        'code': 'K${id.toString().padLeft(6, '0')}',
        'name': name,
        'path': path,
        'usage': usage,
        'parent_id': parentId,
        'bag_count': bags,
        'quantity': quantity,
      });
    }

    final tree = LabLocationTree(
      locations: <LabStockLocation>[
        loc(1, '库存', 'WH/库存', parentId: 0, usage: 'view'),
        loc(2, 'M区', 'WH/库存/M区', parentId: 1),
        loc(3, 'M(1,1)', 'WH/库存/M区/M(1,1)', parentId: 2, bags: 2, quantity: 12),
        loc(4, 'M(10,6)', 'WH/库存/M区/M(10,6)', parentId: 2),
        loc(5, 'R区', 'WH/库存/R区', parentId: 1),
        loc(6, 'R11', 'WH/库存/R区/R11', parentId: 5, bags: 1, quantity: 5),
      ],
      ancestors: <LabStockLocation>[loc(0, 'WH', 'WH', usage: 'view')],
    );

    testWidgets('shows the zones with their branches collapsed', (tester) async {
      await pump(tester, tree: tree, canManage: false);

      // WH and 库存 are open by default; the two zones are the collapsed
      // branches an operator opens to reach a shelf.
      // View folders render their own name; real locations render 库码 · 名称.
      expect(find.text('WH'), findsOneWidget);
      expect(find.text('库存'), findsOneWidget);
      expect(find.text('K000002 · M区'), findsOneWidget);
      expect(find.text('K000005 · R区'), findsOneWidget);
      expect(find.text('K000003 · M(1,1)'), findsNothing);
    });

    testWidgets('expanding a zone reveals its shelves, collapsing hides them',
        (tester) async {
      await pump(tester, tree: tree, canManage: false);

      await tester.tap(find.byKey(const ValueKey('location-toggle-2')));
      await tester.pumpAndSettle();
      expect(find.text('K000003 · M(1,1)'), findsOneWidget);
      // Natural order: M(1,1) comes before M(10,6).
      final first = tester.getTopLeft(find.text('K000003 · M(1,1)'));
      final last = tester.getTopLeft(find.text('K000004 · M(10,6)'));
      expect(first.dy, lessThan(last.dy));

      await tester.tap(find.byKey(const ValueKey('location-toggle-2')));
      await tester.pumpAndSettle();
      expect(find.text('K000003 · M(1,1)'), findsNothing);
      expect(find.text('K000005 · R区'), findsOneWidget);
    });

    testWidgets('search reveals a deep match together with its ancestors',
        (tester) async {
      await pump(tester, tree: tree, canManage: false);
      await tester.enterText(
          find.byKey(const ValueKey('location-search')), 'M(10,6)');
      await tester.pumpAndSettle();

      expect(find.text('K000004 · M(10,6)'), findsOneWidget);
      // The path above the match stays visible for context.
      expect(find.text('K000002 · M区'), findsOneWidget);
      expect(find.text('K000006 · R11'), findsNothing);

      // Clearing the search restores the collapsed default.
      await tester.enterText(find.byKey(const ValueKey('location-search')), '');
      await tester.pumpAndSettle();
      expect(find.text('K000004 · M(10,6)'), findsNothing);
      expect(find.text('K000005 · R区'), findsOneWidget);
    });

    testWidgets('an operator never sees a write action', (tester) async {
      await pump(tester, tree: tree, canManage: false);

      expect(find.byKey(const ValueKey('location-create')), findsNothing);
      expect(find.byKey(const ValueKey('location-move-3')), findsNothing);
    });

    testWidgets('a manager sees create and move', (tester) async {
      await pump(tester, tree: tree, canManage: true);

      expect(find.byKey(const ValueKey('location-create')), findsOneWidget);
      // The move action sits on every visible real location, including a zone.
      expect(find.byKey(const ValueKey('location-move-2')), findsOneWidget);
      // ... and a shelf once its zone is open.
      await tester.tap(find.byKey(const ValueKey('location-toggle-2')));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('location-move-3')), findsOneWidget);
    });

    testWidgets('counting excludes view folders and totals each row once', (
      tester,
    ) async {
      await pump(tester, tree: tree, canManage: false);

      // 5 internal locations (the view folder is not one), 3 bags, 17 on hand.
      expect(find.textContaining('6 个库位'), findsOneWidget);
      expect(find.textContaining('3 袋'), findsOneWidget);
      expect(find.textContaining('在库 17'), findsOneWidget);
    });
  });
}
