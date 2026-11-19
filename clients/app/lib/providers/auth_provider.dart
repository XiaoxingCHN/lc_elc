import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/odoo_config.dart';
import '../models/odoo_exception.dart';
import '../services/auth_gateway.dart';
import '../services/clock.dart';
import '../services/dio_interceptor.dart';
import '../services/login_memory_store.dart';
import '../services/odoo_client.dart';
import '../services/secret_backend.dart';

/// Injecting the clock keeps the 10-day rule testable without touching the
/// machine clock (see test/services/login_freshness_test.dart).
final clockProvider = Provider<Clock>((ref) => systemClock);

/// Platform key store used for the one secret this client keeps.
final secretBackendProvider =
    Provider<SecretBackend>((ref) => const FlutterSecureStorageBackend());

/// Non-secret login preferences + the password secret.
final loginMemoryStoreProvider = Provider<LoginMemoryStore>((ref) {
  return LoginMemoryStore(
    backend: ref.watch(secretBackendProvider),
    clock: ref.watch(clockProvider),
  );
});

/// OdooClient provider - singleton instance.
///
/// Seeded with the build-time defaults, which may be empty strings. The login
/// flow passes whatever the operator typed to `OdooClient.configure`, which
/// repoints this same instance.
///
/// Kept as a [Provider] of the concrete [OdooClient] because the product
/// providers call the full ORM surface (`search_read`, `read`, ...) on it.
final odooClientProvider = Provider<OdooClient>((ref) {
  return OdooClient(
    // Public server by default (https). A build can still override it with
    // --dart-define=LAB_ODOO_URL=...; an empty define falls back to the public
    // deployment instead of leaving the form blank.
    baseUrl: OdooConfig.fallbackBaseUrl,
    database: OdooConfig.fallbackDatabase,
  );
});

/// The same single client instance, seen through the authentication-only
/// interface the login flow needs. Tests override this one provider to stay
/// entirely offline.
final authGatewayProvider = Provider<AuthGateway>((ref) {
  return ref.watch(odooClientProvider);
});

/// Stable identity of the CURRENT signed-in session, or `null` when signed out.
///
/// The unified UI keys its API caches and offline assets by this value, so a
/// different server, database, account or Odoo user id can never read another
/// session's cached images/manuals. It changes on every login and disappears on
/// sign-out or when the server invalidates the session.
///
/// Company scope is NOT part of this string: the server decides which companies
/// the session may read, and it reports that in `/lab/api/inventory/bootstrap` ->
/// `permissions`. The client-side identity deliberately stays to what it can
/// prove locally: server + database + user id + login name.
final sessionIdentityProvider = Provider<String?>((ref) {
  return ref.watch(authProvider.select((state) => state.sessionIdentity));
});

/// Authentication state provider.
final authProvider = StateNotifierProvider<AuthStateNotifier, AuthState>((ref) {
  final gateway = ref.watch(authGatewayProvider);
  final notifier = AuthStateNotifier(
    gateway: gateway,
    store: ref.watch(loginMemoryStoreProvider),
    clock: ref.watch(clockProvider),
  );

  // A business call answered with HTTP 401 / session-expired is routed back to
  // the login screen - without triggering any automatic sign-in attempt.
  gateway.onSessionInvalid = notifier.handleSessionInvalid;
  ref.onDispose(() => gateway.onSessionInvalid = null);

  return notifier;
});

enum AuthStatus {
  /// Reading the remembered account / trying the remembered password. The app
  /// shows a loading state here so the login form never flashes on startup.
  initializing,
  unauthenticated,
  authenticating,
  authenticated,
  error,
}

/// Why the operator has to type the password again (explains the on-screen
/// banner; [ManualLoginReason.none] means "nothing was pre-filled and nothing
/// went wrong").
enum ManualLoginReason {
  none,

  /// No account has ever been remembered on this machine.
  firstUse,

  /// `now - lastSuccessfulLoginAt >= 10 days`; the stored password was erased.
  expired,

