import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/updates/update_controller.dart';
import 'package:lab_inventory_client/updates/update_manifest.dart';
import 'package:lab_inventory_client/updates/update_platform.dart';
import 'package:lab_inventory_client/updates/update_transport.dart';
import 'package:lab_inventory_client/updates/update_ui.dart';

class NoNetwork implements UpdateTransport {
  @override
  Future<Map<String, dynamic>?> check(
    String p,
    String a,
    CancelToken t,
  ) async => null;
  @override
  Future<void> download(
    UpdateManifest r,
    File f,
    CancelToken t,
    void Function(int) onProgress,
  ) async => throw StateError('unexpected download');
}

class TestPlatform extends UpdatePlatform {
  @override
  int get build => 4;
  @override
  String get version => '1.1.1';
}

void main() {
  for (final width in [320.0, 1280.0]) {
    for (final brightness in Brightness.values) {
      testWidgets('updates fit $width / $brightness / 200% text', (
        tester,
      ) async {
        tester.view.reset();
        tester.view.physicalSize = Size(width, 800);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final c = UpdateController(
          transport: NoNetwork(),
          platform: 'windows',
          arch: 'x64',
          build: 4,
          directory: () async => Directory.systemTemp,
          facts: () async => {},
          unmetered: () async => false,
          authenticated: () => false,
          readSequence: () async => 0,
          saveSequence: (_) async {},
        );
        await tester.pumpWidget(
          ProviderScope(
            overrides: [
              updateControllerProvider.overrideWith((ref) => c),
              updatePlatformProvider.overrideWithValue(TestPlatform()),
            ],
            child: MaterialApp(
              theme: ThemeData(brightness: brightness),
              builder: (context, child) => MediaQuery(
                data: MediaQuery.of(context)
                    .copyWith(textScaler: const TextScaler.linear(2)),
                child: child!,
              ),
              home: const Scaffold(body: UpdateSheet()),
            ),
          ),
        );
        expect(find.text('关于与更新'), findsOneWidget);
        await tester.ensureVisible(find.text('检查更新'));
        await tester.tap(find.text('检查更新'));
        await tester.pumpAndSettle();
        expect(find.text('服务器尚未发布更新'), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  }
}
