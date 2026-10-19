import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/config/odoo_config.dart';
import 'package:lab_inventory_client/services/login_memory_store.dart';

/// The whole "how long may a remembered password sign in by itself" rule is a
/// pure function, so the boundary is pinned here without a server, without
/// waiting ten days and without touching the machine clock.
void main() {
  const window = Duration(days: 10);
  final now = DateTime(2026, 10, 14, 12, 0, 0);

  int ms(DateTime value) => value.millisecondsSinceEpoch;

  group('evaluateCredentialFreshness', () {
    test('a login from moments ago is fresh', () {
      expect(
        evaluateCredentialFreshness(
          lastSuccessfulLoginAtMs:
              ms(now.subtract(const Duration(minutes: 5))),
          now: now,
          validity: window,
        ),
        CredentialFreshness.fresh,
      );
    });

    test('one millisecond inside the window is still fresh', () {
      expect(
        evaluateCredentialFreshness(
          lastSuccessfulLoginAtMs: ms(now.subtract(window)) + 1,
          now: now,
          validity: window,
        ),
        CredentialFreshness.fresh,
      );
    });

    test('EXACTLY 10 days old is expired (boundary is inclusive)', () {
      expect(
        evaluateCredentialFreshness(
          lastSuccessfulLoginAtMs: ms(now.subtract(window)),
          now: now,
          validity: window,
        ),
        CredentialFreshness.expired,
      );
    });

    test('one millisecond past 10 days is expired', () {
      expect(
        evaluateCredentialFreshness(
          lastSuccessfulLoginAtMs: ms(now.subtract(window)) - 1,
          now: now,
          validity: window,
        ),
        CredentialFreshness.expired,
      );
    });

    test('a device clock BEHIND the record is refused, not treated as fresh',
        () {
      // now < last: a negative interval must never extend the credential.
      expect(
        evaluateCredentialFreshness(
          lastSuccessfulLoginAtMs: ms(now.add(const Duration(days: 5))),
          now: now,
          validity: window,
        ),
        CredentialFreshness.clockSkew,
      );
    });

    test('a record in the future by one millisecond is also a clock skew', () {
      expect(
        evaluateCredentialFreshness(
          lastSuccessfulLoginAtMs: ms(now) + 1,
          now: now,
          validity: window,
        ),
        CredentialFreshness.clockSkew,
      );
    });

    test('no recorded success can never be fresh', () {
      expect(
        evaluateCredentialFreshness(
          lastSuccessfulLoginAtMs: null,
          now: now,
          validity: window,
        ),
        CredentialFreshness.missing,
      );
    });
  });

  group('scope identity', () {
    test('the secret slot is unique per server, database and user', () {
      LoginScope scope({String url = 'http://h:8069', String db = 'x', String user = 'u'}) =>
          LoginScope.fromInput(baseUrl: url, database: db, login: user);

      final base = scope();
      expect(scope(url: 'http://other:8069').secretKey, isNot(base.secretKey));
      expect(scope(db: 'other').secretKey, isNot(base.secretKey));
      expect(scope(user: 'other').secretKey, isNot(base.secretKey));
      expect(scope().secretKey, base.secretKey);
    });

    test('trailing slashes and padding do not create a second account', () {
      expect(
        LoginScope.fromInput(
          baseUrl: '  http://h:8069/  ',
          database: ' x ',
          login: ' u ',
        ),
        LoginScope.fromInput(baseUrl: 'http://h:8069', database: 'x', login: 'u'),
      );
    });

    test('the key is filesystem safe (the Windows backend names a file after it)',
        () {
      final key = LoginScope.fromInput(
        baseUrl: 'http://192.168.31.105:8069',
        database: 'LcHardwareHouse',
        login: 'lab/operator@example.com',
      ).secretKey;

      expect(key, startsWith('${OdooConfig.secureStorageKeyPrefix}.'));
      expect(RegExp(r'^[A-Za-z0-9._-]+$').hasMatch(key), isTrue);
    });
  });
}