  /// Device clock is behind the recorded success; the password was erased.
  clockSkew,

  /// Explicit sign-out earlier: the stored password was erased and automatic
  /// sign-in stays off until a manual login succeeds.
  signedOut,

  /// This machine has no usable key store, so a password cannot be remembered.
  storageUnavailable,

  /// The build/config supplies no server: the login form starts blank.
  noServer,

  /// The account is remembered but no password is stored for it.
  noStoredPassword,

  /// The server rejected the session (HTTP 401 / session expired) while the app
  /// was running. The remembered login is kept; a new automatic attempt is not
  /// started.
  sessionExpired,
}

class AuthState {
  const AuthState({
    this.status = AuthStatus.initializing,
    this.uid,
    this.activeLogin,
    this.errorMessage,
    this.noticeMessage,
    this.baseUrl,
    this.database,
    this.savedAccount,
    this.rememberLogin = OdooConfig.rememberLoginDefault,
    this.secureStorageStatus = SecureStorageStatus.unknown,
    this.manualLoginReason = ManualLoginReason.none,
    this.ephemeral = false,
    this.switching = false,
  });

  final AuthStatus status;
  final int? uid;

  /// Login name of the live session (never a password). `null` while signed out.
  final String? activeLogin;

  /// Actionable failure text (auto-login failed, credentials rejected, server
  /// unreachable). Shown in a banner and a snack bar.
  final String? errorMessage;

  /// Informational text that is not a failure (e.g. "10 days passed, type the
  /// password again", "this machine cannot store passwords").
  final String? noticeMessage;

  /// Server actually used for the current session (display only).
  final String? baseUrl;
  final String? database;

  /// Account whose server/database/user should be pre-filled on the login
  /// screen. Never contains a password.
  final RememberedAccount? savedAccount;

  /// The operator's single "记住登录" choice for the account being edited.
  final bool rememberLogin;

  /// Whether the last key-store operation worked.
  final SecureStorageStatus secureStorageStatus;

  final ManualLoginReason manualLoginReason;

  /// True when the live session is session-only (LAN acceleration).
  ///
  /// Nothing about such a session is persisted: no account entry, no password,
  /// no last-used mark, and the unified UI keeps its business cache in memory.
  final bool ephemeral;

  /// True while [AuthStateNotifier.switchServer] is contacting the other
  /// server. The old session stays usable until the new one is accepted.
  final bool switching;

  bool get isAuthenticated => status == AuthStatus.authenticated;
  bool get isLoading => status == AuthStatus.authenticating;
  bool get isInitializing => status == AuthStatus.initializing;
  bool get hasError => status == AuthStatus.error;

  /// Key for the unified UI's per-session caches, or `null` when signed out.
  String? get sessionIdentity {
    if (!isAuthenticated || uid == null) return null;
    return '${baseUrl ?? ''}|${database ?? ''}|$uid|${activeLogin ?? ''}';
  }

  /// True when this machine can keep a remembered password.
  bool get canRememberPassword =>
      secureStorageStatus != SecureStorageStatus.unavailable;

  static const Object _unset = Object();

  AuthState copyWith({
    AuthStatus? status,
    Object? uid = _unset,
    Object? activeLogin = _unset,
    Object? errorMessage = _unset,
    Object? noticeMessage = _unset,
    Object? baseUrl = _unset,
    Object? database = _unset,
    Object? savedAccount = _unset,
    bool? rememberLogin,
    SecureStorageStatus? secureStorageStatus,
    ManualLoginReason? manualLoginReason,
    bool? ephemeral,
    bool? switching,
  }) {
    return AuthState(
      status: status ?? this.status,
      uid: identical(uid, _unset) ? this.uid : uid as int?,
      activeLogin: identical(activeLogin, _unset)
          ? this.activeLogin
          : activeLogin as String?,
      errorMessage: identical(errorMessage, _unset)
          ? this.errorMessage
          : errorMessage as String?,
      noticeMessage: identical(noticeMessage, _unset)
          ? this.noticeMessage
          : noticeMessage as String?,
      baseUrl: identical(baseUrl, _unset) ? this.baseUrl : baseUrl as String?,
      database:
          identical(database, _unset) ? this.database : database as String?,
      savedAccount: identical(savedAccount, _unset)
          ? this.savedAccount
          : savedAccount as RememberedAccount?,
      rememberLogin: rememberLogin ?? this.rememberLogin,
      secureStorageStatus: secureStorageStatus ?? this.secureStorageStatus,
      manualLoginReason: manualLoginReason ?? this.manualLoginReason,
      ephemeral: ephemeral ?? this.ephemeral,
      switching: switching ?? this.switching,
    );
  }
}

