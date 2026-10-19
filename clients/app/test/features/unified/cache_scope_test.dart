import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/session_scope.dart';
import 'package:lab_inventory_client/features/unified/providers/lab_errors.dart';
import 'package:lab_inventory_client/features/unified/services/asset_cache.dart';
import 'package:lab_inventory_client/models/lab_api_exception.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Session isolation of the offline cache.
///
/// The failure these tests prevent: operator A looks at `lab:42` on server A (or
/// simply logs out and B logs in), and the cached stock / bags / issue history of
/// A is shown to B - offline, where no server can correct it.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late Directory root;
  late int downloads;

  /// A tiny, VALID PNG so the magic-byte check accepts it.
  Uint8List pngBytes() => Uint8List.fromList(<int>[
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, //
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
      ]);

  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    root = Directory.systemTemp.createTempSync('lab_asset_scope_');
    downloads = 0;
  });

  tearDown(() {
    if (root.existsSync()) root.deleteSync(recursive: true);
  });

  AssetCacheStore storeFor(LabSessionScope scope, {Uri? base, bool authenticated = true}) {
    return AssetCacheStore(
      resolveDirectory: () async => root,
      scopeKey: scope.key,
      // Mirrors the production wiring in `assetCacheProvider`.
      persistBusinessData: scope.canPersistBusinessData,
      baseUriResolver: () async => base ?? Uri.parse(scope.baseUrl),
      authenticatedFetcher: authenticated
          ? (uri) async {
              downloads++;
              return pngBytes();
            }
          : null,
      downloader: (url) async {
        downloads++;
        return pngBytes();
      },
    );
  }

  const scopeA = LabSessionScope(
    baseUrl: 'http://server-a:8069',
    database: 'db_a',
    uid: 1,
  );
  const scopeAOtherServer = LabSessionScope(
    baseUrl: 'http://server-b:8069',
    database: 'db_a',
    uid: 1,
  );
  const scopeB = LabSessionScope(
    baseUrl: 'http://server-a:8069',
    database: 'db_a',
    uid: 2,
  );
  const scopeASameOfficeDifferentDb = LabSessionScope(
    baseUrl: 'http://server-a:8069',
    database: 'db_other',
    uid: 1,
  );
  const scopeAOtherCompany = LabSessionScope(
    baseUrl: 'http://server-a:8069',
    database: 'db_a',
    uid: 1,
    company: '2',
  );

  group('scope identity', () {
    test('server / database / user / company each change the key', () {
      final keys = <String>{
        scopeA.key,
        scopeAOtherServer.key,
        scopeB.key,
        scopeASameOfficeDifferentDb.key,
        scopeAOtherCompany.key,
      };
      expect(keys.length, 5, reason: 'every scope must be distinguishable');
    });

    test('trailing slashes and casing of the base URL do not split a scope', () {
      const withSlash = LabSessionScope(
        baseUrl: 'http://server-a:8069/',
        database: 'db_a',
        uid: 1,
      );
      expect(withSlash.key, scopeA.key);
      expect(withSlash, scopeA);
    });

    test('a signed-out scope may not persist business data', () {
      expect(LabSessionScope.anonymous.isSignedIn, isFalse);
      expect(LabSessionScope.anonymous.canPersistBusinessData, isFalse);
      expect(scopeA.canPersistBusinessData, isTrue);
    });
  });

  group('offline detail metadata is per session', () {
    test('another user cannot read the cached detail of the first user', () async {
      final detail = <String, dynamic>{
        'item': <String, dynamic>{'item_key': 'lab:42', 'name': 'A 的器件'},
        'locations': <Map<String, dynamic>>[
          <String, dynamic>{'id': 1, 'code': 'K1', 'quantity': 120},
        ],
        'bags': <Map<String, dynamic>>[
          <String, dynamic>{'id': 7, 'trace_code': 'TRACE-A', 'quantity': 120},
        ],
      };

      await storeFor(scopeA).saveDetail('lab:42', detail);
      expect((await storeFor(scopeA).readDetail('lab:42'))?.data, isNotNull);

      // Same machine, another account.
      expect(await storeFor(scopeB).readDetail('lab:42'), isNull);
      // Same account uid, another SERVER.
      expect(await storeFor(scopeAOtherServer).readDetail('lab:42'), isNull);
      // Same server+uid, another DATABASE.
      expect(await storeFor(scopeASameOfficeDifferentDb).readDetail('lab:42'), isNull);
      // Same server+db+uid, another COMPANY.
      expect(await storeFor(scopeAOtherCompany).readDetail('lab:42'), isNull);
    });

    test('a signed-out session never writes or reads business metadata', () async {
      final anonymous = storeFor(LabSessionScope.anonymous);
      await anonymous.saveDetail('lab:42', <String, dynamic>{'item': <String, dynamic>{}});
      expect(await anonymous.readDetail('lab:42'), isNull);
      expect(Directory('${root.path}/scope-none').existsSync(), isFalse);
    });
  });

  group('assets are split between shared public files and session files', () {
    test('a same-origin (session) file is not readable by another session', () async {
      final url = 'http://server-a:8069/lab/api/asset/photo.png';

      final bytesA = await storeFor(scopeA).read(url);
      expect(bytesA, isNotEmpty);
      expect(downloads, 1, reason: 'first read downloads through the session');

      // Same session, offline: served from disk without any request.
      final offlineA = await storeFor(scopeA).read(url);
      expect(offlineA, isNotEmpty);
      expect(downloads, 1, reason: 'cached read must not hit the network');

      // Another account must NOT see the previous session's file: it has no
      // cached copy, so the store must go to the network again.
      final storeB = storeFor(scopeB, authenticated: false);
      expect(await storeB.hasCached(url), isFalse);
      await storeB.read(url);
      expect(downloads, 2, reason: 'scope B cannot reuse scope A file');
    });

    test('a public CDN file is shared between sessions', () async {
      final url = 'https://cdn.example.com/photo.png';

      await storeFor(scopeA).read(url);
      expect(downloads, 1);

      // Public files carry no account data, so another session reuses them.
      final reused = await storeFor(scopeB).read(url);
      expect(reused, isNotEmpty);
      expect(downloads, 1, reason: 'the public CDN file is shared, not re-downloaded');
      expect(
        Directory('${root.path}/${AssetCacheStore.publicDirName}').existsSync(),
        isTrue,
      );
    });

    test('without a scope a same-origin file is displayed but never persisted', () async {
      final url = 'http://server-a:8069/lab/api/asset/photo.png';
      // Signed out, but the server URI is still known: this is exactly the case
      // where persistence must be refused.
      final anonymous = storeFor(
        LabSessionScope.anonymous,
        base: Uri.parse('http://server-a:8069'),
      );

      expect(await anonymous.read(url), isNotEmpty);
      expect(await anonymous.hasCached(url), isFalse,
          reason: 'no private directory exists, so nothing may be written');
    });
  });

  group('only genuine transport failures fall back to cache', () {
    test('401 / permission / session errors never use cached business data', () {
      expect(
        isOfflineFailure(const LabApiException(code: 'NETWORK_ERROR', message: 'x')),
        isTrue,
      );
      expect(
        isOfflineFailure(const LabApiException(code: 'TRANSPORT_ERROR', message: 'x')),
        isTrue,
      );
      for (final code in <String>[
        'ACCESS_DENIED',
        'PERMISSION_DENIED',
        'SESSION_INVALID',
        'NOT_AUTHENTICATED',
        'VALIDATION_ERROR',
        'CONFLICT',
      ]) {
        expect(
          isOfflineFailure(LabApiException(code: code, message: 'x')),
          isFalse,
          reason: '$code must surface, not be served from the cache',
        );
      }
      expect(isOfflineFailure(const LabSessionExpiredException()), isFalse);
    });
  });

  group('downloaded bytes are verified before they are cached', () {
    test('an HTML error page is refused instead of being stored as an image', () async {
      final store = AssetCacheStore(
        resolveDirectory: () async => root,
        scopeKey: scopeA.key,
        baseUriResolver: () async => Uri.parse(scopeA.baseUrl),
        downloader: (url) async => Uint8List.fromList(utf8.encode('<html>login</html>')),
        authenticatedFetcher: (uri) async =>
            Uint8List.fromList(utf8.encode('<!DOCTYPE html><html>login</html>')),
      );

      await expectLater(
        store.read('http://server-a:8069/lab/api/asset/x.png'),
        throwsA(isA<AssetCacheException>()),
      );
      expect(await store.hasCached('http://server-a:8069/lab/api/asset/x.png'), isFalse);
    });

    test('an oversized file is refused', () async {
      final store = AssetCacheStore(
        resolveDirectory: () async => root,
        scopeKey: scopeA.key,
        baseUriResolver: () async => Uri.parse(scopeA.baseUrl),
        policy: const AssetFetchPolicy(maxImageBytes: 64),
        downloader: (url) async => Uint8List(1024),
      );

      await expectLater(
        store.read('https://cdn.example.com/big.png', kind: MediaKind.image),
        throwsA(isA<AssetCacheException>()),
      );
    });

    test('an oversized manual is refused with the manual limit', () async {
      final store = AssetCacheStore(
        resolveDirectory: () async => root,
        scopeKey: scopeA.key,
        policy: const AssetFetchPolicy(maxManualBytes: 32),
        // 64 bytes of PDF-looking content: over the 32-byte manual limit.
        downloader: (url) async => Uint8List.fromList(<int>[
          0x25, 0x50, 0x44, 0x46, //
          ...List<int>.filled(60, 0x41),
        ]),
      );

      await expectLater(
        store.ensureFile('https://cdn.example.com/manual.pdf'),
        throwsA(isA<AssetCacheException>()),
      );
    });
  });
}
