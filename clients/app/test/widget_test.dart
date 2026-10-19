import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/screens/unified_catalog_screen.dart';
import 'package:lab_inventory_client/main.dart';
import 'package:lab_inventory_client/providers/auth_provider.dart';
import 'package:lab_inventory_client/routes/app_router.dart';
import 'package:lab_inventory_client/screens/login_screen.dart';
import 'package:lab_inventory_client/screens/splash_screen.dart';
import 'package:lab_inventory_client/services/login_memory_store.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'support/login_test_support.dart';

import 'package:lab_inventory_client/updates/update_ui.dart';
import 'package:lab_inventory_client/updates/update_platform.dart';

class _NoUpdates extends UpdatePlatform {
  @override
  int get build => 0;
}

/// App-level startup behaviour.
///
/// This file replaces the stock Flutter "counter" template test, which could
/// never pass here: MyApp is a Riverpod widget (it needs a ProviderScope) and
/// the counter it looked for does not exist in this application.
///
/// What is asserted instead:
///   * a loading screen is shown while the remembered login is resolved, so the
///     login form never flashes;
///   * a first-ever start lands on the login form;
///   * a fresh remembered login signs in and lands on the UNIFIED library
///     (`/catalog`), which renders real contract-shaped data from the fake API;
///   * the legacy dashboard (`/home`) and the old inventory-only list
///     (`/products`) redirect there, so no second library exists.
void main() {
  final now = DateTime(2026, 10, 14, 12, 0, 0);

  const url = 'http://192.168.31.105:8069';
  const db = 'LcHardwareHouse';
  const user = 'lab_operator';
  const password = 'pw-A-secret';

  /// One captured catalog row, in the exact shape of
  /// `lc_elc/docs/business_api_contract.json` -> /lab/api/catalog/search.
  final catalogRow = <String, dynamic>{
    'item_key': 'lcsc:C25804',
    'catalog_code': 'C25804',
    'lab_template_ids': <dynamic>[42],
    'sn_codes': <dynamic>['LAB-000123'],
    'name': '10k 0603 resistor',
    'mpn': 'RC0603FR-0710KL',
    'brand': 'YAGEO',
    'package': '0603',
    'category_id': 3,
    'category_name': 'Resistors',
    'image_url': null,
    'lab_quantity': 120,
    'lab_available_quantity': 100,
    'has_stock': true,
    'catalog_stock': 5200,
    'parameters': <dynamic>[],
    'revision': 'rev-1',
  };

  late InMemorySecretBackend backend;
  late FakeAuthGateway gateway;

  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    backend = InMemorySecretBackend();
    gateway = FakeAuthGateway();
  });

  /// Pumps frames until [finder] matches, or gives up. The splash screen shows
  /// an endless progress animation, so `pumpAndSettle` can never be used.
  Future<void> pumpUntil(
    WidgetTester tester,
    Finder finder, {
    int maxFrames = 60,
  }) async {
    for (var frame = 0; frame < maxFrames; frame++) {
      if (finder.evaluate().isNotEmpty) return;
      await tester.pump(const Duration(milliseconds: 25));
    }
  }

  /// Runs the route transition to completion. Needed before asserting that the
  /// previous screen is GONE: `pumpUntil` returns as soon as the new screen
  /// appears, while the old one is still fading out.
  Future<void> settleRoute(WidgetTester tester) async {
    for (var frame = 0; frame < 14; frame++) {
      await tester.pump(const Duration(milliseconds: 50));
    }
  }

  /// The catalog screen is a desktop-sized layout; the default 800x600 test
  /// surface overflows it. Test it at a window size it is designed for.
  void useDesktopSurface(WidgetTester tester) {
    tester.view.physicalSize = const Size(1400, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
  }

  testWidgets(
    'startup shows a loading state and never flashes the login form',
    (tester) async {
      // A store whose preferences never load yet: the app is stuck in startup.
      final pendingPreferences = Completer<SharedPreferences>();
      final container = ProviderContainer(
        overrides: [
          updatePlatformProvider.overrideWithValue(_NoUpdates()),
          secretBackendProvider.overrideWithValue(backend),
          authGatewayProvider.overrideWithValue(gateway),
          clockProvider.overrideWithValue(() => now),
          loginMemoryStoreProvider.overrideWith(
            (ref) => LoginMemoryStore(
              backend: backend,
              clock: () => now,
              preferencesLoader: () => pendingPreferences.future,
            ),
          ),
        ],
      );
      addTearDown(container.dispose);

      await tester.pumpWidget(
        UncontrolledProviderScope(container: container, child: const MyApp()),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(find.byType(SplashScreen), findsOneWidget);
      expect(find.byType(CircularProgressIndicator), findsWidgets);
      // The login form must not be reachable while startup is unresolved.
      expect(find.byType(LoginScreen), findsNothing);
      expect(find.text('密码 *'), findsNothing);
      expect(find.text('登录'), findsNothing);

      // Let startup finish: the login form appears, the splash goes away.
      SharedPreferences.setMockInitialValues(<String, Object>{});
      pendingPreferences.complete(await SharedPreferences.getInstance());

      await pumpUntil(tester, find.byType(LoginScreen));
      await settleRoute(tester);

      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.byType(SplashScreen), findsNothing);
      expect(find.text('密码 *'), findsOneWidget);
    },
  );

  testWidgets('a first-ever start lands on the login form', (tester) async {
    final container = buildAuthContainer(
      backend: backend,
      gateway: gateway,
      now: now,
      apiClient: FakeOdooApiClient(items: <Map<String, dynamic>>[catalogRow]),
    );
    addTearDown(container.dispose);

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const MyApp()),
    );

    await pumpUntil(tester, find.byType(LoginScreen));
    await settleRoute(tester);

    expect(find.byType(LoginScreen), findsOneWidget);
    expect(find.text('记住登录'), findsOneWidget);
    expect(gateway.calls, isEmpty);
  });

  testWidgets(
    'a fresh remembered login opens the unified library with real data',
    (tester) async {
      useDesktopSurface(tester);
      final api = FakeOdooApiClient(items: <Map<String, dynamic>>[catalogRow]);
      final container = buildAuthContainer(
        backend: backend,
        gateway: gateway,
        now: now,
        apiClient: api,
      );
      addTearDown(container.dispose);

      final scope = LoginScope.fromInput(
        baseUrl: url,
        database: db,
        login: user,
      );
      await seedRememberedLogin(
        store: container.read(loginMemoryStoreProvider),
        lastSuccessfulLoginAt: now.subtract(const Duration(days: 1)),
        password: password,
      );

      await tester.pumpWidget(
        UncontrolledProviderScope(container: container, child: const MyApp()),
      );

      await pumpUntil(tester, find.byType(UnifiedCatalogScreen));
      await settleRoute(tester);

      // The signed-in home is the one unified library ...
      expect(find.byType(UnifiedCatalogScreen), findsOneWidget);
      expect(find.text('仓库'), findsOneWidget);
      // ... it really queried the contract endpoint ...
      expect(api.requestedPaths, contains('/lab/api/catalog/search'));
      // ... and it rendered the captured row (lab stock and mall stock separate).
      expect(find.text('10k 0603 resistor'), findsWidgets);
      // The automatic sign-in happened exactly once, reusing the stored secret.
      expect(gateway.calls, hasLength(1));
      expect(gateway.calls.single.password, password);
      expect(await backend.read(scope.secretKey), password);
      // The old dashboard is not part of the signed-in experience.
      expect(find.text('P0 原型 - 功能菜单'), findsNothing);
    },
  );

  testWidgets('legacy /home and /products redirect to the unified library', (
    tester,
  ) async {
    useDesktopSurface(tester);
    final container = buildAuthContainer(
      backend: backend,
      gateway: gateway,
      now: now,
      apiClient: FakeOdooApiClient(items: <Map<String, dynamic>>[catalogRow]),
    );
    addTearDown(container.dispose);

    await seedRememberedLogin(
      store: container.read(loginMemoryStoreProvider),
      lastSuccessfulLoginAt: now.subtract(const Duration(days: 1)),
      password: password,
    );

    await tester.pumpWidget(
      UncontrolledProviderScope(container: container, child: const MyApp()),
    );
    await pumpUntil(tester, find.byType(UnifiedCatalogScreen));
    await settleRoute(tester);

    final router = container.read(appRouterProvider);

    for (final legacy in <String>['/home', '/products', '/products/42']) {
      router.go(legacy);
      await settleRoute(tester);

      final location = router.routerDelegate.currentConfiguration.uri.path;
      expect(
        location,
        '/catalog',
        reason: '$legacy must not open a second library',
      );
      expect(find.byType(UnifiedCatalogScreen), findsOneWidget);
      expect(find.text('仓库'), findsOneWidget);
    }
  });

  testWidgets(
    'an expired remembered login lands on the login form with a notice',
    (tester) async {
      final container = buildAuthContainer(
        backend: backend,
        gateway: gateway,
        now: now,
        apiClient: FakeOdooApiClient(items: <Map<String, dynamic>>[catalogRow]),
      );
      addTearDown(container.dispose);

      await seedRememberedLogin(
        store: container.read(loginMemoryStoreProvider),
        lastSuccessfulLoginAt: now.subtract(const Duration(days: 10)),
        password: password,
      );

      await tester.pumpWidget(
        UncontrolledProviderScope(container: container, child: const MyApp()),
      );

      await pumpUntil(tester, find.byType(LoginScreen));
      await settleRoute(tester);

      expect(find.byType(LoginScreen), findsOneWidget);
      expect(find.textContaining('10 天'), findsWidgets);
      expect(gateway.calls, isEmpty);
    },
  );
}