/// Owns the whole "remember my login" behaviour.
///
/// Rules implemented here (and pinned by tests):
///   * server URL / database / user name are always remembered once a login
///     has succeeded, so the form is pre-filled on every later start;
///   * the password is written to the platform key store ONLY after the server
///     accepted it, and only when the operator left "记住登录" switched on;
///   * [RememberedAccount.lastSuccessfulLoginAt] is refreshed ONLY by a
///     successful server authentication - never on startup, never on a
///     failure, never on a network error;
///   * automatic sign-in needs all of: remembered account, "记住登录" on, no
///     sign-out block, a stored password, and `now - last < 10 days`;
///   * exactly one automatic attempt per start - no retry loop; a failure
///     lands on the login screen with an actionable message;
///   * >= 10 days (or a device clock behind the record) deletes the stored
///     password and the in-memory session but keeps the account.
class AuthStateNotifier extends StateNotifier<AuthState> {
  AuthStateNotifier({
    required AuthGateway gateway,
    required LoginMemoryStore store,
    required Clock clock,
  }) : this._(gateway, store, clock);

  AuthStateNotifier._(this._gateway, this._store, this._clock)
      : super(const AuthState());

  final AuthGateway _gateway;
  final LoginMemoryStore _store;
  final Clock _clock;

  bool _bootstrapStarted = false;
  bool _autoLoginAttempted = false;
  LoginScope? _activeScope;

  /// Gateway generation recorded when the live session was established.
  ///
  /// A session-invalid notification whose generation differs belongs to a
  /// session that has already been replaced (a server switch, a local reset),
  /// so it must not send the operator back to the login screen.
  int _activeGeneration = 0;

  /// True once [bootstrap] has been started (guards a second splash build).
  bool get bootstrapStarted => _bootstrapStarted;

  /// True once the single automatic sign-in attempt has been made.
  bool get autoLoginAttempted => _autoLoginAttempted;

  // ---------------------------------------------------------------------------
  // Startup
  // ---------------------------------------------------------------------------

