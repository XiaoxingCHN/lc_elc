/// Odoo connection defaults and endpoint paths.
///
/// SECURITY CONTRACT - read before editing:
///   * This file must never contain a default password, a service-account
///     password, or an API key. Credentials are typed by the operator on the
///     login screen.
///   * The password is never written to a plain file. When the operator picks
///     "记住登录" it is handed to the platform key store through
///     `flutter_secure_storage` (Windows DPAPI, Android Keystore, Linux
///     libsecret) - see lib/services/secret_backend.dart.
///   * The server URL and database name may be supplied at build time with
///     `--dart-define`, or typed at runtime on the login screen. Runtime input
///     always wins over the build-time default.
///
/// Build-time example:
///   flutter build windows --release \
///     --dart-define=LAB_ODOO_URL=http://192.168.31.105:8069 \
///     --dart-define=LAB_ODOO_DB=LcHardwareHouse \
///     --dart-define=LAB_ODOO_USER=<odoo-login>
class OdooConfig {
  const OdooConfig._();

  /// Build-time default server URL. Empty string means "ask the operator".
  static const String defaultBaseUrl =
      String.fromEnvironment('LAB_ODOO_URL', defaultValue: '');

  /// Build-time default database name. Empty string means "ask the operator".
  static const String defaultDatabase =
      String.fromEnvironment('LAB_ODOO_DB', defaultValue: '');

  /// Build-time default login name. Not a secret, so pre-filling it is safe;
  /// it stays editable on the login screen. Empty string means "ask".
  static const String defaultLogin =
      String.fromEnvironment('LAB_ODOO_USER', defaultValue: '');

  /// RPC entry point used for every ORM call.
  ///
  /// This is the endpoint Odoo's own web client posts to. It is authorised by
  /// the `session_id` cookie established through [authPath], so no password
  /// has to be repeated per call - unlike the `/jsonrpc` + `execute_kw` form,
  /// whose third positional argument is the account password.
  static const String callKwPath = '/web/dataset/call_kw';

  /// Web session authentication endpoint.
  static const String authPath = '/web/session/authenticate';

  /// Web session destroy endpoint.
  static const String sessionDestroyPath = '/web/session/destroy';

  /// Connect timeout, in seconds.
  static const int requestTimeout = 10;

  /// RPC call timeout, in seconds.
  static const int rpcTimeout = 30;

  /// Trims whitespace and strips trailing slashes from operator input.
  static String normalizeBaseUrl(String raw) {
    var value = raw.trim();
    while (value.endsWith('/')) {
      value = value.substring(0, value.length - 1);
    }
    return value;
  }

  /// True when [raw] looks like an http(s) base URL.
  static bool isValidBaseUrl(String raw) {
    final value = normalizeBaseUrl(raw);
    return value.startsWith('http://') || value.startsWith('https://');
  }

  // ---------------------------------------------------------------------------
  // "Remember login" policy
  // ---------------------------------------------------------------------------

  /// How long a password that the server has ACCEPTED stays usable for
  /// automatic sign-in.
  ///
  /// Measured on the device's local clock from the last successful server
  /// authentication. At `now - last >= rememberLoginValidity` the stored
  /// password is deleted and the operator types it again; the server address,
  /// database and user name are kept either way.
  ///
  /// Overridable for manual QA only, so the 10-day path can be exercised
  /// without waiting ten days:
  ///   flutter build windows --release --dart-define=LAB_REMEMBER_LOGIN_SECONDS=60
  static const Duration rememberLoginValidity = Duration(
    seconds: int.fromEnvironment(
      'LAB_REMEMBER_LOGIN_SECONDS',
      defaultValue: 10 * 24 * 60 * 60,
    ),
  );

  /// Default state of the single "记住登录" switch on a first-ever login.
  ///
  /// The operator still has to submit the form with the switch visible, and
  /// nothing is persisted before the server accepts the password. Flipping
  /// this to `false` only changes the initial position of the switch.
  static const bool rememberLoginDefault = true;

  /// Key prefix for the one secret in the platform key store (the password).
  /// The rest of the key is a sha256 of (server, database, user), so one
  /// account can never read another account's password.
  static const String secureStorageKeyPrefix = 'lc_elc.login.v1';
}
