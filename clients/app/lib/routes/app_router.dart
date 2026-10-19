import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/unified/unified_routes.dart';
import '../screens/login_screen.dart';
import '../screens/splash_screen.dart';
import '../providers/auth_provider.dart';
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

final rootNavigatorKey = GlobalKey<NavigatorState>();
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
        // The signed-in home is the UNIFIED library. A session that arrives
        // while the app sits on the login/splash screen goes straight there -
        // one catalog, no dashboard detour.
        return (location == '/login' || location == '/splash')
            ? UnifiedRoutes.catalog
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

      // ---- Unified business (one library, one detail, stock + labels) -------
      // The list is exported by the UI owner so the router stays owned by the
      // auth/integration side. Home entry: /catalog.
      ...unifiedRoutes,

      // ---- Compatibility redirects -----------------------------------------
      // The old dashboard is gone: every signed-in entry point resolves to the
      // unified library, so no second "inventory only" navigation exists.
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