  /// Runs once per process, driven by the splash screen.
  ///
  /// Until this completes the state stays [AuthStatus.initializing] and the
  /// router keeps the splash route visible, so the login form cannot flash.
  Future<void> bootstrap() async {
    if (_bootstrapStarted) return;
    _bootstrapStarted = true;

    try {
      await _store.ensureLoaded();
    } catch (e) {
      // The operator sees one plain sentence; the exception text (a filesystem
      // path and an errno) is not useful to them and must not be rendered.
      //
      // This path is reachable on Windows when the per-user preferences
      // directory is not writable (locked-down policy, roaming profile failure,
      // sandbox) - the app must still let the operator sign in for this session.
      state = const AuthState(
        status: AuthStatus.unauthenticated,
        secureStorageStatus: SecureStorageStatus.unavailable,
        manualLoginReason: ManualLoginReason.storageUnavailable,
        noticeMessage: '无法读取本机登录记录，请手动登录。',
      );
      return;
    }

    final account = _store.lastUsedAccount;
    if (account == null) {
      state = const AuthState(status: AuthStatus.unauthenticated);
      return;
    }

    final base = AuthState(
      status: AuthStatus.unauthenticated,
      baseUrl: account.baseUrl,
      database: account.database,
      savedAccount: account,
      rememberLogin: account.rememberLogin,
      secureStorageStatus: _store.storageStatus,
    );

    if (!account.rememberLogin) {
      state = base.copyWith(
        manualLoginReason: ManualLoginReason.noStoredPassword,
        noticeMessage: '上次登录未选择“记住登录”，请输入密码后继续。',
      );
      return;
    }

    if (account.autoLoginBlocked) {
      state = base.copyWith(
        manualLoginReason: ManualLoginReason.signedOut,
        noticeMessage: '上次已退出登录，请重新输入密码（服务器、数据库和用户名已保留）。',
      );
      return;
    }

    final freshness = _store.freshnessOf(account);
    if (freshness != CredentialFreshness.fresh) {
      await _discardStaleCredential(account);
      state = base.copyWith(
        manualLoginReason: freshness == CredentialFreshness.clockSkew
            ? ManualLoginReason.clockSkew
            : ManualLoginReason.expired,
        noticeMessage: _freshnessMessage(freshness),
      );
      return;
    }

    String? password;
    try {
      password = await _store.readPassword(account.scope);
    } on SecretStorageUnavailableException catch (e) {
      _gateway.resetLocalSession();
      state = base.copyWith(
        secureStorageStatus: SecureStorageStatus.unavailable,
        manualLoginReason: ManualLoginReason.storageUnavailable,
        noticeMessage: '${e.message}仍可正常登录，密码只在本次使用，不会保存。',
      );
      return;
    }

    if (password == null) {
      state = base.copyWith(
        manualLoginReason: ManualLoginReason.noStoredPassword,
        noticeMessage: '本机没有保存的密码，请输入密码后继续（账号已保留）。',
      );
      return;
    }

    // Exactly one automatic attempt per start. No retry, ever.
    _autoLoginAttempted = true;
    await _signIn(
      scope: account.scope,
      password: password,
      rememberLogin: true,
      automatic: true,
    );
  }

  // ---------------------------------------------------------------------------
  // Manual login / sign-out
  // ---------------------------------------------------------------------------

  /// Signs in with operator-supplied values.
  ///
  /// [rememberLogin] is the single "记住登录" switch. When it is on, the
  /// password is written to the platform key store - but only after
  /// authentication succeeded. When it is off, any password stored for this
  /// exact account is deleted.
  /// [ephemeral] true is the session-only path (LAN acceleration): the server
  /// accepts the credentials, but nothing about the account is written to the
  /// disk and it never becomes the last-used account.
  Future<bool> login({
    required String baseUrl,
    required String database,
    required String login,
    required String password,
    required bool rememberLogin,
    bool ephemeral = false,
  }) {
    final scope = LoginScope.fromInput(
      baseUrl: baseUrl,
      database: database,
      login: login,
    );
    return _signIn(
      scope: scope,
      password: password,
      rememberLogin: ephemeral ? false : rememberLogin,
      automatic: false,
      ephemeral: ephemeral,
    );
  }

  // ---------------------------------------------------------------------------
  // Atomic server switch (public <-> LAN)
  // ---------------------------------------------------------------------------

