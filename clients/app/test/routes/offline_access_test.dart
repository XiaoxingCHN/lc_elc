import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/routes/offline_access.dart';

/// The read-only offline contract, as the auth/router owner defines it.
///
/// The UI owner's screens implement the cached-data view; these assertions pin
/// WHICH states are allowed to exist without a session, so a later change cannot
/// silently turn the offline entry into a back door for business writes.
void main() {
  group('OfflineAccess.allows', () {
    test('the list and one detail are allowed with the explicit flag', () {
      expect(
        OfflineAccess.allows(
          OfflineAccess.catalog,
          <String, String>{'offline': '1'},
        ),
        isTrue,
      );
      expect(
        OfflineAccess.allows(
          OfflineAccess.itemDetail,
          <String, String>{'offline': '1', 'item_key': 'lcsc:C25804'},
        ),
        isTrue,
      );
    });

    test('without the flag nothing is allowed offline', () {
      expect(OfflineAccess.allows(OfflineAccess.catalog, <String, String>{}),
          isFalse);
      expect(
        OfflineAccess.allows(
          OfflineAccess.catalog,
          <String, String>{'offline': '0'},
        ),
        isFalse,
      );
    });

    test('every business write route stays blocked when signed out', () {
      const writeRoutes = <String>[
        '/receipt',
        '/issue',
        '/return',
        '/labels',
        '/history',
        '/products',
        '/home',
      ];
      for (final route in writeRoutes) {
        expect(
          OfflineAccess.allows(route, <String, String>{'offline': '1'}),
          isFalse,
          reason: '$route must require a real sign-in',
        );
      }
    });

    test('the flag cannot be smuggled onto an unrelated path', () {
      expect(
        OfflineAccess.allows(
          '/catalog/item/extra',
          <String, String>{'offline': '1'},
        ),
        isFalse,
      );
    });
  });

  group('OfflineAccess locations', () {
    test('the catalog location carries the flag', () {
      expect(OfflineAccess.catalogLocation(), '/catalog?offline=1');
    });

    test('the item location carries flag and encoded key', () {
      final location = OfflineAccess.itemLocation('lcsc:C25804');
      expect(location, startsWith('/catalog/item?'));
      expect(location, contains('offline=1'));
      expect(location, contains('item_key=lcsc%3AC25804'));
    });
  });
}
