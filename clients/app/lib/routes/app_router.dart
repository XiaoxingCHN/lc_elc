import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/unified/unified_routes.dart';
import '../features/warehouse/warehouse_routes.dart';
import '../features/warehouse/warehouse_shell.dart';
import '../screens/login_screen.dart';
import '../screens/splash_screen.dart';
import '../providers/auth_provider.dart';
import 'navigator_keys.dart';

export 'navigator_keys.dart' show rootNavigatorKey;
import 'offline_access.dart';

/// Bridges Riverpod auth state into GoRouter's `refreshListenable`.
///
/// Without it the router object would have to be rebuilt (and the navigation
/// stack thrown away) on every auth change; here a single router instance is
/// kept and only the redirect is re-evaluated.
class _AuthRouterRefresh extends ChangeNotifier {
  _AuthRouterRefresh(Ref ref) {
    _subscription = ref.listen<AuthState>(
      authProvider,
      (previous, next) => notifyListeners(),
    );
  }

  late final ProviderSubscription<AuthState> _subscription;

  @override
  void dispose() {
    _subscription.close();
    super.dispose();
  }
}

final appRouterProvider = Provider<GoRouter>((ref) {
  final refresh = _AuthRouterRefresh(ref);

  final router = GoRouter(
    navigatorKey: rootNavigatorKey,
    // Startup lands on the loading screen, never straight on the login form:
    // the remembered account / automatic login must be resolved first.
    initialLocation: '/splash',
    refreshListenable: refresh,
    redirect: (context, state) {
      final auth = ref.read(authProvider);
      final location = state.matchedLocation;

      // Still deciding (reading the remembered account, running the single
      // automatic sign-in attempt): stay on the loading screen.
      if (auth.isInitializing) {
        return location == '/splash' ? null : '/splash';
      }

      if (auth.isAuthenticated) {
        // The signed-in home is 库存速览 (the shell's first section). A session
        // that arrives while the app sits on the login/splash screen goes
        // straight there; the library is one tap away in the same shell.
        return (location == '/login' || location == '/splash')
            ? WarehouseRoutes.overview
            : null;
      }

      // Not signed in (or a failed attempt): the login form, with the
      // remembered server/database/user pre-filled - EXCEPT for the explicit
      // read-only offline entry, which the operator chooses from that form
      // (see OfflineAccess). It never counts as a session: writes stay blocked
      // and no identity/timestamp/secret is produced.
      if (!auth.isAuthenticated &&
          OfflineAccess.allows(location, state.uri.queryParameters)) {
        return null;
      }

      return location == '/login' ? null : '/login';
    },
    routes: <RouteBase>[
      GoRoute(
        path: '/splash',
        builder: (context, state) => const SplashScreen(),
      ),
      GoRoute(
        path: '/login',
        builder: (context, state) => const LoginScreen(),
      ),

      // ---- Four sections, each with its own stack ---------------------------
      // 库存速览 / 仓位速览 / 器件库 / 库存管理. The shell only decides where the
      // switcher sits; every screen keeps its own app bar and back behaviour.
      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) =>
            WarehouseShell(navigationShell: navigationShell),
        branches: warehouseBranches,
      ),

      // ---- Operational pages (full screen, OUTSIDE the shell) ---------------
      // 入库 / 领料 / 归还 / 标签 / 历史 stay top-level so a deep link, a scanner
      // intent and the back button behave exactly as they did before the shell
      // existed. The shell's 库存管理 section is only a launcher for these.
      ...unifiedRoutes,

      // ---- Compatibility redirects -----------------------------------------
      // `/home` and `/products` used to be the old dashboard's paths. They now
      // land on the library, which is still the right answer for them: a link
      // that meant "show me parts" must not become "show me totals".
      GoRoute(
        path: '/home',
        redirect: (context, state) => UnifiedRoutes.catalog,
      ),
      GoRoute(
        path: '/products',
        redirect: (context, state) => UnifiedRoutes.catalog,
      ),
      GoRoute(
        path: '/products/:id',
        redirect: (context, state) => UnifiedRoutes.catalog,
      ),
    ],
  );

  ref.onDispose(() {
    refresh.dispose();
    router.dispose();
  });

  return router;
});
