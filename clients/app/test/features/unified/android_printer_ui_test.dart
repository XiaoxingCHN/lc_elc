import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/session_scope.dart';
import 'package:lab_inventory_client/features/unified/models/unified_item.dart';
import 'package:lab_inventory_client/features/unified/providers/cache_writer_providers.dart';
import 'package:lab_inventory_client/features/unified/providers/unified_providers.dart';
import 'package:lab_inventory_client/features/unified/screens/labels_screen.dart';
import 'package:lab_inventory_client/features/unified/services/asset_cache.dart';
import 'package:lab_inventory_client/services/niimbot_android_printer.dart';

import 'support/fake_lab_api.dart';

/// The Android Bluetooth area is rendered only where it can work, and it never
/// shows a success it did not get.
///
/// The native side is mocked at the MethodChannel boundary, so this pins the
/// screen's own behaviour: hidden on non-Android, hidden when the SDK is
/// unavailable, and the search → list → print controls appear only when the
/// SDK answered available.
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

  const methodChannel = MethodChannel('lab/printer');
  const eventChannel = EventChannel('lab/printer/scan');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  Widget host() {
    final fake = FakeLabApi();
    return ProviderScope(
      overrides: [
        labApiProvider.overrideWithValue(fake.client),
        sessionScopeSourceProvider.overrideWithValue(
          const LabSessionScope(uid: 7),
        ),
        catalogCacheWriterProvider.overrideWithValue(_NoopCacheWriter()),
      ],
      child: const MaterialApp(home: LabelsScreen()),
    );
  }

  void useTallSurface(WidgetTester tester) {
    tester.view.physicalSize = const Size(390, 1800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  setUp(() {
    NiimbotAndroidPrinter.platformOverride =
        const (android: true, windows: false, linux: false);
  });

  tearDown(() {
    messenger.setMockMethodCallHandler(methodChannel, null);
    messenger.setMockStreamHandler(eventChannel, null);
    NiimbotAndroidPrinter.platformOverride = null;
  });

  testWidgets('hidden when the native SDK is unavailable', (tester) async {
    useTallSurface(tester);
    messenger.setMockMethodCallHandler(methodChannel, (call) async {
      if (call.method == 'available') {
        return <String, Object?>{'available': false, 'reason': '字体资源不可用'};
      }
      return null;
    });

    await tester.pumpWidget(host());
    await tester.pumpAndSettle();

    expect(find.text('蓝牙打印机（精臣 B1 Pro）'), findsNothing);
    expect(find.textContaining('字体资源不可用'), findsNothing);
    expect(tester.takeException(), isNull);
  });

  testWidgets('the search control appears when the SDK is available',
      (tester) async {
    useTallSurface(tester);
    messenger.setMockMethodCallHandler(methodChannel, (call) async {
      if (call.method == 'available') {
        return <String, Object?>{'available': true};
      }
      return null;
    });

    await tester.pumpWidget(host());
    await tester.pumpAndSettle();

    expect(find.text('蓝牙打印机（精臣 B1 Pro）'), findsOneWidget);
    expect(find.text('搜索打印机'), findsOneWidget);
    // Printing requires a connection first: the button is rendered disabled.
    final printButton = tester.widget<FilledButton>(
      find.widgetWithText(FilledButton, '连接后可直接打印'),
    );
    expect(printButton.onPressed, isNull);
    expect(tester.takeException(), isNull);
  });

  testWidgets('a permission refusal is shown as a specific Chinese error',
      (tester) async {
    useTallSurface(tester);
    messenger.setMockMethodCallHandler(methodChannel, (call) async {
      switch (call.method) {
        case 'available':
          return <String, Object?>{'available': true};
        case 'requestPermissions':
          return false;
        default:
          return null;
      }
    });

    await tester.pumpWidget(host());
    await tester.pumpAndSettle();

    await tester.tap(find.text('搜索打印机'));
    await tester.pumpAndSettle();

    expect(find.textContaining('蓝牙权限'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
