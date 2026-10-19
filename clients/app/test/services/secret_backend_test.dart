import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/services/dio_interceptor.dart';
import 'package:lab_inventory_client/services/secret_backend.dart';

/// Two guarantees that are easy to lose during a refactor:
///   1. the production adapter really writes/reads through
///      flutter_secure_storage (no bespoke file of our own), and
///   2. nothing that reaches a log sink can still contain a credential.
void main() {
  group('FlutterSecureStorageBackend', () {
    test('round-trips through the plugin that owns the OS key store', () async {
      // The plugin's own test hook: an in-memory implementation of the platform
      // interface. It proves the adapter talks to the plugin (and therefore to
      // DPAPI / Android Keystore / libsecret on a real device), not to a file.
      FlutterSecureStorage.setMockInitialValues(<String, String>{});

      const backend = FlutterSecureStorageBackend();
      const key = 'lc_elc.login.v1.deadbeef';

      expect(await backend.read(key), isNull);
      await backend.write(key, 'stored-value');
      expect(await backend.read(key), 'stored-value');
      await backend.delete(key);
      expect(await backend.read(key), isNull);
    });
  });

  group('log redaction', () {
    test('a password in JSON or query form never survives redaction', () {
      expect(redactForLog('{"password":"hunter2"}'), isNot(contains('hunter2')));
      expect(redactForLog('password=hunter2&x=1'), isNot(contains('hunter2')));
      expect(
        redactForLog('{"api_key":"abc123","token":"tok-9"}'),
        isNot(contains('abc123')),
      );
      expect(
        redactForLog('{"api_key":"abc123","token":"tok-9"}'),
        isNot(contains('tok-9')),
      );
    });

    test('an Odoo session id is redacted', () {
      expect(
        redactForLog('Cookie: session_id=abc123def; Path=/'),
        isNot(contains('abc123def')),
      );
    });

    test('header logging exposes names only, never values', () {
      final names = printableHeaderNames(<String, dynamic>{
        'Cookie': 'session_id=abc123def',
        'Authorization': 'Bearer tok-9',
        'Accept': 'application/json',
      });

      expect(names.join(','), contains('cookie=[redacted]'));
      expect(names.join(','), contains('authorization=[redacted]'));
      expect(names.join(','), contains('accept'));
      expect(names.join(','), isNot(contains('abc123def')));
      expect(names.join(','), isNot(contains('tok-9')));
      expect(names.join(','), isNot(contains('session_id')));
    });
  });
}
