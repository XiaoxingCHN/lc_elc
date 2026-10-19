import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/identity.dart';
import 'package:lab_inventory_client/features/unified/models/session_scope.dart';
import 'package:lab_inventory_client/features/unified/models/unified_item.dart';
import 'package:lab_inventory_client/features/unified/providers/cache_writer_providers.dart';
import 'package:lab_inventory_client/features/unified/providers/unified_providers.dart';
import 'package:lab_inventory_client/features/unified/screens/unified_catalog_screen.dart';
import 'package:lab_inventory_client/features/unified/screens/unified_item_detail_screen.dart';
import 'package:lab_inventory_client/features/unified/widgets/item_card.dart';
import 'package:lab_inventory_client/features/unified/services/asset_cache.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/fake_lab_api.dart';

/// Real widget layout checks (root's review).
///
/// Covered here:
///   * a captured `catalog_code` that already carries its `C` is printed exactly
///     once (`C225521`, never `CC225521`);
///   * the internal identity (`lcsc:` / `lab:`) never reaches the screen;
///   * the card and the detail survive 320 / 360 px phones and a 1280 px desktop
///     with long Chinese brands, long model names and six/seven-digit quantities
///     (no RenderFlex overflow).
/// Cache writes are disabled in widget tests: they would perform real file I/O
/// inside `fakeAsync`, which never completes and would hang the test.
class _NoopCacheWriter implements CatalogCacheWriter {
  @override
  void pinItemAssets(List<({String url, MediaKind kind})> assets) {}

  @override
  void saveDetail(String itemKey, Map<String, dynamic> data) {}

  @override
  void savePublicPage(List<UnifiedItem> items) {}
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory cacheDir;

  setUp(() {
    // The detail screen pins viewer/stocked assets in the file cache, which reads
    // SharedPreferences: without a mock the platform channel is missing.
    SharedPreferences.setMockInitialValues(<String, Object>{});
    // ...and path_provider has no platform implementation in a unit test, so the
    // cache directory is injected instead (same seam the app uses).
    cacheDir = Directory.systemTemp.createTempSync('lab_ui_layout_');
    addTearDown(() {
      if (cacheDir.existsSync()) cacheDir.deleteSync(recursive: true);
    });
  });
  /// Pumps frames until [finder] matches (async providers need a few turns).
  Future<void> pumpUntilFound(
    WidgetTester tester,
    Finder finder, {
    int frames = 40,
  }) async {
    for (var frame = 0; frame < frames; frame++) {
      if (finder.evaluate().isNotEmpty) return;
      await tester.pump(const Duration(milliseconds: 25));
    }
  }

  /// A deliberately hostile row: long CJK text + huge numbers.
  Map<String, dynamic> hostileItem() => itemJson(
        itemKey: 'lcsc:C225521',
        catalogCode: 'C225521',
        name: '贴片钽电容 10uF ±20% 10V 低ESR 工业级 长名称测试用例',
        mpn: 'TMCP1A106MTRF-VERY-LONG-PART-NUMBER-0001',
        brand: 'VISHAY(威世) 长品牌名称测试',
        package: '0805',
        labQuantity: 1234567,
        labAvailable: 1234500,
        catalogStock: 99999999,
        labTemplateIds: <int>[42, 43],
        snCodes: <String>['LAB-000001', 'LAB-000002'],
        parameters: <Map<String, dynamic>>[
          <String, dynamic>{'code': 'param_1', 'name': '容值', 'value': '10uF'},
        ],
      );

  LabApiClient clientFor(String itemKey) {
    final api = FakeLabApi();
    api.onCall = (path, params) async {
      switch (path) {
        case LabApiRoutes.catalogSearch:
          return <String, dynamic>{
            'items': <Map<String, dynamic>>[hostileItem()],
            'next_cursor': null,
            'total': 1,
            'inventory_revision': 'rev-1',
          };
        case LabApiRoutes.catalogCategories:
          return <String, dynamic>{'categories': <dynamic>[]};
        case LabApiRoutes.catalogFacets:
          return <String, dynamic>{
            'brands': <dynamic>[],
            'packages': <dynamic>[],
            'parameters': <dynamic>[],
          };
        case LabApiRoutes.catalogDetail:
          return <String, dynamic>{
            'item': hostileItem(),
            'materials': <Map<String, dynamic>>[
              <String, dynamic>{
                'product_template_id': 42,
                'sn': 'LAB-000001',
                'name': '长名称档案一',
                'lab_quantity': 1234567,
              },
              <String, dynamic>{
                'product_template_id': 43,
                'sn': 'LAB-000002',
                'name': '长名称档案二',
                'lab_quantity': 1,
              },
            ],
            'locations': <Map<String, dynamic>>[
              <String, dynamic>{
                'id': 1,
                'code': 'K000001',
                'name': '货架最顶层最右侧库位名称很长',
                'path': 'Lab/货架最顶层最右侧',
                'quantity': 1234567,
              },
            ],
            'bags': <Map<String, dynamic>>[
              <String, dynamic>{
                'id': 7,
                'trace_code': 'TRACE-0000000007',
                'sn': 'LAB-000001',
                'quantity': 1234567,
                'location_code': 'K000001',
              },
            ],
            'files': <Map<String, dynamic>>[
              <String, dynamic>{
                'fileType': 'pdf_property',
                'fileName': '非常长的数据表文件名-工业级钽电容-2026版.pdf',
                'fileUrl': 'https://cdn.example.com/datasheet.pdf',
              },
            ],
            'history': <Map<String, dynamic>>[
              <String, dynamic>{
                'kind': 'receipt',
                'item_key': 'lcsc:C225521',
                'quantity': 1234567,
                'actor': '张三',
                'location_code': 'K000001',
                'at': '2026-10-14 10:00:00',
              },
            ],
          };
        default:
          throw StateError('unexpected $path');
      }
    };
    return api.client;
  }

