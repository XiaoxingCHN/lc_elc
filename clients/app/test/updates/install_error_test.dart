import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:cryptography/cryptography.dart' as crypto;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:lab_inventory_client/providers/auth_provider.dart';
import 'package:lab_inventory_client/routes/app_router.dart';
import 'package:lab_inventory_client/updates/update_controller.dart';
import 'package:lab_inventory_client/updates/update_manifest.dart';
import 'package:lab_inventory_client/updates/update_platform.dart';
import 'package:lab_inventory_client/updates/update_ui.dart';

import 'update_ui_test.dart' show NoNetwork;

/// Real file integrity and canonical paths are covered separately.
class MemoryPackage implements File {
  final bytes = Uint8List.fromList([1, 2, 3]);
  @override
  String get path => '/fixture/update.apk';
  @override
  Directory get parent => Directory.systemTemp;
  @override
  Future<int> length() async => bytes.length;
  @override
  Stream<List<int>> openRead([int? start, int? end]) =>
      Stream.value(bytes.sublist(start ?? 0, end));
  @override
  Future<Uint8List> readAsBytes() async => bytes;
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class RejectedInstall extends UpdatePlatform {
  RejectedInstall(this.code, this.message);
  final String code, message;
  int calls = 0;
  @override
  Future<void> install(
    File file,
    UpdateManifest release,
    Directory cache,
  ) async {
    calls++;
    expect(await file.readAsBytes(), [1, 2, 3]);
    throw PlatformException(code: code, message: message);
  }
}

void main() {
  for (final failure in [
    ('INSTALL_PERMISSION', '请允许安装后返回重试。'),
    ('INSTALL_CACHE_PATH', '更新文件不在应用私有缓存目录内，请重新下载。'),
    ('INSTALL_SYSTEM_3', '安装已取消，原版本保留，可稍后重试。'),
  ]) {
    testWidgets(
      'install failure ${failure.$1} preserves native reason and releases business gate',
      (tester) async {
        final fixture = await tester.runAsync(() async {
          final dir = Directory.systemTemp;
          final file = MemoryPackage();
          final algorithm = crypto.Ed25519();
          final pair = await algorithm.newKeyPair();
          final payload = utf8.encode(
            jsonEncode({
              'schema': 1,
              'app_id': updateAppId,
              'release_id': 'fixture-build6',
              'filename': 'update.apk',
              'version': '1.1.3',
              'build_number': 6,
              'release_sequence': 2,
              'platform': 'android',
              'arch': 'universal',
              'channel': 'stable',
              'package_type': 'apk',
              'size': 3,
              'sha256': sha256.convert([1, 2, 3]).toString(),
              'api_min': 1,
              'api_max': 1,
            }),
          );
          final release = await UpdateManifest.verify(
            {
              'key_id': 'fixture',
              'payload': base64Encode(payload),
              'signature': base64Encode(
                (await algorithm.sign(payload, keyPair: pair)).bytes,
              ),
            },
            keys: {
              'fixture': base64Encode((await pair.extractPublicKey()).bytes),
            },
          );
          return (dir, file, release);
        });
        final (dir, file, release) = fixture!;
        final controller =
            UpdateController(
                transport: NoNetwork(),
                platform: 'android',
                arch: 'universal',
                build: 5,
                directory: () async => dir,
                facts: () async => {},
                unmetered: () async => false,
                authenticated: () => true,
                readSequence: () async => 0,
                saveSequence: (_) async {},
              )
              ..phase = UpdatePhase.ready
              ..release = release
              ..package = file;
        final native = RejectedInstall(failure.$1, failure.$2);
        final router = GoRouter(
          initialLocation: '/catalog',
          routes: [
            GoRoute(
              path: '/catalog',
              builder: (context, state) => const SizedBox(),
            ),
          ],
        );
        addTearDown(router.dispose);
        final container = ProviderContainer(
          overrides: [
            updateControllerProvider.overrideWith((ref) => controller),
            updatePlatformProvider.overrideWithValue(native),
            appRouterProvider.overrideWithValue(router),
          ],
        );
        addTearDown(container.dispose);
        await tester.pumpWidget(
          UncontrolledProviderScope(
            container: container,
            child: const MaterialApp(home: Scaffold(body: UpdateSheet())),
          ),
        );
        await tester.ensureVisible(find.text('安装更新'));
        await tester.tap(find.text('安装更新'));
        await tester.pumpAndSettle();
        await tester.tap(find.widgetWithText(FilledButton, '安装'));
        await tester.pumpAndSettle();
        expect(native.calls, 1);
        expect(find.text('${failure.$2}（${failure.$1}）'), findsOneWidget);
        expect(find.text('安装未开始，请检查安装权限或重新下载完整包。'), findsNothing);
        final client = container.read(odooClientProvider);
        expect(client.beginClientInstall(), isTrue);
        client.endClientInstall();
        expect(tester.takeException(), isNull);
      },
    );
  }
}