  /// Moves the LIVE session to another server/database without a logout.
  ///
  /// Semantics (pinned by test/providers/auth_provider_test.dart):
  ///   * in-flight requests of the old session are cancelled first;
  ///   * the new server is authenticated on a throw-away session, so a
  ///     rejection or a network failure keeps the old session AND the old
  ///     account exactly as they were;
  ///   * only on success are baseUrl/database/uid committed atomically, and
  ///     the session-invalid generation is advanced so a late 401 from the old
  ///     session cannot tear down the new one;
  ///   * switching INTO the LAN is ephemeral; switching BACK to the public
  ///     server stays ephemeral too (the session was started without a stored
  ///     account and must not silently create one).
  ///
  /// [password] is the password of [login] (the operator re-enters it: a
  /// session-only login has no stored secret to reuse).
  ///
  /// The new session is ALWAYS ephemeral: the switch itself may not create a
  /// remembered account, so a LAN session can never become `lastUsedAccount`.
  Future<bool> switchServer({
    required String baseUrl,
    required String database,
    required String login,
    required String password,
  }) async {
    if (!state.isAuthenticated || _activeScope == null) {
      state = state.copyWith(
        errorMessage: '当前没有可切换的登录会话，请重新登录。',
      );
      return false;
    }

    final scope = LoginScope.fromInput(
      baseUrl: baseUrl,
      database: database,
      login: login,
    );
    final previous = state;

    state = state.copyWith(
      switching: true,
      errorMessage: null,
      noticeMessage: null,
    );

    // 1. Stop the old session's traffic; anything that answers late is ignored.
    _gateway.cancelInFlightRequests();

    // 2. Authenticate on the new server WITHOUT touching the live session.
    final int uid;
    try {
      uid = await _gateway.authenticateAt(
        baseUrl: scope.baseUrl,
        database: scope.database,
        login: scope.login,
        password: password,
      );
    } catch (e) {
      // Nothing was committed: the old session and account survive.
      state = previous.copyWith(
        switching: false,
        errorMessage: '切换失败：${_failureDetail(e)}'
            '当前仍连接原服务器，会话保持不变。',
      );
      return false;
    }

    // 3. Commit. authenticateAt already replaced the uid + cookie jar on the
    // live client, so nothing else has to be reset here.
    _activeScope = scope;
    _activeGeneration = _gateway.sessionGeneration;
    // Switching INTO the LAN records the in-memory address; switching back to
    // the public server clears it (see [switchToPublic]).
    if (OdooConfig.isPrivateNetworkHost(Uri.parse(scope.baseUrl).host)) {
      OdooConfig.setRuntimeLanBaseUrl(scope.baseUrl);
    }

    state = AuthState(
      status: AuthStatus.authenticated,
      uid: uid,
      activeLogin: scope.login,
      baseUrl: _gateway.baseUrl,
      database: _gateway.database,
      // Session-only: never a remembered account.
      savedAccount: null,
      rememberLogin: false,
      secureStorageStatus: _store.storageStatus,
      ephemeral: true,
      noticeMessage: '已切换到 ${scope.baseUrl}（本次运行有效，退出即清除）。',
    );
    return true;
  }

  /// Leaves the LAN acceleration session and returns to the public server.
  ///
  /// This is [switchServer] plus clearing the in-memory LAN address. It does
  /// NOT log the operator out: a failed switch keeps the LAN session.
  Future<bool> switchToPublic({
    required String baseUrl,
    required String database,
    required String login,
    required String password,
  }) async {
    final ok = await switchServer(
      baseUrl: baseUrl,
      database: database,
      login: login,
      password: password,
    );
    if (ok) {
      // Leaving the LAN: the address exists only for this process anyway.
      OdooConfig.setRuntimeLanBaseUrl(null);
    }
    return ok;
  }

  /// Explicit sign-out.
  ///
  /// Erases the stored password and blocks automatic sign-in until the next
  /// successful manual login. The account (server / database / user) and the
  /// operator's "记住登录" preference are kept.
  Future<void> logout() async {
    final wasEphemeral = state.ephemeral;
    final scope = _activeScope ??
        (wasEphemeral ? null : _store.lastUsedAccount?.scope);

    try {
      await _gateway.logout();
    } catch (e) {
      // Local sign-out must not depend on the server answering.
      _safe(e.toString());
    } finally {
      _gateway.resetLocalSession();
      _activeScope = null;
      // The LAN address only ever lived in memory; sign-out clears it too.
      OdooConfig.setRuntimeLanBaseUrl(null);

      // A session-only account was never remembered, so there is no stored
      // password or sign-out block to write. Deleting anyway is a no-op and
      // covers a switch that made a previously stored account ephemeral.
      if (scope != null) {
        await _store.deletePassword(scope);
        if (!wasEphemeral) {
          await _store.setAutoLoginBlocked(scope, true);
        }
      }

      final account =
          wasEphemeral || scope == null ? null : _store.accountFor(scope);
      state = AuthState(
        status: AuthStatus.unauthenticated,
        savedAccount: account,
        baseUrl: account?.baseUrl,
        database: account?.database,
        rememberLogin: account?.rememberLogin ?? OdooConfig.rememberLoginDefault,
        secureStorageStatus: _store.storageStatus,
        manualLoginReason: ManualLoginReason.signedOut,
        noticeMessage: wasEphemeral
            ? '已退出内网加速会话：本次运行的服务器与 WiFi 信息已清除。'
            : '已退出登录：本机保存的密码已清除，自动登录已关闭；'
                '服务器、数据库和用户名仍然保留。',
      );
    }
  }

