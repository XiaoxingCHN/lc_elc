import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/services/login_memory_store.dart';
import 'package:lab_inventory_client/services/secret_backend.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/login_test_support.dart';

/// Storage-level contract of "记住登录".
///
/// The assertions that matter here are the negative ones: a password must never
/// reach `shared_preferences`, and one account must never be able to read
/// another account's secret.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final now = DateTime(2026, 10, 14, 12, 0, 0);

  const urlA = 'http://192.168.31.105:8069';
  const dbA = 'LcHardwareHouse';
  const userA = 'lab_operator';
  const passwordA = 'pw-A-secret';

  late InMemorySecretBackend backend;
  late LoginMemoryStore store;

  LoginScope scopeA() =>
      LoginScope.fromInput(baseUrl: urlA, database: dbA, login: userA);

  LoginMemoryStore newStore({SecretBackend? withBackend}) => LoginMemoryStore(
        backend: withBackend ?? backend,
        clock: () => now,
      );

  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    backend = InMemorySecretBackend();
    store = newStore();
  });

  test('a remembered account survives a restart and keeps no password', () async {
    await store.rememberAccount(scopeA(), rememberLogin: true, at: now);
    await store.markSuccessfulLogin(scopeA(), at: now);
    await store.savePassword(scopeA(), passwordA);

    // A new process: fresh store, same prefs, same key store.
    final reused = newStore();
    await reused.ensureLoaded();

    final account = reused.lastUsedAccount;
    expect(account, isNotNull);
    expect(account!.baseUrl, urlA);
    expect(account.database, dbA);
    expect(account.login, userA);
    expect(account.rememberLogin, isTrue);
    expect(account.lastSuccessfulLoginAt, now.millisecondsSinceEpoch);

    // The password is in the key store and nowhere else.
    expect(await reused.readPassword(scopeA()), passwordA);
    final raw = await rawPreferenceDocument();
    expect(raw, contains(urlA));
    expect(raw, contains(userA));
    expect(raw, isNot(contains(passwordA)));
  });

  test('one server/database/user can never read another account password',
      () async {
    final scopeB = LoginScope.fromInput(
      baseUrl: 'http://192.168.31.200:8069',
      database: 'OtherDb',
      login: userA,
    );

    await store.savePassword(scopeA(), passwordA);

    expect(scopeA().secretKey, isNot(scopeB.secretKey));
    expect(await store.readPassword(scopeB), isNull);
    expect(await store.readPassword(scopeA()), passwordA);
  });

  test('deleting the password removes exactly one secret', () async {
    final scopeB = LoginScope.fromInput(
      baseUrl: 'http://192.168.31.200:8069',
      database: 'OtherDb',
      login: userA,
    );
    await store.savePassword(scopeA(), passwordA);
    await store.savePassword(scopeB, 'pw-B');

    await store.deletePassword(scopeA());

    expect(await store.readPassword(scopeA()), isNull);
    expect(await store.readPassword(scopeB), 'pw-B');
  });

  test('a key store failure is reported and never falls back to a file',
      () async {
    final broken = newStore(withBackend: const UnavailableSecretBackend());

    await expectLater(
      broken.savePassword(scopeA(), passwordA),
      throwsA(isA<SecretStorageUnavailableException>()),
    );

    expect(broken.storageStatus, SecureStorageStatus.unavailable);
    expect(broken.storageMessage, isNotNull);

    // Nothing secret ended up in the plain preferences document.
    final raw = await rawPreferenceDocument();
    expect(raw, isNot(contains(passwordA)));
    expect(raw, isEmpty);
  });

  test('reading through a broken key store raises instead of guessing',
      () async {
    final broken = newStore(withBackend: const UnavailableSecretBackend());
    await expectLater(
      broken.readPassword(scopeA()),
      throwsA(isA<SecretStorageUnavailableException>()),
    );
    expect(broken.storageStatus, SecureStorageStatus.unavailable);
  });

  test('sign-out blocking and the remember choice are per account', () async {
    await store.rememberAccount(scopeA(), rememberLogin: true, at: now);
    await store.markSuccessfulLogin(scopeA(), at: now);

    await store.setAutoLoginBlocked(scopeA(), true);
    await store.setRememberLogin(scopeA(), false);

    final reloaded = newStore();
    await reloaded.ensureLoaded();
    final account = reloaded.accountFor(scopeA())!;
    expect(account.autoLoginBlocked, isTrue);
    expect(account.rememberLogin, isFalse);

    // A successful login clears the sign-out block.
    await reloaded.markSuccessfulLogin(scopeA(), at: now);
    final after = newStore();
    await after.ensureLoaded();
    expect(after.accountFor(scopeA())!.autoLoginBlocked, isFalse);
  });

  test('forgetAll removes every account and every secret', () async {
    final scopeB = LoginScope.fromInput(
      baseUrl: 'http://192.168.31.200:8069',
      database: 'OtherDb',
      login: 'someone',
    );
    await store.rememberAccount(scopeA(), rememberLogin: true, at: now);
    await store.rememberAccount(scopeB, rememberLogin: true, at: now);
    await store.savePassword(scopeA(), passwordA);
    await store.savePassword(scopeB, 'pw-B');

    await store.forgetAll();

    expect(store.accounts, isEmpty);
    expect(backend.values, isEmpty);
    expect(await rawPreferenceDocument(), isEmpty);
  });

  test('a corrupt preference document cannot break startup', () async {
    SharedPreferences.setMockInitialValues(<String, Object>{
      LoginMemoryStore.prefsKey: '{not json at all',
    });
    final corrupted = newStore();

    await corrupted.ensureLoaded();

    expect(corrupted.accounts, isEmpty);
    expect(corrupted.lastUsedAccount, isNull);
  });

  test('a password is only written when savePassword is called', () async {
    await store.rememberAccount(scopeA(), rememberLogin: true, at: now);
    await store.markSuccessfulLogin(scopeA(), at: now);

    expect(backend.writes, isEmpty);
    expect(await store.readPassword(scopeA()), isNull);

    await store.savePassword(scopeA(), passwordA);
    expect(backend.writes, hasLength(1));
  });
}
