import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/session_scope.dart';
import 'package:lab_inventory_client/features/unified/services/asset_cache.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// A session-only (LAN acceleration) login must leave NO business data on
/// disk: no asset file, no sidecar, no offline detail, no pin list.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory root;

  Uint8List pngBytes() => Uint8List.fromList(<int>[
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, //
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
      ]);

  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    root = Directory.systemTemp.createTempSync('lab_ephemeral_cache_');
  });

  tearDown(() {
    if (root.existsSync()) root.deleteSync(recursive: true);
  });

  const ephemeralScope = LabSessionScope(
    baseUrl: 'http://192.168.31.105:8069',
    database: 'LcHardwareHouse',
    uid: 7,
    ephemeral: true,
  );

  AssetCacheStore storeFor(LabSessionScope scope, {int Function()? onDownload}) {
    return AssetCacheStore(
      resolveDirectory: () async => root,
      scopeKey: scope.key,
      persistBusinessData: scope.canPersistBusinessData,
      memoryOnly: scope.ephemeral,
      baseUriResolver: () async => Uri.parse(scope.baseUrl),
      authenticatedFetcher: (uri) async {
        onDownload?.call();
        return pngBytes();
      },
      downloader: (url) async {
        onDownload?.call();
        return pngBytes();
      },
    );
  }

  test('an ephemeral scope never persists business data', () {
    expect(ephemeralScope.canPersistBusinessData, isFalse);
    expect(ephemeralScope.isSignedIn, isTrue);
    // The scope key still isolates the in-memory state from a persistent one.
    const persistent = LabSessionScope(
      baseUrl: 'http://192.168.31.105:8069',
      database: 'LcHardwareHouse',
      uid: 7,
    );
    expect(ephemeralScope.key, isNot(persistent.key));
  });

  test('assets are served from memory and no file/sidecar is written',
      () async {
    final store = storeFor(ephemeralScope);
    const url = '/lab/api/asset/data?item=lab:42';

    final first = await store.read(url);
    expect(first, pngBytes());
    final second = await store.read(url);
    expect(second, pngBytes());

    // Nothing reached the temp directory the store was given.
    final files = root.listSync(recursive: true).whereType<File>().toList();
    expect(files, isEmpty, reason: 'memory-only store must not touch disk');
  });

  test('a fresh ephemeral store cannot read another run\'s bytes', () async {
    final first = storeFor(ephemeralScope);
    await first.read('/lab/api/asset/data?item=lab:42');

    // Memory is per-store, and disk was never used, so a new store re-downloads.
    var downloads = 0;
    final third = storeFor(ephemeralScope, onDownload: () => downloads++);
    await third.read('/lab/api/asset/data?item=lab:42');
    expect(downloads, 1);
  });

  test('pinning does not write the pin list to SharedPreferences', () async {
    final store = storeFor(ephemeralScope);
    await store.pin(<({String url, MediaKind kind})>[
      (url: '/lab/api/asset/data?item=lab:42', kind: MediaKind.image),
    ]);
    // Let the background fetch finish.
    await Future<void>.delayed(const Duration(milliseconds: 50));

    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getKeys(), isEmpty);
  });

  test('offline detail metadata is never written for an ephemeral session',
      () async {
    final store = storeFor(ephemeralScope);
    await store.saveDetail('lab:42', <String, dynamic>{
      'item': <String, dynamic>{'name': 'A'},
    });

    expect(await store.readDetail('lab:42'), isNull);
    final files = root.listSync(recursive: true).whereType<File>().toList();
    expect(files, isEmpty);
  });

  test('clear() on an ephemeral store does not delete the shared public cache',
      () async {
    final publicFile = File('${root.path}/${AssetCacheStore.publicDirName}/keep.png')
      ..createSync(recursive: true)
      ..writeAsBytesSync(<int>[1, 2, 3]);

    final store = storeFor(ephemeralScope);
    await store.clear();

    expect(publicFile.existsSync(), isTrue);
  });
}
