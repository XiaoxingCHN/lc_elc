import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../config/odoo_config.dart';
import 'clock.dart';
import 'secret_backend.dart';

/// Result of asking "may this stored credential still sign in by itself?".
enum CredentialFreshness {
  /// A successful server authentication happened inside the validity window.
  fresh,

  /// `now - last >= validity`. The operator types the password again.
  expired,

  /// The device clock is EARLIER than the recorded success (timezone change,
  /// dead CMOS battery, manual clock change). Treated as not-fresh on purpose:
  /// a negative interval must never extend the credential forever.
  clockSkew,

  /// No successful login was ever recorded for this account, so freshness
  /// cannot be proven.
  missing,
}

/// Pure policy function - the whole 10-day rule lives here.
///
/// [lastSuccessfulLoginAtMs] is the epoch-millisecond stamp written ONLY after
/// the server accepted a password.
CredentialFreshness evaluateCredentialFreshness({
  required int? lastSuccessfulLoginAtMs,
  required DateTime now,
  required Duration validity,
}) {
  if (lastSuccessfulLoginAtMs == null) return CredentialFreshness.missing;

  final last = DateTime.fromMillisecondsSinceEpoch(lastSuccessfulLoginAtMs);
  final elapsed = now.difference(last);

  // Clock moved backwards: refuse, but do not extend.
  if (elapsed.isNegative) return CredentialFreshness.clockSkew;

  // Boundary is inclusive: exactly 10 days already requires the password.
  if (elapsed >= validity) return CredentialFreshness.expired;

  return CredentialFreshness.fresh;
}

/// The identity of one login: server + database + user name.
///
/// All three always come from operator input and are normalised the same way
/// the client normalises them before use, so "http://h:8069/" and
/// "http://h:8069" are one account.
class LoginScope {
  const LoginScope({
    required this.baseUrl,
    required this.database,
    required this.login,
  });

  factory LoginScope.fromInput({
    required String baseUrl,
    required String database,
    required String login,
  }) {
    return LoginScope(
      baseUrl: OdooConfig.normalizeBaseUrl(baseUrl),
      database: database.trim(),
      login: login.trim(),
    );
  }

  final String baseUrl;
  final String database;
  final String login;

  /// Stable, filesystem-safe id.
  ///
  /// The Windows backend writes its encrypted blob into a keyed store and the
  /// Android backend uses the key as a preference key, so the raw URL ("/"
  /// and ":") cannot be used. sha256 also guarantees that the same password
  /// slot is reachable only from the exact (server, database, user) triple:
  /// pointing the client at another server can therefore not pick up the old
  /// password.
  String get id => sha256
      .convert(utf8.encode('$baseUrl\n$database\n$login'))
      .toString();

  /// Key name inside the platform key store.
  String get secretKey => '${OdooConfig.secureStorageKeyPrefix}.$id';

  @override
  bool operator ==(Object other) =>
      other is LoginScope &&
      other.baseUrl == baseUrl &&
      other.database == database &&
      other.login == login;

  @override
  int get hashCode => Object.hash(baseUrl, database, login);

  /// Never includes a password - there is none in this object.
  @override
  String toString() => 'LoginScope($baseUrl, $database, $login)';
}

/// One remembered account.
///
/// Everything in here is NON-SECRET and lives in `shared_preferences`: the
/// server address, the database, the user name, the operator's "记住登录"
/// choice and the timestamp of the last successful login. The password is the
/// only secret and it is stored separately, in the platform key store, keyed
/// by [LoginScope.secretKey].
class RememberedAccount {
  const RememberedAccount({
    required this.baseUrl,
    required this.database,
    required this.login,
    required this.rememberLogin,
    this.lastSuccessfulLoginAt,
    this.autoLoginBlocked = false,
    this.lastUsedAt = 0,
  });

