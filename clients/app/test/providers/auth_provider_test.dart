import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/models/odoo_exception.dart';
import 'package:lab_inventory_client/providers/auth_provider.dart';
import 'package:lab_inventory_client/services/login_memory_store.dart';
import 'package:lab_inventory_client/services/secret_backend.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/login_test_support.dart';

/// Behaviour of the whole "记住登录" contract, driven through the real
/// [AuthStateNotifier] with a frozen clock and an offline gateway.
///
/// No test here contacts any server, and no real credential appears anywhere.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final now = DateTime(2026, 10, 14, 12, 0, 0);
  const tenDays = Duration(days: 10);

  const urlA = 'http://192.168.31.105:8069';
  const dbA = 'LcHardwareHouse';
  const userA = 'lab_operator';
  const passwordA = 'pw-A-secret';

  const urlB = 'http://192.168.31.200:8069';
  const dbB = 'OtherDb';
  const userB = 'someone';
  const passwordB = 'pw-B-secret';

  late InMemorySecretBackend backend;
  late FakeAuthGateway gateway;
  late ProviderContainer container;
  final extraContainers = <ProviderContainer>[];

  LoginScope scopeA() =>
      LoginScope.fromInput(baseUrl: urlA, database: dbA, login: userA);
  LoginScope scopeB() =>
      LoginScope.fromInput(baseUrl: urlB, database: dbB, login: userB);

  /// A fresh container = a fresh app process, sharing "disk" (prefs + key
  /// store) with any other container built in the same test.
  ProviderContainer newContainer({
    SecretBackend? withBackend,
    FakeAuthGateway? withGateway,
  }) {
    final created = buildAuthContainer(
      backend: withBackend ?? backend,
      gateway: withGateway ?? gateway,
      now: now,
    );
    extraContainers.add(created);
    return created;
  }

  AuthStateNotifier notifierOf(ProviderContainer target) =>
      target.read(authProvider.notifier);

  LoginMemoryStore storeOf(ProviderContainer target) =>
      target.read(loginMemoryStoreProvider);

  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    backend = InMemorySecretBackend();
    gateway = FakeAuthGateway();
    container = buildAuthContainer(
      backend: backend,
      gateway: gateway,
      now: now,
    );
  });

  tearDown(() {
    container.dispose();
    for (final extra in extraContainers) {
      extra.dispose();
    }
    extraContainers.clear();
  });

  // ---------------------------------------------------------------------------
  group('manual login', () {
    test('a successful login remembers the account and stores the password',
        () async {
      final notifier = notifierOf(container);

      final ok = await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );

      expect(ok, isTrue);
      final state = container.read(authProvider);
      expect(state.isAuthenticated, isTrue);
      expect(state.uid, gateway.successUid);

      final store = storeOf(container);
      expect(backend.writes, hasLength(1));
      expect(await store.readPassword(scopeA()), passwordA);

      final account = store.accountFor(scopeA())!;
      expect(account.baseUrl, urlA);
      expect(account.database, dbA);
      expect(account.login, userA);
      expect(account.rememberLogin, isTrue);
      expect(account.lastSuccessfulLoginAt, now.millisecondsSinceEpoch);

      // The password lives in the key store, the account in plain prefs.
      final raw = await rawPreferenceDocument();
      expect(raw, contains(urlA));
      expect(raw, contains(userA));
      expect(raw, isNot(contains(passwordA)));
    });

    test('with 记住登录 off the account is remembered but no password is',
        () async {
      final ok = await notifierOf(container).login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: false,
      );

      expect(ok, isTrue);
      expect(backend.values, isEmpty);
      expect(backend.writes, isEmpty);

      final store = storeOf(container);
      final account = store.accountFor(scopeA())!;
      expect(account.rememberLogin, isFalse);
      expect(account.lastSuccessfulLoginAt, now.millisecondsSinceEpoch);
      expect(await store.readPassword(scopeA()), isNull);
    });

    test('the password reaches the key store only after the server accepted it',
        () async {
      final notifier = notifierOf(container);

      gateway.failure = OdooAuthException('Invalid credentials');
      final rejected = await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );

      expect(rejected, isFalse);
      expect(backend.writes, isEmpty, reason: 'nothing may be written on failure');
      expect(await storeOf(container).readPassword(scopeA()), isNull);

      gateway.failure = null;
      final accepted = await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );

      expect(accepted, isTrue);
      expect(backend.writes, hasLength(1));
    });

    test('a rejected login keeps the old secret and does not renew the stamp',
        () async {
      final store = storeOf(container);
      final earlier = now.subtract(const Duration(days: 2));
      await seedRememberedLogin(
        store: store,
        password: passwordA,
        lastSuccessfulLoginAt: earlier,
      );
      final writesBefore = backend.writes.length;

      gateway.failure = OdooAuthException('Invalid credentials');
      final ok = await notifierOf(container).login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: 'a-wrong-password',
        rememberLogin: true,
      );

      expect(ok, isFalse);
      expect(gateway.calls, hasLength(1));
      expect(backend.writes.length, writesBefore);
      expect(await store.readPassword(scopeA()), passwordA);
      expect(
        store.accountFor(scopeA())!.lastSuccessfulLoginAt,
        earlier.millisecondsSinceEpoch,
        reason: 'a failure must never refresh the 10-day window',
      );

      final state = container.read(authProvider);
      expect(state.hasError, isTrue);
      expect(state.errorMessage, contains('登录失败'));
    });

    test('a rejected login is retryable with corrected input', () async {
      final notifier = notifierOf(container);
      gateway.failure = OdooAuthException('Invalid credentials');

      await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: 'wrong',
        rememberLogin: false,
      );
      gateway.failure = null;

      final ok = await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: false,
      );

      expect(ok, isTrue);
      expect(container.read(authProvider).errorMessage, isNull);
    });
  });

  // ---------------------------------------------------------------------------
  group('automatic sign-in and the 10-day window', () {
    test('signs in exactly once inside the window and refreshes the record',
        () async {
      final store = storeOf(container);
      await seedRememberedLogin(
        store: store,
        password: passwordA,
        lastSuccessfulLoginAt: now.subtract(const Duration(days: 9)),
      );

      final notifier = notifierOf(container);
      await notifier.bootstrap();

      expect(gateway.calls, hasLength(1));
      expect(gateway.calls.single.password, passwordA);
      expect(gateway.calls.single.baseUrl, urlA);
      expect(gateway.calls.single.database, dbA);

      final state = container.read(authProvider);
      expect(state.isAuthenticated, isTrue);
      expect(state.uid, gateway.successUid);
      expect(
        store.accountFor(scopeA())!.lastSuccessfulLoginAt,
        now.millisecondsSinceEpoch,
        reason: 'an automatic success is a success: it refreshes the window',
      );

      // A second splash build must not fire a second attempt.
      await notifier.bootstrap();
      expect(gateway.calls, hasLength(1));
      expect(notifier.autoLoginAttempted, isTrue);
    });

    test('one millisecond inside the window still signs in automatically',
        () async {
      await seedRememberedLogin(
        store: storeOf(container),
        password: passwordA,
        lastSuccessfulLoginAt:
            now.subtract(tenDays).add(const Duration(milliseconds: 1)),
      );

      await notifierOf(container).bootstrap();

      expect(gateway.calls, hasLength(1));
      expect(container.read(authProvider).isAuthenticated, isTrue);
    });

    test('EXACTLY 10 days asks for the password and erases the secret',
        () async {
      final store = storeOf(container);
      await seedRememberedLogin(
        store: store,
        password: passwordA,
        lastSuccessfulLoginAt: now.subtract(tenDays),
      );

      await notifierOf(container).bootstrap();

      expect(gateway.calls, isEmpty, reason: 'nothing may be sent');
      expect(backend.contains(scopeA().secretKey), isFalse);
      expect(backend.deletes, contains(scopeA().secretKey));
      expect(gateway.resetSessionCount, greaterThanOrEqualTo(1));

      final account = store.accountFor(scopeA())!;
      expect(account.baseUrl, urlA);
      expect(account.database, dbA);
      expect(account.login, userA);
      expect(account.rememberLogin, isTrue);

      final state = container.read(authProvider);
      expect(state.isAuthenticated, isFalse);
      expect(state.manualLoginReason, ManualLoginReason.expired);
      expect(state.noticeMessage, contains('10 天'));
      expect(state.savedAccount?.login, userA);
    });

    test('one millisecond past the window asks for the password', () async {
      final store = storeOf(container);
      await seedRememberedLogin(
        store: store,
        password: passwordA,
        lastSuccessfulLoginAt:
            now.subtract(tenDays).subtract(const Duration(milliseconds: 1)),
      );

      await notifierOf(container).bootstrap();

      expect(gateway.calls, isEmpty);
      expect(backend.contains(scopeA().secretKey), isFalse);
      expect(
        container.read(authProvider).manualLoginReason,
        ManualLoginReason.expired,
      );
    });

    test('a device clock behind the record cannot extend the window', () async {
      final store = storeOf(container);
      await seedRememberedLogin(
        store: store,
        password: passwordA,
        lastSuccessfulLoginAt: now.add(const Duration(days: 5)),
      );

      await notifierOf(container).bootstrap();

      expect(gateway.calls, isEmpty);
      expect(backend.contains(scopeA().secretKey), isFalse);
      final state = container.read(authProvider);
      expect(state.manualLoginReason, ManualLoginReason.clockSkew);
      expect(state.noticeMessage, contains('本机时间'));
      expect(state.savedAccount?.login, userA);
    });

    test('a failed automatic attempt does not renew the stamp and is not retried',
        () async {
      final store = storeOf(container);
      final earlier = now.subtract(const Duration(days: 2));
      await seedRememberedLogin(
        store: store,
        password: passwordA,
        lastSuccessfulLoginAt: earlier,
      );

      gateway.failure = OdooAuthException('Invalid credentials');
      final notifier = notifierOf(container);
      await notifier.bootstrap();

      expect(gateway.calls, hasLength(1), reason: 'exactly one attempt');
      expect(
        store.accountFor(scopeA())!.lastSuccessfulLoginAt,
        earlier.millisecondsSinceEpoch,
      );

      final state = container.read(authProvider);
      expect(state.isAuthenticated, isFalse);
      expect(state.hasError, isTrue);
      expect(state.errorMessage, contains('自动登录失败'));
      expect(state.savedAccount?.login, userA);

      // No retry loop.
      await notifier.bootstrap();
      expect(gateway.calls, hasLength(1));
    });

    test('a network failure keeps the secret and offers it for a manual retry',
        () async {
      await seedRememberedLogin(
        store: storeOf(container),
        password: passwordA,
        lastSuccessfulLoginAt: now.subtract(const Duration(days: 1)),
      );

      gateway.failure = OdooNetworkException('Connection timeout.');
      final notifier = notifierOf(container);
      await notifier.bootstrap();

      expect(gateway.calls, hasLength(1));
      expect(backend.contains(scopeA().secretKey), isTrue);

      final state = container.read(authProvider);
      expect(state.errorMessage, contains('无法连接'));

      expect(
        await notifier.revealRememberedPassword(
          baseUrl: urlA,
          database: dbA,
          login: userA,
        ),
        passwordA,
        reason: 'a transport failure is not a reason to forget the password',
      );
    });

    test('automatic sign-in is off when the operator did not choose it',
        () async {
      await seedRememberedLogin(
        store: storeOf(container),
        password: passwordA,
        lastSuccessfulLoginAt: now.subtract(const Duration(days: 1)),
        rememberLogin: false,
      );

      await notifierOf(container).bootstrap();

      expect(gateway.calls, isEmpty);
      final state = container.read(authProvider);
      expect(state.manualLoginReason, ManualLoginReason.noStoredPassword);
      expect(state.savedAccount?.login, userA);
    });

    test('nothing is restored on a first-ever start', () async {
      await notifierOf(container).bootstrap();

      final state = container.read(authProvider);
      expect(state.status, AuthStatus.unauthenticated);
      expect(state.savedAccount, isNull);
      expect(state.noticeMessage, isNull);
      expect(gateway.calls, isEmpty);
    });
  });

  // ---------------------------------------------------------------------------
  group('explicit sign-out', () {
    test('erases the password, blocks automatic sign-in and keeps the account',
        () async {
      final notifier = notifierOf(container);
      await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );
      expect(backend.contains(scopeA().secretKey), isTrue);

      await notifier.logout();

      expect(gateway.logoutCount, 1);
      expect(backend.contains(scopeA().secretKey), isFalse);
      expect(gateway.isAuthenticated, isFalse);

      final store = storeOf(container);
      final account = store.accountFor(scopeA())!;
      expect(account.autoLoginBlocked, isTrue);
      expect(account.rememberLogin, isTrue, reason: 'preference is kept');
      expect(account.login, userA);

      final state = container.read(authProvider);
      expect(state.isAuthenticated, isFalse);
      expect(state.savedAccount?.login, userA);
      expect(state.manualLoginReason, ManualLoginReason.signedOut);
    });

    test('the block survives a restart and stops the next automatic attempt',
        () async {
      final notifier = notifierOf(container);
      await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );
      await notifier.logout();

      final restarted = newContainer();
      await notifierOf(restarted).bootstrap();

      expect(gateway.calls, hasLength(1), reason: 'only the manual login ran');
      final state = restarted.read(authProvider);
      expect(state.isAuthenticated, isFalse);
      expect(state.manualLoginReason, ManualLoginReason.signedOut);
      expect(state.savedAccount?.login, userA);

      // A successful manual login unblocks the next start.
      final ok = await notifierOf(restarted).login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );
      expect(ok, isTrue);
      expect(
        storeOf(restarted).accountFor(scopeA())!.autoLoginBlocked,
        isFalse,
      );
    });
  });

  // ---------------------------------------------------------------------------
  group('switching server / database', () {
    test('a saved password is never sent to a different server', () async {
      final notifier = notifierOf(container);
      await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );

      final ok = await notifier.login(
        baseUrl: urlB,
        database: dbB,
        login: userB,
        password: passwordB,
        rememberLogin: true,
      );

      expect(ok, isTrue);
      expect(gateway.submittedPasswords, [passwordA, passwordB]);
      expect(gateway.calls[1].password, isNot(passwordA));
      expect(gateway.calls[1].password, passwordB);

      final store = storeOf(container);
      expect(await store.readPassword(scopeB()), passwordB);
      expect(await store.readPassword(scopeA()), passwordA);
    });

    test('a never-used server has no password to restore', () async {
      final notifier = notifierOf(container);
      await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );

      expect(
        await notifier.revealRememberedPassword(
          baseUrl: 'http://10.9.9.9:8069',
          database: 'SomeDb',
          login: userA,
        ),
        isNull,
      );
      expect(
        storeOf(container).accountFor(
          LoginScope.fromInput(
            baseUrl: 'http://10.9.9.9:8069',
            database: 'SomeDb',
            login: userA,
          ),
        ),
        isNull,
      );
    });

    test('a database change is a different account too', () async {
      final notifier = notifierOf(container);
      await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );

      expect(
        await notifier.revealRememberedPassword(
          baseUrl: urlA,
          database: 'AnotherDb',
          login: userA,
        ),
        isNull,
      );
      expect(gateway.submittedPasswords, [passwordA]);
    });
  });

  // ---------------------------------------------------------------------------
  group('turning the memory off', () {
    test('switching 记住登录 off deletes the secret immediately', () async {
      final notifier = notifierOf(container);
      await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );
      expect(backend.contains(scopeA().secretKey), isTrue);

      await notifier.setRememberLoginPreference(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        value: false,
      );

      expect(backend.contains(scopeA().secretKey), isFalse);
      expect(storeOf(container).accountFor(scopeA())!.rememberLogin, isFalse);
      expect(container.read(authProvider).rememberLogin, isFalse);
    });

    test('clearing the saved password keeps the account', () async {
      final notifier = notifierOf(container);
      await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );

      await notifier.forgetSavedPassword(
        baseUrl: urlA,
        database: dbA,
        login: userA,
      );

      expect(backend.contains(scopeA().secretKey), isFalse);
      final account = storeOf(container).accountFor(scopeA());
      expect(account, isNotNull);
      expect(account!.baseUrl, urlA);
      expect(account.rememberLogin, isFalse);
    });

    test('clearing everything removes accounts and secrets', () async {
      final notifier = notifierOf(container);
      await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );

      await notifier.forgetAllRememberedLogins();

      expect(storeOf(container).accounts, isEmpty);
      expect(backend.values, isEmpty);
      expect(await rawPreferenceDocument(), isEmpty);
      expect(container.read(authProvider).savedAccount, isNull);
    });
  });

  // ---------------------------------------------------------------------------
  group('session expiry during business use', () {
    test('a 401 hands control back to the login screen without an auto retry',
        () async {
      final notifier = notifierOf(container);
      await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );
      final callsAfterLogin = gateway.calls.length;
      expect(backend.contains(scopeA().secretKey), isTrue);

      // What OdooClient does when a business call is answered with 401.
      gateway.fireSessionInvalid();

      expect(gateway.calls.length, callsAfterLogin,
          reason: 'a dead session must not trigger another sign-in attempt');
      expect(gateway.isAuthenticated, isFalse);

      final state = container.read(authProvider);
      expect(state.isAuthenticated, isFalse);
      expect(state.manualLoginReason, ManualLoginReason.sessionExpired);
      expect(state.noticeMessage, contains('登录状态已失效'));
      expect(state.savedAccount?.login, userA);

      // The credential survives: an expired session is not a rejected password.
      expect(await storeOf(container).readPassword(scopeA()), passwordA);

      // Parallel requests hitting the same dead session must not churn state.
      gateway.fireSessionInvalid();
      expect(
        container.read(authProvider).manualLoginReason,
        ManualLoginReason.sessionExpired,
      );
      expect(gateway.calls.length, callsAfterLogin);
    });

    test('the operator can simply sign in again after the session expired',
        () async {
      final notifier = notifierOf(container);
      await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );

      gateway.fireSessionInvalid();
      expect(container.read(authProvider).isAuthenticated, isFalse);

      final ok = await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );

      expect(ok, isTrue);
      expect(container.read(authProvider).isAuthenticated, isTrue);
    });
  });

  // ---------------------------------------------------------------------------
  group('unreadable preference store', () {
    test('still allows a manual login and shows no technical detail', () async {
      // Reproduces the real Windows failure: the per-user preferences directory
      // could not be created, so reading the remembered account throws.
      final broken = ProviderContainer(
        overrides: [
          secretBackendProvider.overrideWithValue(backend),
          authGatewayProvider.overrideWithValue(gateway),
          clockProvider.overrideWithValue(() => now),
          loginMemoryStoreProvider.overrideWith(
            (ref) => LoginMemoryStore(
              backend: backend,
              clock: () => now,
              preferencesLoader: () =>
                  Future<SharedPreferences>.error(StateError('prefs denied')),
            ),
          ),
        ],
      );
      extraContainers.add(broken);
      final notifier = notifierOf(broken);

      await notifier.bootstrap();

      final state = broken.read(authProvider);
      expect(state.status, AuthStatus.unauthenticated);
      expect(state.isAuthenticated, isFalse);
      expect(state.canRememberPassword, isFalse);
      expect(state.noticeMessage, isNotNull);
      // The operator gets one plain sentence - no paths, no errno, no exception.
      expect(state.noticeMessage, isNot(contains('Exception')));
      expect(state.noticeMessage, isNot(contains('StateError')));
      expect(state.noticeMessage, isNot(contains('prefs denied')));

      // Signing in for this session must still work.
      final ok = await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );
      expect(ok, isTrue);
      expect(broken.read(authProvider).isAuthenticated, isTrue);
    });
  });

  // ---------------------------------------------------------------------------
  group('no usable key store (headless Linux, no libsecret keyring)', () {
    test('a normal login still works and nothing secret is written anywhere',
        () async {
      final broken = newContainer(withBackend: const UnavailableSecretBackend());
      final notifier = notifierOf(broken);

      final ok = await notifier.login(
        baseUrl: urlA,
        database: dbA,
        login: userA,
        password: passwordA,
        rememberLogin: true,
      );

      expect(ok, isTrue, reason: 'a missing keyring must not block login');
      final state = broken.read(authProvider);
      expect(state.isAuthenticated, isTrue);
      expect(state.secureStorageStatus, SecureStorageStatus.unavailable);
      expect(state.canRememberPassword, isFalse);
      expect(state.noticeMessage, contains('密码未保存'));

      // The account is still remembered; the password is nowhere.
      expect(storeOf(broken).accountFor(scopeA()), isNotNull);
      expect(await rawPreferenceDocument(), isNot(contains(passwordA)));
    });

    test('automatic sign-in cannot run without a key store', () async {
      await seedRememberedLogin(
        store: storeOf(container),
        password: passwordA,
        lastSuccessfulLoginAt: now.subtract(const Duration(days: 1)),
      );

      final broken = newContainer(withBackend: const UnavailableSecretBackend());
      await notifierOf(broken).bootstrap();

      expect(gateway.calls, isEmpty);
      final state = broken.read(authProvider);
      expect(state.isAuthenticated, isFalse);
      expect(state.manualLoginReason, ManualLoginReason.storageUnavailable);
      expect(state.noticeMessage, contains('无法保存密码'));
      expect(state.savedAccount?.login, userA);
    });
  });
}
