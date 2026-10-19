import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lab_inventory_client/providers/auth_provider.dart';
import 'package:lab_inventory_client/services/auth_gateway.dart';
import 'package:lab_inventory_client/services/login_memory_store.dart';
import 'package:lab_inventory_client/services/odoo_client.dart';
import 'package:lab_inventory_client/services/secret_backend.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// One recorded call into [AuthGateway.authenticate].
typedef AuthCall = ({
  String login,
  String password,
  String baseUrl,
  String database,
});

/// Offline stand-in for [AuthGateway].
///
/// No test in this repository may contact the laboratory Odoo server, so every
/// authentication decision is recorded here instead of being sent anywhere.
class FakeAuthGateway implements AuthGateway {
  FakeAuthGateway({this.successUid = 7, this.failure});

  /// uid returned by a successful authentication.
  final int successUid;

  /// When set, [authenticate] throws this instead of succeeding.
  Object? failure;

  final List<AuthCall> calls = <AuthCall>[];
  int configureCount = 0;
  int logoutCount = 0;
  int resetSessionCount = 0;

  String _baseUrl = '';
  String _database = '';
  int? _uid;

  @override
  String get baseUrl => _baseUrl;

  @override
  String get database => _database;

  @override
  int? get uid => _uid;

  @override
  bool get isAuthenticated => _uid != null;

  /// Passwords actually handed to the network layer, in order.
  List<String> get submittedPasswords =>
      calls.map((call) => call.password).toList(growable: false);

  @override
  void configure({required String baseUrl, required String database}) {
    _baseUrl = baseUrl;
    _database = database;
    _uid = null;
    configureCount++;
  }

  @override
  Future<int> authenticate(String login, String password) async {
    calls.add((
      login: login,
      password: password,
      baseUrl: _baseUrl,
      database: _database,
    ));

    final Object? pending = failure;
    if (pending != null) throw pending;

    _uid = successUid;
    return successUid;
  }

  @override
  Future<void> logout() async {
    logoutCount++;
    _uid = null;
  }

  @override
  void resetLocalSession() {
    resetSessionCount++;
    _uid = null;
  }

  void Function()? _onSessionInvalid;

  @override
  set onSessionInvalid(void Function()? handler) => _onSessionInvalid = handler;

  /// Simulates what [OdooClient] does when a business call is answered with
  /// HTTP 401 / a session-expired error.
  void fireSessionInvalid() => _onSessionInvalid?.call();
}

/// Working key store, in memory.
class InMemorySecretBackend implements SecretBackend {
  final Map<String, String> values = <String, String>{};
  final List<String> writes = <String>[];
  final List<String> reads = <String>[];
  final List<String> deletes = <String>[];

  bool contains(String key) => values.containsKey(key);

  @override
  Future<String?> read(String key) async {
    reads.add(key);
    return values[key];
  }

  @override
  Future<void> write(String key, String value) async {
    writes.add(key);
    values[key] = value;
  }

  @override
  Future<void> delete(String key) async {
    deletes.add(key);
    values.remove(key);
  }
}

/// Simulates a machine without a usable key store: the realistic case is a
/// headless Linux box with no libsecret / gnome-keyring / KWallet running.
class UnavailableSecretBackend implements SecretBackend {
  const UnavailableSecretBackend([
    this.message = '当前系统没有可用的安全存储，无法保存密码。',
  ]);

  final String message;

  Never _fail() => throw SecretStorageUnavailableException(message);

  @override
  Future<String?> read(String key) async => _fail();

  @override
  Future<void> write(String key, String value) async => _fail();

  @override
  Future<void> delete(String key) async => _fail();
}

/// Builds a container whose login flow is entirely offline and whose clock is
/// frozen at [now].
///
/// [apiClient] is for widget tests of the signed-in UI: they need the unified
/// catalog screen to render real contract-shaped data, so they pass
/// [FakeOdooApiClient] and no socket is ever opened.
ProviderContainer buildAuthContainer({
  required SecretBackend backend,
  required FakeAuthGateway gateway,
  required DateTime now,
  OdooClient? apiClient,
}) {
  return ProviderContainer(
    overrides: [
      secretBackendProvider.overrideWithValue(backend),
      authGatewayProvider.overrideWithValue(gateway),
      clockProvider.overrideWithValue(() => now),
      if (apiClient != null) odooClientProvider.overrideWithValue(apiClient),
    ],
  );
}

