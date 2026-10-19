import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/detail_models.dart';
import 'package:lab_inventory_client/features/unified/providers/offline_providers.dart';
import 'package:lab_inventory_client/features/unified/providers/unified_providers.dart';
import 'package:lab_inventory_client/features/unified/screens/unified_catalog_screen.dart';
import 'package:lab_inventory_client/features/unified/screens/unified_item_detail_screen.dart';
import 'package:lab_inventory_client/features/unified/services/asset_cache.dart';
import 'package:lab_inventory_client/features/unified/services/public_catalog_cache.dart';
import 'package:lab_inventory_client/features/unified/unified_routes.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The public offline catalog: "重启时服务器不可达，仍然能看已缓存的资料".
///
/// These tests simulate the exact failure root described:
///   * a cold start with NO server and NO session (every API call impossible);
///   * only what a previous signed-in session cached on disk;
/// and they pin the boundaries:
///   * the cache contains public catalog facts only - never SN, stock, bags,
///     borrowers, projects or history;
///   * an unbound local material (`lab:42`) is never exposed this way;
///   * the cached manual opens from REAL BYTES with no network at all;
///   * the offline library offers no stock action and shows no stock figure;
///   * no login/secret state is written, so the 10-day rule is untouched.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory root;

  /// A hostile "live" detail payload that contains every private thing.
  Map<String, dynamic> liveDetail() => <String, dynamic>{
        'item': <String, dynamic>{
          'item_key': 'lcsc:C225521',
          'catalog_code': 'C225521',
          'name': '贴片钽电容 10uF',
          'mpn': 'TMCP1A106MTRF',
          'brand': 'VISHAY(威世)',
          'package': '0805',
          'category_name': '钽电容',
          'image_url': 'https://cdn.example.com/c225521.png',
          'lab_quantity': 1234567,
          'lab_available_quantity': 1234500,
          'has_stock': true,
          'catalog_stock': 99999999,
          'sn_codes': <String>['LAB-000001'],
          'lab_template_ids': <int>[42],
          'parameters': <Map<String, dynamic>>[
            <String, dynamic>{'code': 'param_1', 'name': '容值', 'value': '10uF'},
          ],
        },
        'materials': <Map<String, dynamic>>[
          <String, dynamic>{'product_template_id': 42, 'sn': 'LAB-000001'},
        ],
        'locations': <Map<String, dynamic>>[
          <String, dynamic>{'id': 1, 'code': 'K000001', 'quantity': 1234567},
        ],
        'bags': <Map<String, dynamic>>[
          <String, dynamic>{'id': 7, 'trace_code': 'TRACE-7', 'quantity': 1234567},
        ],
        'history': <Map<String, dynamic>>[
          <String, dynamic>{
            'kind': 'issue',
            'borrower': '张三',
            'project': '项目A',
            'quantity': 5,
          },
        ],
        'files': <Map<String, dynamic>>[
          <String, dynamic>{
            'fileType': 'pdf_property',
            'fileName': 'datasheet.pdf',
            'fileUrl': 'https://cdn.example.com/datasheet.pdf',
          },
        ],
      };

  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    root = Directory.systemTemp.createTempSync('lab_offline_');
  });

  tearDown(() {
    if (root.existsSync()) root.deleteSync(recursive: true);
  });

  PublicCatalogStore store() =>
      PublicCatalogStore(resolveDirectory: () async => root);

  group('the cache keeps public catalog facts only', () {
    test('sanitizeItem drops every private field', () {
      final sanitized = PublicCatalogStore.sanitizeItem(liveDetail()['item']);

      expect(sanitized['name'], '贴片钽电容 10uF');
      expect(sanitized['mpn'], 'TMCP1A106MTRF');
      expect(sanitized['catalog_code'], 'C225521');
      for (final forbidden in PublicCatalogStore.forbiddenFields) {
        expect(
          sanitized.containsKey(forbidden),
          isFalse,
          reason: '$forbidden must never be persisted',
        );
      }
      // The public mall stock figure is allowed (reference only)...
      expect(sanitized['catalog_stock'], 99999999);
      // ...but the laboratory quantity is not.
      expect(sanitized.containsKey('lab_quantity'), isFalse);
    });

    test('a saved detail contains no trace of stock, SN, bags or history', () async {
      final saved = await store().saveDetail('lcsc:C225521', liveDetail());
      expect(saved, isTrue);

      final entry = await store().read('lcsc:C225521');
      expect(entry, isNotNull);

      final encoded = jsonEncode(entry!.toJson());
      for (final needle in <String>[
        'lab_quantity',
        'lab_available_quantity',
        'has_stock',
        'sn_codes',
        'LAB-000001',
        'materials',
        'product_template_id',
        'bags',
        'TRACE-7',
        'locations',
        'K000001',
        'history',
        '张三',
        '项目A',
        'borrower',
        'project',
      ]) {
        expect(encoded.contains(needle), isFalse,
            reason: 'the cached document must not mention $needle');
      }
      // What it MUST keep: the public identity, parameters and files.
      expect(encoded.contains('C225521'), isTrue);
      expect(encoded.contains('10uF'), isTrue);
      expect(encoded.contains('datasheet.pdf'), isTrue);
    });

    test('an unbound local material is never cached here', () async {
      final saved = await store().saveDetail('lab:42', <String, dynamic>{
        'item': <String, dynamic>{'item_key': 'lab:42', 'name': '本地物料'},
      });
      expect(saved, isFalse);
      expect(await store().read('lab:42'), isNull);
      expect(await store().hasEntries(), isFalse);
    });

    test('files keep name/url/type and nothing else', () {
      final files = PublicCatalogStore.sanitizeFiles(<Map<String, dynamic>>[
        <String, dynamic>{
          'fileType': 'pdf_property',
          'fileName': 'a.pdf',
          'fileUrl': 'https://cdn.example.com/a.pdf',
          'supplier': '内部供应商信息',
          'uploaded_by': 7,
        },
      ]);
      expect(files.single.keys.toSet(), <String>{'fileType', 'fileName', 'fileUrl'});
    });

    test('the store writes no login/secret preference', () async {
      await store().saveDetail('lcsc:C225521', liveDetail());

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getKeys(), isEmpty,
          reason: 'offline caching must not touch login state or secrets');
    });
  });

  group('cold start with the server unreachable', () {
    test('a cached manual opens from real bytes with no network at all', () async {
      const manualUrl = 'https://cdn.example.com/datasheet.pdf';
      final pdfBytes = Uint8List.fromList(<int>[
        0x25, 0x50, 0x44, 0x46, 0x2D, 0x31, 0x2E, 0x34, 0x0A, ...List<int>.filled(40, 0x41),
      ]);

      // --- Session 1: online, the operator views the item (manual downloaded). ---
      var downloads = 0;
      final onlineCache = AssetCacheStore(
        resolveDirectory: () async => root,
        scopeKey: 'scope-a',
        downloader: (url) async {
          downloads++;
          return pdfBytes;
        },
      );
      await onlineCache.ensureFile(manualUrl);
      expect(downloads, 1);

      // --- Session 2: restart, no session, and the downloader would FAIL. ---
      final offlineCache = AssetCacheStore(
        resolveDirectory: () async => root,
        scopeKey: '',
        persistBusinessData: false,
        downloader: (url) async {
          fail('offline browsing must not need the network');
        },
      );

      final bytes = await offlineCache.read(manualUrl, kind: MediaKind.manual);
      expect(bytes, pdfBytes, reason: 'the cached PDF bytes must be returned');
      // A real PDF header, so the viewer can render it.
      expect(String.fromCharCodes(bytes.sublist(0, 4)), '%PDF');
      expect(downloads, 1, reason: 'no second download happened');
    });

    test('a cache-only store reports a miss instead of opening a connection', () async {
      var downloadAttempts = 0;
      final cache = AssetCacheStore(
        resolveDirectory: () async => root,
        scopeKey: '',
        persistBusinessData: false,
        cacheOnly: true,
        downloader: (url) async {
          downloadAttempts++;
          return Uint8List(0);
        },
      );

      await expectLater(
        cache.read('https://cdn.example.com/never-cached.pdf',
            kind: MediaKind.manual),
        throwsA(isA<AssetCacheException>()),
      );
      expect(downloadAttempts, 0,
          reason: 'offline browsing must never try the network');
    });

    test('a restart can still list and open the cached public metadata', () async {
      await store().saveDetail('lcsc:C225521', liveDetail());
      await store().saveItem(<String, dynamic>{
        'item_key': 'lcsc:C1',
        'catalog_code': 'C1',
        'name': '另一个器件',
      });

      // A brand-new store instance over the same directory = a restart.
      final reopened = store();
      final entries = await reopened.list();
      expect(entries.length, 2);
      expect(entries.map((entry) => entry.itemKey),
          containsAll(<String>['lcsc:C225521', 'lcsc:C1']));

      final detail = await reopened.read('lcsc:C225521');
      expect(detail, isNotNull);
      expect(detail!.files.single['fileUrl'], 'https://cdn.example.com/datasheet.pdf');
    });

    test('detail -> later search row -> restart still opens the manual AND its bytes',
        () async {
      const manualUrl = 'https://cdn.example.com/datasheet.pdf';
      final pdfBytes = Uint8List.fromList(<int>[
        0x25, 0x50, 0x44, 0x46, 0x2D, 0x31, 0x2E, 0x34, //
        ...List<int>.filled(60, 0x42),
      ]);

      // --- Session 1: view the detail (manual downloaded) ---
      final onlineCache = AssetCacheStore(
        resolveDirectory: () async => root,
        scopeKey: 'scope-a',
        downloader: (url) async => pdfBytes,
      );
      await onlineCache.ensureFile(manualUrl);

      final first = store();
      await first.saveDetail('lcsc:C225521', liveDetail());

      // A LATER search page saves the same row - without files and without
      // parameters, and with private fields a live row carries.
      await first.saveItem(<String, dynamic>{
        'item_key': 'lcsc:C225521',
        'catalog_code': 'C225521',
        'name': '贴片钽电容 10uF',
        'image_url': 'https://cdn.example.com/c225521.png',
        'lab_quantity': 5,
        'sn_codes': <String>['LAB-000001'],
      });

      // --- Session 2: restart, nothing cached in memory ---
      final reopened = store();
      final entry = await reopened.read('lcsc:C225521');
      expect(entry, isNotNull, reason: 'the search-row save must not erase the entry');
      expect(entry!.files.map((file) => file['fileUrl']), contains(manualUrl),
          reason: 'the manual cached by the detail must survive the search-row save');
      expect(entry.parameters, isNotEmpty,
          reason: 'the parameters cached by the detail must survive');
      expect(entry.item['name'], '贴片钽电容 10uF');
      expect(jsonEncode(entry.toJson()).contains('LAB-000001'), isFalse);
      expect(jsonEncode(entry.toJson()).contains('lab_quantity'), isFalse);

      // ...and the real bytes are still readable without any network.
      var networkAttempts = 0;
      final offlineCache = AssetCacheStore(
        resolveDirectory: () async => root,
        scopeKey: '',
        persistBusinessData: false,
        cacheOnly: true,
        downloader: (url) async {
          networkAttempts++;
          return pdfBytes;
        },
      );
      final bytes = await offlineCache.read(manualUrl, kind: MediaKind.manual);
      expect(bytes, pdfBytes);
      expect(String.fromCharCodes(bytes.sublist(0, 4)), '%PDF');
      expect(networkAttempts, 0);
    });

    test('concurrent saves never lose an entry', () async {
      final concurrent = store();
      await Future.wait(<Future<bool>>[
        for (var index = 1; index <= 25; index++)
          concurrent.saveItem(<String, dynamic>{
            'item_key': 'lcsc:C$index',
            'catalog_code': 'C$index',
            'name': '器件 $index',
          }),
      ]);

      // A restart must see every entry: no write overwrote another.
      final entries = await store().list();
      expect(entries.length, 25);
      expect(entries.map((entry) => entry.itemKey).toSet().length, 25);
    });

    test('two store instances over one directory do not lose entries', () async {
      // Two writers with their own queues (a second call site / isolate): each
      // read-modify-write must merge with what is already ON DISK, not with a
      // stale in-memory list.
      final first = store();
      final second = store();

      await first.saveItem(<String, dynamic>{
        'item_key': 'lcsc:C1',
        'catalog_code': 'C1',
        'name': 'first',
      });
      await second.saveItem(<String, dynamic>{
        'item_key': 'lcsc:C2',
        'catalog_code': 'C2',
        'name': 'second',
      });
      await first.saveItem(<String, dynamic>{
        'item_key': 'lcsc:C3',
        'catalog_code': 'C3',
        'name': 'third',
      });

      final entries = await store().list();
      expect(
        entries.map((entry) => entry.itemKey).toSet(),
        <String>{'lcsc:C1', 'lcsc:C2', 'lcsc:C3'},
      );
    });

    test('a foreign or stale index entry is re-sanitized or dropped on read', () async {
      final dir = Directory('${root.path}/${PublicCatalogStore.directoryName}')
        ..createSync(recursive: true);
      File('${dir.path}/index.json').writeAsStringSync(jsonEncode(<Map<String, dynamic>>[
        // Not a public identity: dropped entirely.
        <String, dynamic>{
          'item_key': 'lab:42',
          'item': <String, dynamic>{'name': '本地物料'},
          'files': <dynamic>[],
          'parameters': <dynamic>[],
        },
        // A public identity carrying private fields from an older/fiddled file.
        <String, dynamic>{
          'item_key': 'lcsc:C9',
          'item': <String, dynamic>{
            'catalog_code': 'C9',
            'name': '器件',
            'lab_quantity': 9,
            'sn_codes': <String>['LAB-9'],
            'materials': <Map<String, dynamic>>[
              <String, dynamic>{'sn': 'LAB-9'},
            ],
            'borrower': '张三',
          },
          'files': <Map<String, dynamic>>[
            <String, dynamic>{
              'fileUrl': 'https://cdn.example.com/x.pdf',
              'supplier': '内部供应商',
            },
          ],
          'parameters': <Map<String, dynamic>>[
            <String, dynamic>{'name': '容值', 'value': '1uF', 'actor': '李四'},
          ],
        },
      ]));

      final entries = await store().list();
      expect(entries.length, 1, reason: 'the lab: entry must be refused');

      final encoded = jsonEncode(entries.single.toJson());
      for (final needle in <String>[
        'lab_quantity',
        'sn_codes',
        'LAB-9',
        'materials',
        'borrower',
        '张三',
        'supplier',
        '李四',
        'lab:42',
      ]) {
        expect(encoded.contains(needle), isFalse,
            reason: 'an untrusted index must not reintroduce $needle');
      }
      expect(entries.single.files.single.keys.toSet(), <String>{'fileUrl'});
      expect(entries.single.parameters.single.keys.toSet(), <String>{'name', 'value'});
    });

    test('the index is bounded, keeping the newest entries', () async {
      final bounded = PublicCatalogStore(
        resolveDirectory: () async => root,
        maxEntries: 3,
      );
      for (var index = 1; index <= 5; index++) {
        await bounded.saveItem(<String, dynamic>{
          'item_key': 'lcsc:C$index',
          'catalog_code': 'C$index',
          'name': '器件 $index',
        });
      }
      final entries = await bounded.list();
      expect(entries.length, 3);
      expect(entries.first.itemKey, 'lcsc:C5');
    });
  });

  group('offline rows never look like live stock', () {
    test('a cached row is rendered without any stock figure', () async {
      await store().saveDetail('lcsc:C225521', liveDetail());
      final entry = await store().read('lcsc:C225521');
      final item = offlineItemFrom(entry!);

      expect(item.labQuantity, 0);
      expect(item.hasStock, isFalse);
      expect(item.labAvailableQuantity, 0);
      expect(item.catalogCode, 'C225521');
    });

    test('the offline detail carries no locations, bags, history or materials',
        () async {
      await store().saveDetail('lcsc:C225521', liveDetail());
      final entry = await store().read('lcsc:C225521');

      final detail = CatalogDetail(
        item: null,
        locations: const <LabStockLocation>[],
        bags: const <LabBag>[],
        files: entry!.files
            .map((file) => LabFile(
                  name: file['fileName']?.toString() ?? '',
                  url: file['fileUrl']!.toString(),
                  type: file['fileType']?.toString() ?? '',
                ))
            .toList(),
        history: const <LabOperation>[],
        materials: const <LabMaterial>[],
      );

      expect(detail.locations, isEmpty);
      expect(detail.bags, isEmpty);
      expect(detail.history, isEmpty);
      expect(detail.materials, isEmpty);
      expect(detail.files.length, 1);
    });
  });

  group('offline UI', () {
    /// Seeded public entry built with the REAL sanitizer, but without touching the
    /// disk: widget tests run inside `fakeAsync`, where real file I/O never
    /// completes (that is the hang root spotted). The disk/restart guarantees are
    /// covered by the plain `test()` cases above.
    PublicCatalogEntry seededEntry() {
      final detail = liveDetail();
      return PublicCatalogEntry(
        itemKey: 'lcsc:C225521',
        item: PublicCatalogStore.sanitizeItem(detail['item']),
        files: PublicCatalogStore.sanitizeFiles(detail['files']),
        parameters: PublicCatalogStore.sanitizeParameters(
          (detail['item']! as Map<String, dynamic>)['parameters'],
        ),
        savedAt: DateTime(2026, 10, 14, 10),
      );
    }

    Widget wrap(
      Widget child, {
      List<PublicCatalogEntry>? entries,
      CatalogDetail? detail,
    }) {
      return ProviderScope(
        overrides: <Override>[
          assetCacheDirectoryProvider.overrideWithValue(
            () async => Directory.systemTemp.createTempSync('lab_offline_ui_'),
          ),
          // Pre-seeded, in-memory: no File I/O inside the widget test's fakeAsync.
          offlineCatalogEntriesProvider.overrideWith(
            (ref) async => entries ?? <PublicCatalogEntry>[],
          ),
          if (detail != null)
            offlineCatalogDetailProvider.overrideWith((ref, itemKey) async => detail),
        ],
        child: MaterialApp(
          theme: ThemeData(splashFactory: InkRipple.splashFactory),
          home: child,
        ),
      );
    }

    CatalogDetail seededDetail() {
      final entry = seededEntry();
      return CatalogDetail(
        item: offlineItemFrom(entry),
        locations: const <LabStockLocation>[],
        bags: const <LabBag>[],
        files: entry.files
            .map((file) => LabFile(
                  name: file['fileName']?.toString() ?? '',
                  url: file['fileUrl']!.toString(),
                  type: file['fileType']?.toString() ?? '',
                ))
            .toList(),
        history: const <LabOperation>[],
        materials: const <LabMaterial>[],
      );
    }

    Future<void> pumpUntilFound(WidgetTester tester, Finder finder) async {
      for (var frame = 0; frame < 40; frame++) {
        if (finder.evaluate().isNotEmpty) return;
        await tester.pump(const Duration(milliseconds: 25));
      }
    }

    testWidgets('the offline library shows cached items, a clear banner and NO stock action',
        (tester) async {
      await tester.pumpWidget(
        wrap(
          const UnifiedCatalogScreen(offline: true),
          entries: <PublicCatalogEntry>[seededEntry()],
        ),
      );
      await pumpUntilFound(tester, find.text('C225521'));

      expect(find.text('C225521'), findsWidgets);
      expect(find.textContaining('离线只读缓存资料'), findsWidgets);
      expect(find.textContaining('不含库存数量'), findsWidgets);
      // No stock action exists in offline mode.
      expect(find.text('入库'), findsNothing);
      expect(find.text('领料'), findsNothing);
      expect(find.textContaining('内部库存'), findsNothing);
      expect(find.textContaining('1234567'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('the offline detail shows parameters and manuals, never stock or history',
        (tester) async {
      await tester.pumpWidget(
        wrap(
          const UnifiedItemDetailScreen(itemKey: 'lcsc:C225521', offline: true),
          entries: <PublicCatalogEntry>[seededEntry()],
          detail: seededDetail(),
        ),
      );
      await pumpUntilFound(tester, find.text('参数'));

      expect(find.text('参数'), findsOneWidget);
      expect(find.text('手册 / 数据表'), findsOneWidget);
      expect(find.textContaining('datasheet.pdf'), findsWidgets);
      // Business sections are absent, not merely empty.
      expect(find.text('库存'), findsNothing);
      expect(find.text('库位分布'), findsNothing);
      expect(find.text('追溯袋 / 批次'), findsNothing);
      expect(find.text('最近操作'), findsNothing);
      expect(find.textContaining('LAB-000001'), findsNothing);
      expect(find.textContaining('lcsc:'), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('an empty cache says so explicitly instead of pretending', (tester) async {
      await tester.pumpWidget(
        wrap(const UnifiedCatalogScreen(offline: true), entries: <PublicCatalogEntry>[]),
      );
      await pumpUntilFound(tester, find.text('本机还没有缓存资料'));

      expect(find.text('本机还没有缓存资料'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });

  group('route flag', () {
    test('isOffline recognises the flag the auth layer must allow', () {
      expect(UnifiedRoutes.isOffline(<String, String>{'offline': '1'}), isTrue);
      expect(UnifiedRoutes.isOffline(<String, String>{'offline': 'true'}), isTrue);
      expect(UnifiedRoutes.isOffline(<String, String>{}), isFalse);
      expect(UnifiedRoutes.isOffline(<String, String>{'offline': '0'}), isFalse);
      expect(UnifiedRoutes.offlineCatalog, '/catalog?offline=1');
      expect(
        UnifiedRoutes.offlineItemDetail('lcsc:C225521'),
        contains('offline=1'),
      );
    });
  });
}