  factory RememberedAccount.fromJson(Map<String, dynamic> json) {
    return RememberedAccount(
      baseUrl: (json['baseUrl'] as String? ?? '').trim(),
      database: (json['database'] as String? ?? '').trim(),
      login: (json['login'] as String? ?? '').trim(),
      rememberLogin: json['rememberLogin'] as bool? ?? false,
      lastSuccessfulLoginAt: (json['lastSuccessfulLoginAt'] as num?)?.toInt(),
      autoLoginBlocked: json['autoLoginBlocked'] as bool? ?? false,
      lastUsedAt: (json['lastUsedAt'] as num?)?.toInt() ?? 0,
    );
  }

  final String baseUrl;
  final String database;
  final String login;

  /// The operator's single "记住登录" choice for this account.
  final bool rememberLogin;

  /// Epoch ms of the last server-accepted authentication. Only ever written
  /// after `authenticate()` returned a uid.
  final int? lastSuccessfulLoginAt;

  /// Set by an explicit sign-out: automatic sign-in stays off until the next
  /// successful manual login. Kept separate from [rememberLogin] so a sign-out
  /// does not silently erase the operator's preference.
  final bool autoLoginBlocked;

  /// Ordering hint; the most recently used account is pre-filled.
  final int lastUsedAt;

  LoginScope get scope => LoginScope(
        baseUrl: baseUrl,
        database: database,
        login: login,
      );

  bool get hasCompleteIdentity =>
      baseUrl.isNotEmpty && database.isNotEmpty && login.isNotEmpty;

  RememberedAccount copyWith({
    String? baseUrl,
    String? database,
    String? login,
    bool? rememberLogin,
    int? lastSuccessfulLoginAt,
    bool? autoLoginBlocked,
    int? lastUsedAt,
  }) {
    return RememberedAccount(
      baseUrl: baseUrl ?? this.baseUrl,
      database: database ?? this.database,
      login: login ?? this.login,
      rememberLogin: rememberLogin ?? this.rememberLogin,
      lastSuccessfulLoginAt:
          lastSuccessfulLoginAt ?? this.lastSuccessfulLoginAt,
      autoLoginBlocked: autoLoginBlocked ?? this.autoLoginBlocked,
      lastUsedAt: lastUsedAt ?? this.lastUsedAt,
    );
  }

  Map<String, dynamic> toJson() => <String, dynamic>{
        'baseUrl': baseUrl,
        'database': database,
        'login': login,
        'rememberLogin': rememberLogin,
        if (lastSuccessfulLoginAt != null)
          'lastSuccessfulLoginAt': lastSuccessfulLoginAt,
        'autoLoginBlocked': autoLoginBlocked,
        'lastUsedAt': lastUsedAt,
      };

  /// Deliberately excludes nothing secret, because there is nothing secret
  /// here. A password never enters this object.
  @override
  String toString() =>
      'RememberedAccount($baseUrl, $database, $login, rememberLogin: '
      '$rememberLogin, lastSuccessfulLoginAt: $lastSuccessfulLoginAt, '
      'autoLoginBlocked: $autoLoginBlocked)';
}

/// Whether this machine can keep a secret at all.
enum SecureStorageStatus {
  /// Not probed yet (nothing needed to be read or written).
  unknown,

  /// Last key-store operation succeeded.
  available,

  /// Last key-store operation failed. Passwords cannot be remembered here.
  unavailable,
}

/// Loading hook so tests can inject `SharedPreferences.setMockInitialValues`.
typedef PreferencesLoader = Future<SharedPreferences> Function();

/// Persistence for the remembered accounts (non-secret prefs) plus the single
/// password secret (platform key store).
///
/// Storage layout:
///   * `shared_preferences` key `lc_elc.login.accounts.v1` -> one JSON document
///     with every remembered account. Never contains a password.
///   * platform key store key `<prefix>.<sha256(server|db|user)>` -> password,
///     written only after the server accepted it.
class LoginMemoryStore {
  LoginMemoryStore({
    required SecretBackend backend,
    required Clock clock,
    Duration? validity,
    PreferencesLoader? preferencesLoader,
  }) : this._(
          backend,
          clock,
          validity ?? OdooConfig.rememberLoginValidity,
          preferencesLoader ?? SharedPreferences.getInstance,
        );