/// Stand-in for the business API inside widget tests.
///
/// Only [callRoute] is replaced: it answers with payloads shaped exactly like
/// `lc_elc/docs/business_api_contract.json`, so the unified catalog screen runs
/// its real parsing, real state machine and real widgets. Authentication is not
/// part of this fake - widget tests drive that through [FakeAuthGateway].
class FakeOdooApiClient extends OdooClient {
  FakeOdooApiClient({
    this.items = const <Map<String, dynamic>>[],
    this.categories = const <Map<String, dynamic>>[],
    super.baseUrl = 'http://127.0.0.1:8069',
    super.database = 'LcHardwareHouse',
  });

  /// Rows returned by `/lab/api/catalog/search`.
  final List<Map<String, dynamic>> items;

  /// Nodes returned by `/lab/api/catalog/categories`.
  final List<Map<String, dynamic>> categories;

  /// Every path the UI asked for, in order.
  final List<String> requestedPaths = <String>[];

  @override
  Future<Map<String, dynamic>> callRoute(
    String path,
    Map<String, dynamic> params,
  ) async {
    requestedPaths.add(path);

    if (path.endsWith('/catalog/search')) {
      return <String, dynamic>{
        'items': items,
        'next_cursor': null,
        'total': items.length,
        'inventory_revision': 'rev-1',
        'catalog_revision': 'cat-1',
      };
    }
    if (path.endsWith('/catalog/categories')) {
      return <String, dynamic>{'categories': categories};
    }
    if (path.endsWith('/catalog/facets')) {
      return <String, dynamic>{
        'brands': <dynamic>[],
        'packages': <dynamic>[],
        'parameters': <dynamic>[],
      };
    }
    if (path.endsWith('/inventory/bootstrap')) {
      return <String, dynamic>{
        'locations': <dynamic>[],
        'borrowers': <dynamic>[],
        'permissions': <String, dynamic>{},
        'inventory_revision': 'rev-1',
      };
    }
    // Anything else the UI asks for in a test is an empty but SUCCESSFUL answer;
    // a failure here would make the test assert an error screen by accident.
    return <String, dynamic>{};
  }
}

/// Reads the non-secret preference document the way a reviewer would: straight
/// out of shared_preferences, to prove no password can be in it.
Future<String> rawPreferenceDocument() async {
  final prefs = await SharedPreferences.getInstance();
  return prefs.getString(LoginMemoryStore.prefsKey) ?? '';
}

/// Convenience: the secret key one specific account would use.
String secretKeyFor(String baseUrl, String database, String login) =>
    LoginScope.fromInput(
      baseUrl: baseUrl,
      database: database,
      login: login,
    ).secretKey;

/// A previously successful, still-fresh account, as it would look after a
/// normal login (non-secret record + secret in the key store).
Future<void> seedRememberedLogin({
  required LoginMemoryStore store,
  required DateTime lastSuccessfulLoginAt,
  String baseUrl = 'http://192.168.31.105:8069',
  String database = 'LcHardwareHouse',
  String login = 'lab_operator',
  String password = 'pw-A',
  bool rememberLogin = true,
  bool autoLoginBlocked = false,
}) async {
  final scope = LoginScope.fromInput(
    baseUrl: baseUrl,
    database: database,
    login: login,
  );

  await store.rememberAccount(
    scope,
    rememberLogin: rememberLogin,
    at: lastSuccessfulLoginAt,
  );
  await store.markSuccessfulLogin(scope, at: lastSuccessfulLoginAt);
  if (autoLoginBlocked) {
    await store.setAutoLoginBlocked(scope, true);
  }
  if (rememberLogin) {
    await store.savePassword(scope, password);
  }
}