  // ---------------------------------------------------------------------------
  // Login-screen helpers
  // ---------------------------------------------------------------------------

  /// Password to pre-fill on the login screen, or `null`.
  ///
  /// Returns a value only when the operator asked to be remembered, the account
  /// is inside the freshness window, no sign-out block is set and the stored
  /// secret exists. Called after a failed automatic attempt (e.g. the server
  /// was briefly unreachable) so one click retries it.
  Future<String?> revealRememberedPassword({
    required String baseUrl,
    required String database,
    required String login,
  }) async {
    final scope = LoginScope.fromInput(
      baseUrl: baseUrl,
      database: database,
      login: login,
    );
    final account = _store.accountFor(scope);
    if (account == null ||
        !account.rememberLogin ||
        account.autoLoginBlocked ||
        _store.freshnessOf(account) != CredentialFreshness.fresh) {
      return null;
    }
    try {
      return await _store.readPassword(scope);
    } on SecretStorageUnavailableException {
      return null;
    }
  }

  /// Mirrors the "记住登录" switch.
  ///
  /// Switching it off deletes the stored password for this exact account
  /// immediately - before the next login, not on the next login.
  Future<void> setRememberLoginPreference({
    required String baseUrl,
    required String database,
    required String login,
    required bool value,
  }) async {
    final scope = LoginScope.fromInput(
      baseUrl: baseUrl,
      database: database,
      login: login,
    );

    state = state.copyWith(rememberLogin: value);

    if (!value) {
      await _store.deletePassword(scope);
    }
    // No-op when this (server, database, user) has never logged in; the choice
    // is then carried by the form and stored together with the account on the
    // next successful login.
    await _store.setRememberLogin(scope, value);
  }

  /// Deletes the stored password for one account, keeping the account.
  Future<void> forgetSavedPassword({
    required String baseUrl,
    required String database,
    required String login,
  }) async {
    final scope = LoginScope.fromInput(
      baseUrl: baseUrl,
      database: database,
      login: login,
    );
    await _store.deletePassword(scope);
    await _store.setRememberLogin(scope, false);
    state = state.copyWith(
      rememberLogin: false,
      noticeMessage: '已清除本机保存的密码（服务器、数据库和用户名仍保留）。',
    );
  }

  /// Deletes every remembered account and every stored password.
  Future<void> forgetAllRememberedLogins() async {
    await _store.forgetAll();
    state = const AuthState(
      status: AuthStatus.unauthenticated,
      noticeMessage: '已清除本机记住的全部账号与密码。',
    );
  }