  LoginMemoryStore._(
    this._backend,
    this._clock,
    this._validity,
    this._loadPreferences,
  );

  static const String prefsKey = 'lc_elc.login.accounts.v1';

  final SecretBackend _backend;
  final Clock _clock;
  final Duration _validity;
  final PreferencesLoader _loadPreferences;

  SharedPreferences? _prefs;
  Future<void>? _loading;
  List<RememberedAccount> _accounts = <RememberedAccount>[];

  SecureStorageStatus _storageStatus = SecureStorageStatus.unknown;
  String? _storageMessage;

  Duration get validity => _validity;
  List<RememberedAccount> get accounts => List.unmodifiable(_accounts);
  SecureStorageStatus get storageStatus => _storageStatus;
  String? get storageMessage => _storageMessage;

  /// Most recently used account, or `null` when nothing is remembered.
  RememberedAccount? get lastUsedAccount {
    if (_accounts.isEmpty) return null;
    final sorted = List<RememberedAccount>.of(_accounts)
      ..sort((a, b) => b.lastUsedAt.compareTo(a.lastUsedAt));
    return sorted.first;
  }

  RememberedAccount? accountFor(LoginScope scope) {
    for (final account in _accounts) {
      if (account.scope == scope) return account;
    }
    return null;
  }

  bool hasAccount(LoginScope scope) => accountFor(scope) != null;

  CredentialFreshness freshnessOf(RememberedAccount account) =>
      evaluateCredentialFreshness(
        lastSuccessfulLoginAtMs: account.lastSuccessfulLoginAt,
        now: _clock(),
        validity: _validity,
      );

  /// Reads the non-secret half from disk. Safe to call repeatedly.
  Future<void> ensureLoaded() {
    return _loading ??= _load();
  }

