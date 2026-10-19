import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:archive/archive_io.dart';
import 'package:crypto/crypto.dart';
import 'package:cryptography/cryptography.dart' as signing;
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/updates/update_manifest.dart';
import 'package:lab_inventory_client/updates/update_controller.dart';
import 'package:lab_inventory_client/updates/update_transport.dart';
import 'package:lab_inventory_client/updates/desktop_update.dart';

void main() {
  late signing.SimpleKeyPair pair;
  late Map<String, String> keys;
  late Directory dir;
  final bytes = utf8.encode('verified complete release');
  Future<Map<String, dynamic>> envelope([
    Map<String, dynamic> changes = const {},
  ]) async {
    final d = <String, dynamic>{
      'schema': 1,
      'app_id': updateAppId,
      'release_id': 'client-5',
      'filename': 'client.zip',
      'version': '1.1.2',
      'build_number': 5,
      'release_sequence': 5,
      'platform': 'windows',
      'arch': 'x64',
      'channel': 'stable',
      'package_type': 'zip',
      'size': bytes.length,
      'sha256': sha256.convert(bytes).toString(),
      'api_min': 1,
      'api_max': 1,
      'requirements': <String, int>{},
      ...changes,
    };
    final payload = utf8.encode(jsonEncode(d));
    return {
      'key_id': 'test',
      'payload': base64Encode(payload),
      'signature': base64Encode(
        (await signing.Ed25519().sign(payload, keyPair: pair)).bytes,
      ),
    };
  }

  setUp(() async {
    pair = await signing.Ed25519().newKeyPair();
    keys = {'test': base64Encode((await pair.extractPublicKey()).bytes)};
    final temp = await Directory.systemTemp.createTemp('lc-updater-test-');
    // Windows may expose TEMP using an 8.3 alias. The installer deliberately
    // requires canonical roots, so fixtures must use the resolved path too.
    dir = Directory(await temp.resolveSymbolicLinks());
  });
  tearDown(() async {
    await dir.delete(recursive: true);
  });

  test(
    'signed decision fields cannot be changed and unknown keys fail',
    () async {
      final good = await envelope();
      final release = await UpdateManifest.verify(good, keys: keys);
      expect(release.matches('windows', 'x64', 4, 5, {}), isTrue);
      final changed = {
        ...good,
        'payload': base64Encode(
          utf8.encode(jsonEncode({...release.data, 'build_number': 90})),
        ),
      };
      await expectLater(
        UpdateManifest.verify(changed, keys: keys),
        throwsFormatException,
      );
      await expectLater(UpdateManifest.verify(good), throwsFormatException);
    },
  );
  test(
    'build, sequence, architecture, API and OS requirements gate update',
    () async {
      final release = await UpdateManifest.verify(
        await envelope({
          'requirements': {'windows_build': 19041},
        }),
        keys: keys,
      );
      expect(
        release.matches('windows', 'x64', 4, 4, {'windows_build': 19041}),
        isTrue,
      );
      for (final value in [
        release.matches('windows', 'x64', 5, 5, {'windows_build': 19041}),
        release.matches('linux', 'x64', 4, 5, {'windows_build': 19041}),
        release.matches('windows', 'arm64', 4, 5, {'windows_build': 19041}),
        release.matches('windows', 'x64', 4, 6, {'windows_build': 19041}),
        release.matches('windows', 'x64', 4, 5, {}),
      ]) {
        expect(value, isFalse);
      }
      await expectLater(
        UpdateManifest.verify(await envelope({'api_min': 2}), keys: keys),
        throwsFormatException,
      );
      await expectLater(
        UpdateManifest.verify(
          await envelope({'filename': '../escape.zip'}),
          keys: keys,
        ),
        throwsFormatException,
      );
      await expectLater(
        UpdateManifest.verify(
          await envelope({'size': maxUpdateBytes + 1}),
          keys: keys,
        ),
        throwsFormatException,
      );
    },
  );
  test('streamed integrity rejects corrupt or truncated package', () async {
    final release = await UpdateManifest.verify(await envelope(), keys: keys);
    final file = File('${dir.path}/file');
    await file.writeAsBytes(bytes);
    await verifyUpdateFile(file, release);
    await file.writeAsBytes(List.filled(bytes.length, 0));
    await expectLater(verifyUpdateFile(file, release), throwsFormatException);
    await file.writeAsBytes([0]);
    await expectLater(verifyUpdateFile(file, release), throwsFormatException);
  });
  UpdateController controller(
    FakeTransport transport, {
    bool metered = false,
    bool loggedIn = true,
    int sequence = 0,
  }) => UpdateController(
    transport: transport,
    platform: 'windows',
    arch: 'x64',
    build: 4,
    directory: () async => dir,
    facts: () async => {},
    unmetered: () async => !metered,
    authenticated: () => loggedIn,
    readSequence: () async => sequence,
    saveSequence: (s) async {
      sequence = s;
    },
    keys: keys,
  );
  test(
    'startup auto downloads once on unmetered, and reuses verified cache',
    () async {
      final transport = FakeTransport(await envelope(), bytes);
      final c = controller(transport);
      addTearDown(c.dispose);
      await c.check();
      expect(c.phase, UpdatePhase.ready);
      expect(transport.downloads, 1);
      await c.download();
      expect(transport.downloads, 1);
      expect(await c.package!.readAsBytes(), bytes);
    },
  );
  test(
    'metered/unknown network and signed-out state do not auto download',
    () async {
      for (final options in [(true, true), (false, false)]) {
        final transport = FakeTransport(await envelope(), bytes);
        final c = controller(
          transport,
          metered: options.$1,
          loggedIn: options.$2,
        );
        await c.check();
        expect(c.phase, UpdatePhase.available);
        expect(transport.downloads, 0);
        c.dispose();
      }
    },
  );
  test(
    'corruption never becomes ready and temporary package is removed',
    () async {
      final transport = FakeTransport(await envelope(), [0]);
      final c = controller(transport);
      addTearDown(c.dispose);
      await c.check();
      expect(c.phase, UpdatePhase.available);
      expect(c.package, isNull);
      expect(await dir.list().toList(), isEmpty);
    },
  );
  test(
    'scope disposal drops late response and deduplicates parallel checks',
    () async {
      final transport = FakeTransport(await envelope(), bytes)
        ..gate = Completer<void>();
      final c = controller(transport);
      final pending = c.check();
      await Future<void>.delayed(Duration.zero);
      await c.check();
      expect(transport.checks, 1);
      c.dispose();
      transport.gate!.complete();
      await pending;
      expect(transport.downloads, 0);
    },
  );
  test('offline failure can recover without touching authentication', () async {
    final transport = FakeTransport(await envelope(), bytes)..fail = true;
    final c = controller(transport);
    addTearDown(c.dispose);
    await c.check();
    expect(c.phase, UpdatePhase.error);
    transport.fail = false;
    await c.check();
    expect(c.phase, UpdatePhase.ready);
  });
  test('no published release is distinct from current version', () async {
    final c = controller(FakeTransport(null, bytes));
    addTearDown(c.dispose);
    await c.check();
    expect(c.phase, UpdatePhase.unavailable);
  });
  test(
    'safe extraction rejects traversal, links and duplicate names',
    () async {
      for (final name in [
        'bundle/../escaped',
        '/bundle/file',
        'bundle/C:/file',
        'bundle/a\\..\\file',
      ]) {
        final file = File('${dir.path}/attack.zip');
        await file.writeAsBytes(
          ZipEncoder().encode(Archive()..addFile(ArchiveFile(name, 1, [1]))),
        );
        await expectLater(
          extractBundle(file, Directory('${dir.path}/out'), 'windows'),
          throwsFormatException,
        );
        expect(await Directory('${dir.path}/out').exists(), isFalse);
      }
    },
  );
  test('complete installation switch retains old version and rolls back bad startup', () async {
    final release = await UpdateManifest.verify(await envelope(), keys: keys);
    Future<Directory> bundle(String name, int build) async {
      final root = Directory('${dir.path}/$name');
      await root.create();
      await File('${root.path}/client-install.json').writeAsString(
        jsonEncode({
          'app_id': updateAppId,
          'layout': 1,
          'build': build,
          'platform': 'windows',
        }),
      );
      for (final file in [
        'lab_inventory_client.exe',
        'client_update_helper.exe',
        'flutter_windows.dll',
        'data/flutter_assets/NOTICES.Z',
      ]) {
        final f = File('${root.path}/$file');
        await f.parent.create(recursive: true);
        await f.writeAsString('build$build');
      }
      return root;
    }

    final old = await bundle('current', 4);
    final next = await bundle('next', 5);
    await expectLater(
      replaceInstallation(
        root: old,
        next: next,
        release: release,
        launch: (root, nonce, build) async => false,
      ),
      throwsFormatException,
    );
    expect((await installationIdentity(old))['build'], 4);
    expect(
      await Directory('${dir.path}/.lab-client-failed-client-5').exists(),
      isTrue,
    );
    final second = await bundle('new-current', 4);
    final secondNext = await bundle('new-next', 5);
    // Unique release identity has separate retained slots/transaction.
    final secondRelease = await UpdateManifest.verify(
      await envelope({'release_id': 'client-5b'}),
      keys: keys,
    );
    await replaceInstallation(
      root: second,
      next: secondNext,
      release: secondRelease,
      launch: (root, nonce, build) async => true,
    );
    expect((await installationIdentity(second))['build'], 5);
    expect(
      await Directory('${dir.path}/.lab-client-previous-4-client-5b').exists(),
      isTrue,
    );
  });
}

class FakeTransport implements UpdateTransport {
  FakeTransport(this.envelope, this.bytes);
  final Map<String, dynamic>? envelope;
  final List<int> bytes;
  int checks = 0, downloads = 0;
  bool fail = false;
  Completer<void>? gate;
  @override
  Future<Map<String, dynamic>?> check(
    String platform,
    String arch,
    CancelToken token,
  ) async {
    checks++;
    if (gate != null) await gate!.future;
    if (fail) throw const SocketException('offline');
    return envelope;
  }

  @override
  Future<void> download(
    UpdateManifest release,
    File target,
    CancelToken token,
    void Function(int) onProgress,
  ) async {
    downloads++;
    await target.writeAsBytes(bytes);
    onProgress(bytes.length);
  }
}