  /// Called when the server reports that the session is no longer valid.
  ///
  /// Returns the app to the login screen and does nothing else:
  ///   * NO automatic sign-in attempt and no retry - that is the loop this
  ///     guard exists to prevent;
  ///   * the remembered account and the stored password are kept, because an
  ///     expired server session says nothing about the credential.
  void handleSessionInvalid() {
    if (!mounted) return;

    // Already handled: further 401s from parallel requests must not keep
    // resetting the screen.
    if (!state.isAuthenticated &&
        state.manualLoginReason == ManualLoginReason.sessionExpired) {
      return;
    }

    // A 401 that belongs to a session which has already been replaced (server
    // switch, local reset, sign-out) must not sign the NEW session out.
    if (state.isAuthenticated && _gateway.sessionGeneration != _activeGeneration) {
      return;
    }

    final wasEphemeral = state.ephemeral;
    final scope = _activeScope;
    _gateway.resetLocalSession();
    _activeScope = null;
    if (wasEphemeral) OdooConfig.setRuntimeLanBaseUrl(null);

    final account = wasEphemeral
        ? null
        : (scope == null ? null : _store.accountFor(scope)) ?? state.savedAccount;

    state = AuthState(
      status: AuthStatus.unauthenticated,
      savedAccount: account,
      baseUrl: wasEphemeral ? null : account?.baseUrl ?? state.baseUrl,
      database: wasEphemeral ? null : account?.database ?? state.database,
      rememberLogin: wasEphemeral
          ? OdooConfig.rememberLoginDefault
          : account?.rememberLogin ?? state.rememberLogin,
      secureStorageStatus: _store.storageStatus,
      manualLoginReason: ManualLoginReason.sessionExpired,
      ephemeral: wasEphemeral,
      noticeMessage: wasEphemeral
          ? '内网加速会话已失效，请重新登录（本次运行的服务器信息已清除）。'
          : '登录状态已失效，请重新登录。账号与已保存的登录信息仍然保留。',
    );
  }

  // ---------------------------------------------------------------------------
  // Internals
  // ---------------------------------------------------------------------------

  /// Checks credentials without establishing or disturbing a session.
  ///
  /// Used by the "测试连接" button of "服务器与内网加速". The live session is
  /// untouched whether the probe succeeds or fails.
  Future<bool> testConnection({
    required String baseUrl,
    required String database,
    required String login,
    required String password,
  }) async {
    final scope = LoginScope.fromInput(
      baseUrl: baseUrl,
      database: database,
      login: login,
    );
    try {
      await _gateway.probe(
        baseUrl: scope.baseUrl,
        database: scope.database,
        login: scope.login,
        password: password,
      );
      return true;
    } catch (_) {
      return false;
    }
  }

  /// The one and only sign-in path, used by both the form and automatic login.
  Future<bool> _signIn({
    required LoginScope scope,
    required String password,
    required bool rememberLogin,
    required bool automatic,
    bool ephemeral = false,
  }) async {
    state = state.copyWith(
      status: AuthStatus.authenticating,
      errorMessage: null,
      noticeMessage: null,
      manualLoginReason: ManualLoginReason.none,
      baseUrl: scope.baseUrl,
      database: scope.database,
      rememberLogin: rememberLogin,
    );

    // ---------------------------------------------------------------------
    // Step 1: the server decides. Everything below this block runs only when
    // the credentials were actually accepted.
    // ---------------------------------------------------------------------
    final int uid;
    try {
      _gateway.configure(baseUrl: scope.baseUrl, database: scope.database);
      uid = await _gateway.authenticate(scope.login, password);
    } catch (e) {
      // Nothing is written on this path: no password, no timestamp refresh.
      state = state.copyWith(
        status: AuthStatus.error,
        errorMessage: _failureMessage(e, scope: scope, automatic: automatic),
        savedAccount: _store.accountFor(scope) ?? state.savedAccount,
      );
      return false;
    }

    // ---------------------------------------------------------------------
    // Step 2: persist - EXCEPT for a session-only (LAN) login, which must not
    // leave anything on disk: no account entry, no password, no last-used
    // mark, and therefore no pre-fill or auto-login after a restart.
    // ---------------------------------------------------------------------
    final now = _clock();
    String? storageNotice;
    if (!ephemeral) {
      try {
        await _store.rememberAccount(scope, rememberLogin: rememberLogin, at: now);

        if (rememberLogin) {
          try {
            await _store.savePassword(scope, password);
          } on SecretStorageUnavailableException catch (e) {
            storageNotice = '${e.message}密码未保存，本次登录仍然有效；'
                '下次打开需要重新输入密码。';
          }
        } else {
          // "记住登录" off means nothing may stay behind for this account.
          await _store.deletePassword(scope);
        }

        await _store.markSuccessfulLogin(scope, at: now);
      } catch (e) {
        storageNotice = '登录成功，但本机登录记录写入失败：${_safe(e.toString())}';
      }
    } else {
      OdooConfig.setRuntimeLanBaseUrl(scope.baseUrl);
    }

    _activeScope = scope;
    _activeGeneration = _gateway.sessionGeneration;
    state = AuthState(
      status: AuthStatus.authenticated,
      uid: uid,
      activeLogin: scope.login,
      baseUrl: _gateway.baseUrl,
      database: _gateway.database,
      // A session-only login is never a remembered account.
      savedAccount: ephemeral ? null : _store.accountFor(scope),
      rememberLogin: ephemeral ? false : rememberLogin,
      secureStorageStatus: _store.storageStatus,
      ephemeral: ephemeral,
      noticeMessage: ephemeral
          ? '内网加速会话：仅本次运行有效，退出即清除；不保留离线缓存。'
          : storageNotice,
    );
    return true;
  }