  Future<void> _load() async {
    final prefs = await _loadPreferences();
    _prefs = prefs;

    final raw = prefs.getString(prefsKey);
    if (raw == null || raw.isEmpty) {
      _accounts = <RememberedAccount>[];
      return;
    }

    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) {
        _accounts = <RememberedAccount>[];
        return;
      }
      final list = decoded['accounts'];
      if (list is! List) {
        _accounts = <RememberedAccount>[];
        return;
      }
      _accounts = list
          .whereType<Map<dynamic, dynamic>>()
          .map((entry) => RememberedAccount.fromJson(
                entry.cast<String, dynamic>(),
              ))
          .where((account) => account.hasCompleteIdentity)
          .toList();
    } on FormatException {
      // Corrupt preference blob: start clean instead of crashing the app.
      // Passwords are unaffected - they are not in this document.
      _accounts = <RememberedAccount>[];
    }
  }

  Future<void> _persist() async {
    final prefs = _prefs ??= await _loadPreferences();
    await prefs.setString(
      prefsKey,
      jsonEncode(<String, dynamic>{
        'version': 1,
        'accounts': _accounts.map((account) => account.toJson()).toList(),
      }),
    );
  }

  void _upsert(RememberedAccount account) {
    final index =
        _accounts.indexWhere((candidate) => candidate.scope == account.scope);
    if (index == -1) {
      _accounts = <RememberedAccount>[..._accounts, account];
    } else {
      _accounts = <RememberedAccount>[..._accounts]..[index] = account;
    }
  }

  /// Records/refreshes the account identity and the "记住登录" choice.
  ///
  /// Contains no secret, so it is safe on plain preferences; the caller is
  /// expected to have authenticated successfully first.
  Future<RememberedAccount> rememberAccount(
    LoginScope scope, {
    required bool rememberLogin,
    DateTime? at,
  }) async {
    await ensureLoaded();
    final now = at ?? _clock();
    final existing = accountFor(scope);
    final account = (existing ?? RememberedAccount(
              baseUrl: scope.baseUrl,
              database: scope.database,
              login: scope.login,
              rememberLogin: rememberLogin,
            ))
        .copyWith(
      baseUrl: scope.baseUrl,
      database: scope.database,
      login: scope.login,
      rememberLogin: rememberLogin,
      lastUsedAt: now.millisecondsSinceEpoch,
    );
    _upsert(account);
    await _persist();
    return account;
  }

  /// Stamps a server-accepted authentication.
  ///
  /// MUST only be called after `authenticate()` returned a uid. Startup,
  /// failures and network errors must never reach this method - that is the
  /// difference between a real 10-day window and one that renews itself.
  Future<void> markSuccessfulLogin(LoginScope scope, {required DateTime at}) async {
    await ensureLoaded();
    final existing = accountFor(scope);
    if (existing == null) return;
    _upsert(existing.copyWith(
      lastSuccessfulLoginAt: at.millisecondsSinceEpoch,
      lastUsedAt: at.millisecondsSinceEpoch,
      autoLoginBlocked: false,
    ));
    await _persist();
  }

  /// Persists the operator's "记住登录" choice for a known account.
  ///
  /// Returns `false` when this (server, database, user) was never used, in
  /// which case there is nothing on disk to update yet.
  Future<bool> setRememberLogin(LoginScope scope, bool value) async {
    await ensureLoaded();
    final existing = accountFor(scope);
    if (existing == null) return false;
    _upsert(existing.copyWith(rememberLogin: value));
    await _persist();
    return true;
  }

  /// Sign-out sets this; the next successful login clears it.
  Future<bool> setAutoLoginBlocked(LoginScope scope, bool value) async {
    await ensureLoaded();
    final existing = accountFor(scope);
    if (existing == null) return false;
    _upsert(existing.copyWith(autoLoginBlocked: value));
    await _persist();
    return true;
  }

  /// Writes the password into the platform key store.
  ///
  /// Throws [SecretStorageUnavailableException] when the machine has no usable
  /// key store (headless Linux without libsecret/gnome-keyring is the realistic
  /// case). The caller keeps the login valid and tells the operator.
  Future<void> savePassword(LoginScope scope, String password) async {
    try {
      await _backend.write(scope.secretKey, password);
      _storageStatus = SecureStorageStatus.available;
      _storageMessage = null;
    } on SecretStorageUnavailableException catch (e) {
      _storageStatus = SecureStorageStatus.unavailable;
      _storageMessage = e.message;
      rethrow;
    }
  }

  /// Reads the stored password, or `null` when this exact account has none.
  ///
  /// Throws [SecretStorageUnavailableException] when the key store cannot be
  /// reached - a caller must then ask for the password instead of guessing.
  Future<String?> readPassword(LoginScope scope) async {
    try {
      final value = await _backend.read(scope.secretKey);
      _storageStatus = SecureStorageStatus.available;
      _storageMessage = null;
      return (value == null || value.isEmpty) ? null : value;
    } on SecretStorageUnavailableException catch (e) {
      _storageStatus = SecureStorageStatus.unavailable;
      _storageMessage = e.message;
      rethrow;
    }
  }

  Future<bool> hasPassword(LoginScope scope) async =>
      (await readPassword(scope)) != null;

  /// Deletes the password for exactly one (server, database, user).
  ///
  /// Never throws: an unreachable key store has nothing stored that this call
  /// could leave behind, so a failure is recorded and ignored.
  Future<void> deletePassword(LoginScope scope) async {
    try {
      await _backend.delete(scope.secretKey);
    } on SecretStorageUnavailableException catch (e) {
      _storageStatus = SecureStorageStatus.unavailable;
      _storageMessage = e.message;
    }
  }

  /// Drops one account and its secret.
  Future<void> forgetAccount(LoginScope scope) async {
    await ensureLoaded();
    await deletePassword(scope);
    _accounts = _accounts
        .where((account) => account.scope != scope)
        .toList(growable: false);
    await _persist();
  }

  /// Drops every remembered account and every stored secret.
  Future<void> forgetAll() async {
    await ensureLoaded();
    for (final account in _accounts) {
      await deletePassword(account.scope);
    }
    _accounts = <RememberedAccount>[];
    final prefs = _prefs ??= await _loadPreferences();
    await prefs.remove(prefsKey);
  }
}