  void useSurface(WidgetTester tester, Size size) {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  Widget wrap(Widget child, String itemKey) {
    return ProviderScope(
      overrides: <Override>[
        labApiProvider.overrideWithValue(clientFor(itemKey)),
        // PROOF that these tests do no file I/O: the resolver throws if anything
        // ever tries to touch the cache directory. Combined with the no-op cache
        // writer below, a layout test performs zero disk work inside fakeAsync -
        // which is exactly the hang root spotted.
        assetCacheDirectoryProvider.overrideWithValue(
          () async => throw StateError(
            'layout tests must not touch the cache directory',
          ),
        ),
        // A fixed session scope: the layout tests are about pixels.
        effectiveSessionScopeProvider.overrideWithValue(
          const LabSessionScope(baseUrl: 'http://a:8069', database: 'db', uid: 1),
        ),
        // No cache WRITES at all: these tests run inside fakeAsync, where real
        // file I/O never completes. The layout must not depend on it (and the
        // production code fires those writes without awaiting).
        catalogCacheWriterProvider.overrideWithValue(_NoopCacheWriter()),
      ],
      child: MaterialApp(
        theme: ThemeData(splashFactory: InkRipple.splashFactory),
        home: child,
      ),
    );
  }

  group('catalog code is printed exactly once', () {
    testWidgets('a card whose code already carries C shows C225521, not CC225521',
        (tester) async {
      useSurface(tester, const Size(1280, 900));
      await tester.pumpWidget(wrap(const UnifiedCatalogScreen(), 'lcsc:C225521'));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.text('C225521'), findsOneWidget);
      expect(find.textContaining('CC225521'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('the raw card widget renders the same single prefix',
        (tester) async {
      useSurface(tester, const Size(360, 720));
      final item = UnifiedItem.fromJson(hostileItem());
      await tester.pumpWidget(
        wrap(
          Scaffold(
            body: SizedBox(
              width: 160,
              height: 300,
              child: ItemCard(item: item, onTap: () {}),
            ),
          ),
          'lcsc:C225521',
        ),
      );
      await tester.pump();

      expect(find.text('C225521'), findsOneWidget);
      expect(find.textContaining('CC225521'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    test('the display helper never doubles the prefix', () {
      expect(displayCatalogCode('C225521'), 'C225521');
      expect(displayCatalogCode('c225521'), 'C225521');
      expect(displayCatalogCode('225521'), 'C225521');
      expect(displayCatalogCode('lcsc:C225521'), 'C225521');
      expect(displayCatalogCode('Ｃ２２５５２１'), 'C225521');
      expect(displayCatalogCode(null), '');
    });
  });

  group('narrow and desktop layouts do not overflow', () {
    testWidgets('catalog grid at 320 px with huge numbers and long CJK text',
        (tester) async {
      useSurface(tester, const Size(320, 640));
      await tester.pumpWidget(wrap(const UnifiedCatalogScreen(), 'lcsc:C225521'));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.text('C225521'), findsWidgets);
      expect(tester.takeException(), isNull);
    });

    testWidgets('catalog list mode at 360 px', (tester) async {
      useSurface(tester, const Size(360, 720));
      await tester.pumpWidget(wrap(const UnifiedCatalogScreen(), 'lcsc:C225521'));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pump(const Duration(milliseconds: 50));

      await tester.tap(find.byIcon(Icons.view_list));
      await tester.pump();

      expect(tester.takeException(), isNull);
    });

    testWidgets('catalog grid at 1280 px (desktop)', (tester) async {
      useSurface(tester, const Size(1280, 900));
      await tester.pumpWidget(wrap(const UnifiedCatalogScreen(), 'lcsc:C225521'));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pump(const Duration(milliseconds: 50));

      expect(tester.takeException(), isNull);
    });

    testWidgets('item detail at 320 px shows no internal key and no overflow',
        (tester) async {
      useSurface(tester, const Size(320, 640));
      await tester.pumpWidget(
        wrap(
          const UnifiedItemDetailScreen(itemKey: 'lcsc:C225521'),
          'lcsc:C225521',
        ),
      );
      await pumpUntilFound(tester, find.text('库存'));

      // Surface a build/layout exception before any expectation about content.
      expect(tester.takeException(), isNull);

      // The operator sees human codes only.
      expect(find.textContaining('lcsc:'), findsNothing);
      expect(find.textContaining('lab:'), findsNothing);
      expect(find.text('C225521'), findsWidgets);
    });

    testWidgets('item detail at 1280 px', (tester) async {
      useSurface(tester, const Size(1280, 900));
      await tester.pumpWidget(
        wrap(
          const UnifiedItemDetailScreen(itemKey: 'lcsc:C225521'),
          'lcsc:C225521',
        ),
      );
      await pumpUntilFound(tester, find.text('库存'));

      expect(tester.takeException(), isNull);
      // Both local archives are listed by SN, not by internal id.
      expect(find.textContaining('LAB-000001'), findsWidgets);
    });
  });
}
