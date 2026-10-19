import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/providers/auth_provider.dart';
import 'package:lab_inventory_client/screens/login_screen.dart';
import 'package:lab_inventory_client/services/login_memory_store.dart';
import 'package:lab_inventory_client/services/secret_backend.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../support/login_test_support.dart';

/// Operator-facing contract of the login form:
///   * exactly ONE switch, and it is "记住登录" - no pile of technical toggles;
///   * the remembered account is pre-filled;
///   * a password is pre-filled only while it is allowed, and it is dropped the
///     moment the server/database/user changes;
///   * a machine without a key store says so and still allows a normal login.
void main() {
  final now = DateTime(2026, 10, 14, 12, 0, 0);

  const url = 'http://192.168.31.105:8069';
  const db = 'LcHardwareHouse';
  const user = 'lab_operator';
  const password = 'pw-A-secret';

  late InMemorySecretBackend backend;
  late FakeAuthGateway gateway;

  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    backend = InMemorySecretBackend();
    gateway = FakeAuthGateway();
  });

  Future<void> pumpUntil(WidgetTester tester, Finder finder,
      {int maxFrames = 40}) async {
    for (var frame = 0; frame < maxFrames; frame++) {
      if (finder.evaluate().isNotEmpty) return;
      await tester.pump(const Duration(milliseconds: 25));
    }
  }

  Future<ProviderContainer> pumpLogin(
    WidgetTester tester, {
    SecretBackend? withBackend,
  }) async {
    final container = buildAuthContainer(
      backend: withBackend ?? backend,
      gateway: gateway,
      now: now,
    );
    addTearDown(container.dispose);

    // Startup runs first in the real app (splash screen); here it is driven
    // directly so the screen is in the state the operator would actually see.
    await container.read(authProvider.notifier).bootstrap();

    await tester.pumpWidget(
      UncontrolledProviderScope(
        container: container,
        child: const MaterialApp(home: LoginScreen()),
      ),
    );
    await tester.pump();

    return container;
  }

  String fieldText(WidgetTester tester, int index) =>
      tester.widget<TextField>(find.byType(TextField).at(index)).controller!.text;

  testWidgets('exactly one switch, and it is 记住登录', (tester) async {
    await pumpLogin(tester);

    expect(find.byType(SwitchListTile), findsOneWidget);
    expect(find.byType(Switch), findsOneWidget);
    expect(find.text('记住登录'), findsOneWidget);

    // The three technical switches of the original design must not be here.
    expect(find.text('记住账号'), findsNothing);
    expect(find.text('记住密码'), findsNothing);
    expect(find.text('自动登录'), findsNothing);
  });

  testWidgets('the remembered account is pre-filled after a restart',
      (tester) async {
    await seedRememberedLogin(
      store: LoginMemoryStore(backend: backend, clock: () => now),
      lastSuccessfulLoginAt: now.subtract(const Duration(days: 1)),
      password: password,
    );

    await pumpLogin(tester);

    expect(fieldText(tester, 0), url);
    expect(fieldText(tester, 1), db);
    expect(fieldText(tester, 2), user);
  });

  testWidgets('a fresh remembered password is pre-filled', (tester) async {
    await seedRememberedLogin(
      store: LoginMemoryStore(backend: backend, clock: () => now),
      lastSuccessfulLoginAt: now.subtract(const Duration(days: 1)),
      password: password,
    );

    await pumpLogin(tester);
    await pumpUntil(
      tester,
      find.byWidgetPredicate(
        (widget) => widget is TextField && widget.controller?.text == password,
      ),
    );

    expect(fieldText(tester, 3), password);
  });

  testWidgets('changing the server drops the pre-filled password',
      (tester) async {
    await seedRememberedLogin(
      store: LoginMemoryStore(backend: backend, clock: () => now),
      lastSuccessfulLoginAt: now.subtract(const Duration(days: 1)),
      password: password,
    );

    await pumpLogin(tester);
    await pumpUntil(
      tester,
      find.byWidgetPredicate(
        (widget) => widget is TextField && widget.controller?.text == password,
      ),
    );
    expect(fieldText(tester, 3), password);

    // The operator now points the client at another server. The password that
    // belonged to the old account must not travel with it.
    await tester.enterText(find.byType(TextField).at(0), 'http://10.9.9.9:8069');
    await tester.pump();

    expect(fieldText(tester, 3), isEmpty);
    expect(find.textContaining('请重新输入'), findsOneWidget);

    // And it stays empty: nothing re-injects the old account's password.
    await tester.pump(const Duration(milliseconds: 100));
    expect(fieldText(tester, 3), isEmpty);
  });

  testWidgets('an expired credential is not pre-filled and says why',
      (tester) async {
    await seedRememberedLogin(
      store: LoginMemoryStore(backend: backend, clock: () => now),
      lastSuccessfulLoginAt: now.subtract(const Duration(days: 10)),
      password: password,
    );

    await pumpLogin(tester);

    expect(fieldText(tester, 0), url);
    expect(fieldText(tester, 2), user);
    expect(fieldText(tester, 3), isEmpty);
    expect(find.textContaining('10 天'), findsWidgets);
    expect(backend.contains(secretKeyFor(url, db, user)), isFalse);
  });

  testWidgets('a machine without a key store says so and disables the switch',
      (tester) async {
    // Seed a real remembered login (a keyring that used to work), then start
    // with a key store that is no longer reachable.
    await seedRememberedLogin(
      store: LoginMemoryStore(backend: backend, clock: () => now),
      lastSuccessfulLoginAt: now.subtract(const Duration(days: 1)),
      password: password,
    );

    await pumpLogin(tester, withBackend: const UnavailableSecretBackend());

    // Told in plain language, in the switch's own caption ...
    expect(find.textContaining('无法安全保存密码'), findsOneWidget);
    // ... and in the banner that explains the skipped automatic sign-in.
    expect(find.textContaining('无法保存密码'), findsOneWidget);

    final switchTile =
        tester.widget<SwitchListTile>(find.byType(SwitchListTile));
    expect(switchTile.onChanged, isNull, reason: 'cannot promise to remember');
    expect(switchTile.value, isFalse);

    // Normal login stays possible: the fields are all there and usable.
    expect(fieldText(tester, 0), url);
    expect(find.text('登录'), findsOneWidget);
  });
}
