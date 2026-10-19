import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/config/odoo_config.dart';
import 'package:lab_inventory_client/models/odoo_exception.dart';
import 'package:lab_inventory_client/services/odoo_client.dart';

// ---------------------------------------------------------------------------
// Odoo integration tests.
//
// The "live integration" group below needs a reachable Odoo 19 server and a
// real account. It is SKIPPED unless all four values are supplied at run time,
// so `flutter test` on a machine without the LAN server reports "skipped"
// instead of failing on connection timeouts.
//
//   flutter test test/services/odoo_client_test.dart \
//     --dart-define=LAB_TEST_ODOO_URL=http://192.168.31.105:8069 \
//     --dart-define=LAB_TEST_ODOO_DB=LcHardwareHouse \
//     --dart-define=LAB_TEST_ODOO_USER=<user> \
//     --dart-define=LAB_TEST_ODOO_PASSWORD=<password>
//
// No credential is hard-coded in this file on purpose.
// ---------------------------------------------------------------------------

const _testUrl = String.fromEnvironment('LAB_TEST_ODOO_URL', defaultValue: '');
const _testDb = String.fromEnvironment('LAB_TEST_ODOO_DB', defaultValue: '');
const _testUser =
    String.fromEnvironment('LAB_TEST_ODOO_USER', defaultValue: '');
const _testPassword =
    String.fromEnvironment('LAB_TEST_ODOO_PASSWORD', defaultValue: '');

bool get _hasCredentials =>
    _testUrl.isNotEmpty &&
    _testDb.isNotEmpty &&
    _testUser.isNotEmpty &&
    _testPassword.isNotEmpty;

const _skipReason =
    'Needs a reachable Odoo server. Re-run with --dart-define='
    'LAB_TEST_ODOO_URL / LAB_TEST_ODOO_DB / LAB_TEST_ODOO_USER / '
    'LAB_TEST_ODOO_PASSWORD.';

/// A client pointed at a closed port: used where no server may be contacted.
OdooClient _offlineClient() =>
    OdooClient(baseUrl: 'http://127.0.0.1:1', database: 'unused');

void main() {
  group('OdooClient offline contract (no server required)', () {
    test('RPC without authentication throws OdooException', () async {
      await expectLater(
        _offlineClient().search_read('product.template', const [], const ['id']),
        throwsA(isA<OdooException>()),
      );
    });

    test('configure() rejects a URL without an http(s) scheme', () {
      final client = _offlineClient();
      expect(
        () => client.configure(baseUrl: '192.168.31.105:8069', database: 'db'),
        throwsA(isA<OdooValidationException>()),
      );
    });

    test('configure() rejects an empty database name', () {
      final client = _offlineClient();
      expect(
        () => client.configure(
          baseUrl: 'http://192.168.31.105:8069',
          database: '   ',
        ),
        throwsA(isA<OdooValidationException>()),
      );
    });

    test('configure() normalises trailing slash and trims database', () {
      final client = _offlineClient();
      client.configure(
        baseUrl: 'http://192.168.31.105:8069/',
        database: ' LcHardwareHouse ',
      );
      expect(client.baseUrl, 'http://192.168.31.105:8069');
      expect(client.database, 'LcHardwareHouse');
    });

    test('normalizeBaseUrl / isValidBaseUrl behave as documented', () {
      expect(OdooConfig.normalizeBaseUrl('  http://h:8069//  '), 'http://h:8069');
      expect(OdooConfig.isValidBaseUrl('http://h:8069'), isTrue);
      expect(OdooConfig.isValidBaseUrl('https://h:8069'), isTrue);
      expect(OdooConfig.isValidBaseUrl('h:8069'), isFalse);
      expect(OdooConfig.isValidBaseUrl(''), isFalse);
    });
  });

  group('OdooClient live integration', () {
    late OdooClient client;

    setUpAll(() {
      client = OdooClient(baseUrl: _testUrl, database: _testDb);
    });

    test('authenticates with the supplied account', () async {
      final uid = await client.authenticate(_testUser, _testPassword);
      expect(uid, greaterThan(0));
      expect(client.isAuthenticated, isTrue);
      expect(client.uid, equals(uid));
    });

    test('rejects wrong credentials', () async {
      await expectLater(
        client.authenticate('__definitely_wrong__', '__wrong__'),
        throwsA(isA<OdooAuthException>()),
      );
    });

    test('search_read returns lab fields', () async {
      await client.authenticate(_testUser, _testPassword);
      final products = await client.search_read(
        'product.template',
        const [],
        const ['id', 'name', 'lab_sn', 'lab_lcsc_code', 'lab_mpn'],
        limit: 3,
      );
      expect(products.length, lessThanOrEqualTo(3));
      for (final product in products) {
        expect(product['id'], isA<int>());
      }
    });

    test('fields_get exposes the lab_* fields', () async {
      await client.authenticate(_testUser, _testPassword);
      final fields = await client.fields_get('product.template');
      expect(fields, contains('name'));
      expect(fields, contains('lab_sn'));
      expect(fields, contains('lab_lcsc_code'));
    });

    test('search_count does not throw', () async {
      await client.authenticate(_testUser, _testPassword);
      final count = await client.search_count('product.template', const []);
      expect(count, greaterThanOrEqualTo(0));
    });
  }, skip: _hasCredentials ? null : _skipReason);
}