  /// Erases a credential that may no longer be used, without any network call.
  ///
  /// The account entry (server, database, user, "记住登录" choice) survives so
  /// the operator only has to type the password.
  Future<void> _discardStaleCredential(RememberedAccount account) async {
    await _store.deletePassword(account.scope);
    _gateway.resetLocalSession();
    _activeScope = null;
  }

  String _freshnessMessage(CredentialFreshness freshness) {
    final window = _windowLabel();
    switch (freshness) {
      case CredentialFreshness.expired:
        return '已超过 $window 没有成功登录，本机保存的密码已自动清除。'
            '请输入密码后继续（服务器、数据库和用户名已保留）。';
      case CredentialFreshness.clockSkew:
        return '检测到本机时间早于上次成功登录的时间，无法确认凭据仍在 $window 内，'
            '已清除保存的密码。请输入密码后继续（账号已保留）。';
      case CredentialFreshness.missing:
        return '本机缺少上次成功登录的时间记录，请输入密码后继续（账号已保留）。';
      case CredentialFreshness.fresh:
        return '';
    }
  }

  String _windowLabel() {
    final validity = _store.validity;
    if (validity.inSeconds % Duration.secondsPerDay == 0) {
      return '${validity.inDays} 天';
    }
    if (validity.inSeconds % Duration.secondsPerHour == 0) {
      return '${validity.inHours} 小时';
    }
    return '${validity.inSeconds} 秒';
  }

  String _failureMessage(
    Object error, {
    required LoginScope scope,
    required bool automatic,
  }) {
    final prefix = automatic ? '自动登录失败' : '登录失败';
    final suffix = automatic
        ? '请在下方手动登录。'
        : '请检查后重试，或修改服务器地址与数据库。';

    if (error is OdooAuthException) {
      return '$prefix：服务器拒绝了用户名或密码（${_safe(error.message)}）。$suffix';
    }
    if (error is OdooNetworkException) {
      // OdooClient already explains a cleartext HTTP address on Android.
      return '$prefix：无法连接 ${scope.baseUrl}。${_safe(error.message)}'
          '请检查服务器地址与网络。';
    }
    if (error is OdooException) {
      return '$prefix：${_safe(error.message)}';
    }
    return '$prefix：${_safe(error.toString())}';
  }

  /// Operator-facing sentence for a failed server switch.
  String _failureDetail(Object error) {
    if (error is OdooAuthException) {
      return '服务器拒绝了用户名或密码（${_safe(error.message)}）。';
    }
    if (error is OdooNetworkException) {
      return '无法连接新服务器。${_safe(error.message)}';
    }
    if (error is OdooException) {
      return '${_safe(error.message)}。';
    }
    return '${_safe(error.toString())}。';
  }

  /// Last line of defence: exception text can quote a URL or a payload.
  String _safe(String text) => redactForLog(text);
}
