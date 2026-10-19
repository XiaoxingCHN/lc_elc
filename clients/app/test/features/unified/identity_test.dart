import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/identity.dart';
import 'package:lab_inventory_client/features/unified/models/json_read.dart';

/// Identity rules pinned by `business_api_contract.json` (root-approved).
///
/// The failure this file exists to prevent: merging two different components, or
/// splitting one component into two cards, because a code was normalized or
/// validated differently on the client than on the server.
void main() {
  group('normalization', () {
    test('full-width digits/letters become half-width and upper-case', () {
      expect(normalizeCatalogCode('  ｃ１２３  '), 'C123');
      expect(normalizeCatalogCode('c123456'), 'C123456');
      expect(normalizeCatalogCode('lcsc:C999'), 'C999');
    });

    test('accepts C followed by a positive integer, with no 4-digit minimum', () {
      expect(isUsableCatalogCode('C1'), isTrue);
      expect(isUsableCatalogCode('C123'), isTrue);
      expect(isUsableCatalogCode('C9999999'), isTrue);
    });

    test('rejects everything that must not merge', () {
      for (final invalid in <Object?>[
        null,
        '',
        '   ',
        'C',
        'C0',
        'C00',
        '-',
        'N/A',
        '待补',
        'ABC',
        '123456',
        bool.fromEnvironment('x'),
      ]) {
        expect(
          isUsableCatalogCode(invalid),
          isFalse,
          reason: 'must be unusable: $invalid',
        );
        expect(catalogItemKey(invalid), isNull, reason: 'must not build a key: $invalid');
      }
    });
  });

  group('item keys', () {
    test('catalog and lab keys use the contract prefixes', () {
      expect(catalogItemKey('c123'), 'lcsc:C123');
      expect(labItemKey(42), 'lab:42');
      expect(labItemKey(0), isNull);
      expect(labItemKey(null), isNull);
    });

    test('identity kind is derived from the key', () {
      expect(identityKindOf('lcsc:C123'), IdentityKind.catalog);
      expect(identityKindOf('lab:42'), IdentityKind.lab);
      expect(identityKindOf('whatever'), IdentityKind.unknown);
    });
  });

  group('deriveItemKey', () {
    test('prefers the server item_key', () {
      expect(
        deriveItemKey(<String, dynamic>{'item_key': 'lab:42', 'catalog_code': 'C9'}),
        'lab:42',
      );
    });

    test('derives from catalog_code when item_key is absent', () {
      expect(deriveItemKey(<String, dynamic>{'catalog_code': 'c7'}), 'lcsc:C7');
    });

    test('falls back to the first local template id', () {
      expect(
        deriveItemKey(<String, dynamic>{
          'lab_template_ids': <int>[12, 13],
        }),
        'lab:12',
      );
    });

    test('never merges an invalid code, and never invents a key', () {
      expect(
        deriveItemKey(<String, dynamic>{'item_key': '', 'catalog_code': '待补'}),
        isNull,
      );
      expect(deriveItemKey(<String, dynamic>{'name': '无编号物料'}), isNull);
    });
  });

  group('payload helpers', () {
    test('bag and location payloads match the printed QR content', () {
      expect(bagPayload('TRACE1'), 'LABB:TRACE1');
      expect(locationPayload('K000001'), 'LABL:K000001');
      expect(unwrapPayload('labb:TRACE1'), 'TRACE1');
      expect(unwrapPayload('LABL:K000001'), 'K000001');
      expect(unwrapPayload('C123'), 'C123');
    });
  });

  group('asset references', () {
    test('accepts absolute URLs and same-origin paths, refuses the rest', () {
      expect(asAssetReference('https://cdn.example/x.jpg'), 'https://cdn.example/x.jpg');
      expect(asAssetReference('/lab/api/asset/abc'), '/lab/api/asset/abc');
      expect(asAssetReference('lab/api/asset/abc'), 'lab/api/asset/abc');
      expect(asAssetReference('javascript:alert(1)'), isNull);
      expect(asAssetReference('data:image/png;base64,AAAA'), isNull);
      expect(asAssetReference('C123456'), isNull);
      expect(asAssetReference(''), isNull);
    });

    test('a base64 blob is never mistaken for a relative asset path', () {
      // A long Odoo base64 image containing '/' and '=' must not be treated as
      // a server-relative URL (the model reads image_url/thumb_url only, and
      // this guard covers a base64 payload arriving in one of those fields).
      final base64 = 'iVBORw0KGgoAAAANSUhEUg' + 'AAAA' * 200 + '/+AAAAAElFTkSuQmCC==';
      expect(base64.length, greaterThan(512));
      expect(asAssetReference(base64), isNull);
    });
  });
}
