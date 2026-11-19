import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/session_scope.dart';
import 'package:lab_inventory_client/features/unified/models/unified_item.dart';
import 'package:lab_inventory_client/features/unified/providers/cache_writer_providers.dart';
import 'package:lab_inventory_client/features/unified/providers/label_providers.dart';
import 'package:lab_inventory_client/features/unified/providers/unified_providers.dart';
import 'package:lab_inventory_client/features/unified/screens/labels_screen.dart';
import 'package:lab_inventory_client/features/unified/services/asset_cache.dart';

import 'support/fake_lab_api.dart';

/// The direct-print action is shown ONLY where it can work.
///
/// The provider is overridden both ways, so this pins the user's rule: a dead
/// button is never rendered, and when the SDK is available the action sits
/// beside the PDF/system-print path.
class _NoopCacheWriter implements CatalogCacheWriter {
  @override
  void pinItemAssets(List<({String url, MediaKind kind})> assets) {}

  @override
  void saveDetail(String itemKey, Map<String, dynamic> data) {}

  @override
  void savePublicPage(List<UnifiedItem> items) {}
}

void main() {
  Widget host({required bool niimbotAvailable}) {
    final fake = FakeLabApi();
    return ProviderScope(
      overrides: [
        labApiProvider.overrideWithValue(fake.client),
        sessionScopeSourceProvider.overrideWithValue(
          const LabSessionScope(uid: 7),
        ),
        catalogCacheWriterProvider.overrideWithValue(_NoopCacheWriter()),
        niimbotAvailableProvider.overrideWithValue(niimbotAvailable),
      ],
      child: const MaterialApp(home: LabelsScreen()),
    );
  }

  testWidgets('the direct-print button is hidden when the SDK is unavailable',
      (tester) async {
    tester.view.physicalSize = const Size(390, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(host(niimbotAvailable: false));
    await tester.pumpAndSettle();

    expect(find.text('精臣打印机直打'), findsNothing);
    expect(find.text('生成 A4 PDF 并预览'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('the direct-print button appears beside the PDF action when available',
      (tester) async {
    tester.view.physicalSize = const Size(390, 1600);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(host(niimbotAvailable: true));
    await tester.pumpAndSettle();

    expect(find.text('精臣打印机直打'), findsOneWidget);
    expect(find.text('生成 A4 PDF 并预览'), findsOneWidget);

    // With nothing selected the layout is invalid, so BOTH actions are
    // disabled rather than submitting an empty job.
    final button = tester.widget<OutlinedButton>(
      find.widgetWithText(OutlinedButton, '精臣打印机直打'),
    );
    expect(button.onPressed, isNull);
    expect(tester.takeException(), isNull);
  });
}
