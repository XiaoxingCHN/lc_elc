import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/session_scope.dart';
import 'package:lab_inventory_client/features/unified/models/unified_item.dart';
import 'package:lab_inventory_client/features/unified/providers/cache_writer_providers.dart';
import 'package:lab_inventory_client/features/unified/providers/unified_providers.dart';
import 'package:lab_inventory_client/features/unified/screens/labels_screen.dart';
import 'package:lab_inventory_client/features/unified/screens/pending_receipt_screen.dart';
import 'package:lab_inventory_client/features/unified/screens/unified_catalog_screen.dart';
import 'package:lab_inventory_client/features/unified/screens/unified_item_detail_screen.dart';
import 'package:lab_inventory_client/features/unified/services/asset_cache.dart';
import 'package:lab_inventory_client/providers/auth_provider.dart';
import 'package:lab_inventory_client/features/unified/widgets/label_preview.dart';
import 'package:lab_inventory_client/screens/login_screen.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';
import 'package:lab_inventory_client/widgets/lab_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../support/login_test_support.dart';
import 'support/fake_lab_api.dart';

/// Renders the priority business screen under the shipped dark glass theme.
///
/// The other pending tests deliberately pump a bare [ThemeData] to prove the
/// screen survives without the design-system extension; this one is the visual
/// acceptance pass: real [LabTheme.dark], real [GlassBackdrop], and PNG output
/// when `LAB_UI_EVIDENCE` points at a directory.
void main() {
  setUp(() => SharedPreferences.setMockInitialValues(<String, Object>{}));

  Future<ThemeData> prepareEvidence(WidgetTester tester) async {
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
        final icons = _findSdkIconFont();
        if (icons != null) {
          final iconLoader = FontLoader('MaterialIcons')
            ..addFont(
              Future.value(ByteData.sublistView(await icons.readAsBytes())),
            );
          await iconLoader.load();
        }
        final cupertinoLoader =
            FontLoader('packages/cupertino_icons/CupertinoIcons')..addFont(
              rootBundle.load(
                'packages/cupertino_icons/assets/CupertinoIcons.ttf',
              ),
            );
        await cupertinoLoader.load();
      });
    }
    final base = LabTheme.dark;
    return output == null
        ? base
        : base.copyWith(
            textTheme: base.textTheme.apply(fontFamily: 'Evidence'),
            primaryTextTheme: base.primaryTextTheme.apply(
              fontFamily: 'Evidence',
            ),
            appBarTheme: base.appBarTheme.copyWith(
              titleTextStyle: base.appBarTheme.titleTextStyle?.copyWith(
                fontFamily: 'Evidence',
              ),
            ),
            listTileTheme: base.listTileTheme.copyWith(
              titleTextStyle: base.listTileTheme.titleTextStyle?.copyWith(
                fontFamily: 'Evidence',
              ),
              subtitleTextStyle: base.listTileTheme.subtitleTextStyle?.copyWith(
                fontFamily: 'Evidence',
              ),
            ),
          );
  }

  Widget evidenceHost({
    required ThemeData theme,
    required Widget child,
    required GlobalKey boundaryKey,
    List<Override> overrides = const <Override>[],
    ProviderContainer? container,
  }) {
    final app = RepaintBoundary(
      key: boundaryKey,
      child: MaterialApp(
        theme: theme,
        darkTheme: theme,
        themeMode: ThemeMode.dark,
        builder: (context, child) =>
            GlassBackdrop(child: child ?? const SizedBox.shrink()),
        home: child,
      ),
    );
    return container == null
        ? ProviderScope(overrides: overrides, child: app)
        : UncontrolledProviderScope(container: container, child: app);
  }

  void useSurface(WidgetTester tester, Size size) {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  Map<String, dynamic> evidenceItem() => itemJson(
    itemKey: 'lcsc:C225521',
    catalogCode: 'C225521',
    name: '贴片钽电容 10uF ±20% 10V',
    mpn: 'TMCP1A106MTRF',
    brand: 'VISHAY（威世）',
    package: '0805',
    labQuantity: 1200,
    catalogStock: 8400,
    labTemplateIds: const <int>[42],
    snCodes: const <String>['LAB-000001'],
    parameters: const <Map<String, dynamic>>[
      <String, dynamic>{'name': '容值', 'value': '10uF'},
      <String, dynamic>{'name': '耐压', 'value': '10V'},
    ],
  );

  FakeLabApi evidenceApi() {
    return FakeLabApi(
      onCall: (path, params) async {
        switch (path) {
          case LabApiRoutes.pendingList:
            return {
              'records': [
                {
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
                },
              ],
            };
          case LabApiRoutes.inventoryLocations:
            return {
              'locations': [
                {'id': 3, 'name': 'R01', 'code': 'K000003'},
              ],
            };
          case LabApiRoutes.catalogSearch:
            return {
              'items': [evidenceItem()],
              'next_cursor': null,
              'total': 1,
              'inventory_revision': 'rev-1',
            };
          case LabApiRoutes.catalogCategories:
            return {'categories': <dynamic>[]};
          case LabApiRoutes.catalogFacets:
            return {
              'brands': <dynamic>[],
              'packages': <dynamic>[],
              'parameters': <dynamic>[],
            };
          case LabApiRoutes.catalogDetail:
            return {
              'item': evidenceItem(),
              'materials': [
                {
                  'product_template_id': 42,
                  'sn': 'LAB-000001',
                  'name': '贴片钽电容 10uF',
                  'lab_quantity': 1200,
                },
              ],
              'locations': [
                {
                  'id': 1,
                  'code': 'K000001',
                  'name': 'A01-03',
                  'path': 'Lab/A01-03',
                  'quantity': 1200,
                },
              ],
              'bags': [
                {
                  'id': 7,
                  'trace_code': 'TRACE-0000000007',
                  'sn': 'LAB-000001',
                  'quantity': 1200,
                  'location_code': 'K000001',
                },
              ],
              'files': [
                {
                  'fileType': 'pdf_property',
                  'fileName': 'TMCP1A106MTRF 数据手册.pdf',
                  'fileUrl': 'https://cdn.example.com/datasheet.pdf',
                },
              ],
              'history': [
                {
                  'kind': 'receipt',
                  'item_key': 'lcsc:C225521',
                  'quantity': 1200,
                  'actor': '张三',
                  'location_code': 'K000001',
                  'at': '2026-10-14 10:00:00',
                },
              ],
            };
          default:
            return {};
        }
      },
    );
  }

  testWidgets('pending receipt renders on the dark glass theme', (
    tester,
  ) async {
    final output = Platform.environment['LAB_UI_EVIDENCE'];
    final theme = await prepareEvidence(tester);
    useSurface(tester, const Size(390, 1000));

    final fake = evidenceApi();
    final boundaryKey = GlobalKey();
    await tester.pumpWidget(
      evidenceHost(
        theme: theme,
        boundaryKey: boundaryKey,
        overrides: [
          labApiProvider.overrideWithValue(fake.client),
          sessionScopeSourceProvider.overrideWithValue(
            const LabSessionScope(uid: 7),
          ),
          catalogCacheWriterProvider.overrideWithValue(_NoopCacheWriter()),
        ],
        child: const PendingReceiptScreen(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('先贴码，再上架'), findsOneWidget);
    expect(tester.takeException(), isNull);
    if (output != null) {
      await _capture(tester, boundaryKey, output, 'dark-pending-prepare.png');
    }

    await tester.tap(find.text('2  扫码上架'));
    await tester.pumpAndSettle();
    expect(find.text('逐袋核对入库'), findsOneWidget);
    expect(tester.takeException(), isNull);
    if (output != null) {
      await _capture(tester, boundaryKey, output, 'dark-pending-scan.png');
    }
  });

  testWidgets('login, catalog, detail and paper render without a server', (
    tester,
  ) async {
    final output = Platform.environment['LAB_UI_EVIDENCE'];
    final theme = await prepareEvidence(tester);
    useSurface(tester, const Size(390, 1100));
    final boundaryKey = GlobalKey();
    final container = buildAuthContainer(
      backend: InMemorySecretBackend(),
      gateway: FakeAuthGateway(),
      now: DateTime(2026, 11, 6),
    );
    addTearDown(container.dispose);
    await container.read(authProvider.notifier).bootstrap();
    await tester.pumpWidget(
      evidenceHost(
        theme: theme,
        boundaryKey: boundaryKey,
        container: container,
        child: const LoginScreen(),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('登录'), findsOneWidget);
    expect(tester.takeException(), isNull);
    if (output != null) {
      await _capture(tester, boundaryKey, output, 'dark-login.png');
    }

    useSurface(tester, const Size(1280, 900));
    await tester.pumpWidget(
      evidenceHost(
        theme: theme,
        boundaryKey: boundaryKey,
        overrides: [
          labApiProvider.overrideWithValue(evidenceApi().client),
          sessionScopeSourceProvider.overrideWithValue(
            const LabSessionScope(uid: 7),
          ),
          catalogCacheWriterProvider.overrideWithValue(_NoopCacheWriter()),
        ],
        child: const UnifiedCatalogScreen(),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('C225521'), findsOneWidget);
    expect(tester.takeException(), isNull);
    if (output != null) {
      await _capture(tester, boundaryKey, output, 'dark-catalog-desktop.png');
    }

    useSurface(tester, const Size(390, 1100));
    await tester.pumpWidget(
      evidenceHost(
        theme: theme,
        boundaryKey: boundaryKey,
        overrides: [
          labApiProvider.overrideWithValue(evidenceApi().client),
          sessionScopeSourceProvider.overrideWithValue(
            const LabSessionScope(uid: 7),
          ),
          catalogCacheWriterProvider.overrideWithValue(_NoopCacheWriter()),
        ],
        child: const UnifiedItemDetailScreen(itemKey: 'lcsc:C225521'),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('库存'), findsOneWidget);
    expect(tester.takeException(), isNull);
    if (output != null) {
      await _capture(tester, boundaryKey, output, 'dark-item-detail.png');
    }

    useSurface(tester, const Size(390, 1400));
    await tester.pumpWidget(
      evidenceHost(
        theme: theme,
        boundaryKey: boundaryKey,
        overrides: [
          labApiProvider.overrideWithValue(evidenceApi().client),
          sessionScopeSourceProvider.overrideWithValue(
            const LabSessionScope(uid: 7),
          ),
          catalogCacheWriterProvider.overrideWithValue(_NoopCacheWriter()),
        ],
        child: const LabelsScreen(initialKind: 'pending', initialIds: '8'),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('A4 排版预览'), findsOneWidget);
    expect(tester.takeException(), isNull);
    final caption = tester.widget<Text>(
      find.descendant(
        of: find.byType(LabelLayoutPreview),
        matching: find.textContaining('/ 页'),
      ),
    );
    expect(caption.style?.color, Colors.black);
    if (output != null) {
      await _capture(tester, boundaryKey, output, 'dark-label-designer.png');
    }
  });
}

class _NoopCacheWriter implements CatalogCacheWriter {
  @override
  void pinItemAssets(List<({String url, MediaKind kind})> assets) {}

  @override
  void saveDetail(String itemKey, Map<String, dynamic> data) {}

  @override
  void savePublicPage(List<UnifiedItem> items) {}
}

Future<void> _capture(
  WidgetTester tester,
  GlobalKey boundaryKey,
  String output,
  String name,
) async {
  await tester.runAsync(() async {
    final image =
        await (boundaryKey.currentContext!.findRenderObject()!
                as RenderRepaintBoundary)
            .toImage();
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    await Directory(output).create(recursive: true);
    await File('$output/$name').writeAsBytes(bytes!.buffer.asUint8List());
    image.dispose();
  });
}

/// Locates the Material icon font from the SDK payload, searching upwards so
/// the same test works from the main checkout and from a git worktree.
File? _findSdkIconFont() {
  const relative =
      'dependencies/sdk/windows/flutter/bin/cache/artifacts/material_fonts/materialicons-regular.otf';
  var dir = Directory.current.absolute;
  for (var depth = 0; depth < 8; depth++) {
    final candidate = File('${dir.path}/$relative');
    if (candidate.existsSync()) return candidate;
    final parent = dir.parent;
    if (parent.path == dir.path) break;
    dir = parent;
  }
  return null;
}
