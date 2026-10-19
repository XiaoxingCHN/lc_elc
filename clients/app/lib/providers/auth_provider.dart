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
    baseUrl: OdooConfig.defaultBaseUrl,
    database: OdooConfig.defaultDatabase,
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
  Future<bool> login({
    required String baseUrl,
    required String database,
    required String login,
    required String password,
    required bool rememberLogin,
  }) {
    final scope = LoginScope.fromInput(
      baseUrl: baseUrl,
      database: database,
      login: login,
    );
    return _signIn(
      scope: scope,
      password: password,
      rememberLogin: rememberLogin,
      automatic: false,
    );
  }

  /// Explicit sign-out.
  ///
  /// Erases the stored password and blocks automatic sign-in until the next
  /// successful manual login. The account (server / database / user) and the
  /// operator's "记住登录" preference are kept.
  Future<void> logout() async {
    final scope = _activeScope ?? _store.lastUsedAccount?.scope;

    try {
      await _gateway.logout();
    } catch (e) {
      // Local sign-out must not depend on the server answering.
      _safe(e.toString());
    } finally {
      _gateway.resetLocalSession();
      _activeScope = null;

      if (scope != null) {
        await _store.deletePassword(scope);
        await _store.setAutoLoginBlocked(scope, true);
      }

      final account = scope == null ? null : _store.accountFor(scope);
      state = AuthState(
        status: AuthStatus.unauthenticated,
        savedAccount: account,
        baseUrl: account?.baseUrl,
        database: account?.database,
        rememberLogin: account?.rememberLogin ?? OdooConfig.rememberLoginDefault,
        secureStorageStatus: _store.storageStatus,
        manualLoginReason: ManualLoginReason.signedOut,
        noticeMessage: '已退出登录：本机保存的密码已清除，自动登录已关闭；'
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

    final scope = _activeScope;
    _gateway.resetLocalSession();
    _activeScope = null;

    final account =
        (scope == null ? null : _store.accountFor(scope)) ?? state.savedAccount;

    state = AuthState(
      status: AuthStatus.unauthenticated,
      savedAccount: account,
      baseUrl: account?.baseUrl ?? state.baseUrl,
      database: account?.database ?? state.database,
      rememberLogin: account?.rememberLogin ?? state.rememberLogin,
      secureStorageStatus: _store.storageStatus,
      manualLoginReason: ManualLoginReason.sessionExpired,
      noticeMessage: '登录状态已失效，请重新登录。账号与已保存的登录信息仍然保留。',
    );
  }

  // ---------------------------------------------------------------------------
  // Internals
  // ---------------------------------------------------------------------------

  /// The one and only sign-in path, used by both the form and automatic login.
  Future<bool> _signIn({
    required LoginScope scope,
    required String password,
    required bool rememberLogin,
    required bool automatic,
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
    // Step 2: persist. A local storage hiccup must not turn a valid session
    // into a failed login, so it is reported as a notice instead.
    // ---------------------------------------------------------------------
    final now = _clock();
    String? storageNotice;
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

    _activeScope = scope;
    state = AuthState(
      status: AuthStatus.authenticated,
      uid: uid,
      activeLogin: scope.login,
      baseUrl: _gateway.baseUrl,
      database: _gateway.database,
      savedAccount: _store.accountFor(scope),
      rememberLogin: rememberLogin,
      secureStorageStatus: _store.storageStatus,
      noticeMessage: storageNotice,
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

  /// Last line of defence: exception text can quote a URL or a payload.
  String _safe(String text) => redactForLog(text);
}
