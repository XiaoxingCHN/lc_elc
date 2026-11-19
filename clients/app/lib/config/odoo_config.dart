import '../models/odoo_exception.dart';

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

  /// The public server every build defaults to. A build may still override it
  /// with `--dart-define=LAB_ODOO_URL=...`.
  static const String publicBaseUrl = 'https://team.l-creation.club';

  /// Database used by the public and LAN deployments.
  static const String publicDatabase = 'LcHardwareHouse';

  /// Build-time LAN acceleration address (`--dart-define=LAB_LAN_URL=...`).
  ///
  /// Kept empty by default: the operator fills the current LAN address in
  /// "服务器与内网加速", where it lives in memory only.
  static const String buildLanBaseUrl =
      String.fromEnvironment('LAB_LAN_URL', defaultValue: '');

  /// In-memory LAN address entered in the settings sheet. NEVER persisted.
  static String? _runtimeLanBaseUrl;

  static String? get runtimeLanBaseUrl => _runtimeLanBaseUrl;

  /// Records the LAN address for THIS process only. Passing null/empty clears
  /// it (logout, application exit).
  ///
  /// Only a private-network HTTP(S) host is accepted: this value widens the
  /// cleartext whitelist, so a public hostname must never be able to enter it.
  static void setRuntimeLanBaseUrl(String? value) {
    final normalized = normalizeBaseUrl(value ?? '');
    if (normalized.isEmpty) {
      _runtimeLanBaseUrl = null;
      return;
    }
    final host = Uri.tryParse(normalized)?.host ?? '';
    _runtimeLanBaseUrl = isPrivateNetworkHost(host) ? normalized : null;
  }

  /// The server the login form pre-fills when nothing has been remembered.
  static String get fallbackBaseUrl =>
      defaultBaseUrl.trim().isNotEmpty ? defaultBaseUrl : publicBaseUrl;

  /// The database the login form pre-fills when nothing has been remembered.
  static String get fallbackDatabase =>
      defaultDatabase.trim().isNotEmpty ? defaultDatabase : publicDatabase;

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
  // Cleartext (HTTP) policy for the LAN acceleration path
  // ---------------------------------------------------------------------------
  //
  // HTTPS is always allowed. Plain HTTP is allowed ONLY for an intranet host
  // that is either:
  //   * the build-time LAN address (`--dart-define=LAB_LAN_URL=...`),
  //   * the LAN address the operator entered in "服务器与内网加速" for this
  //     process, or
  //   * the historical laboratory address 192.168.31.105 (kept for existing
  //     installations; see the Android network security config).
  //
  // The host must also be a private/loopback address. A public hostname over
  // HTTP is always refused, so this never becomes "any HTTP is fine".

  /// The historical LAN host kept for existing installations.
  static const String legacyLanHost = '192.168.31.105';

  /// True when [host] is an RFC1918 / loopback / mDNS name.
  static bool isPrivateNetworkHost(String host) {
    final value = host.trim().toLowerCase();
    if (value.isEmpty) return false;
    if (value == 'localhost' || value == '::1' || value == '[::1]') return true;
    if (value.endsWith('.local')) return true;

    final parts = value.split('.');
    if (parts.length != 4) return false;
    final octets = <int>[];
    for (final part in parts) {
      final number = int.tryParse(part);
      if (number == null || number < 0 || number > 255) return false;
      octets.add(number);
    }
    if (octets[0] == 10) return true;
    if (octets[0] == 127) return true;
    if (octets[0] == 192 && octets[1] == 168) return true;
    if (octets[0] == 172 && octets[1] >= 16 && octets[1] <= 31) return true;
    return false;
  }

  /// Hosts (lower-case) explicitly allowed over plain HTTP.
  ///
  /// Loopback is always included (a local dev server cannot leave the machine);
  /// every other host must be the legacy lab host, the build-time LAN address
  /// or the address the operator entered for this run.
  static Set<String> permittedCleartextHosts() {
    final hosts = <String>{legacyLanHost, '127.0.0.1', 'localhost'};
    for (final candidate in <String?>[
      buildLanBaseUrl,
      runtimeLanBaseUrl,
    ]) {
      final host = Uri.tryParse(normalizeBaseUrl(candidate ?? ''))?.host;
      if (host != null && host.isNotEmpty) hosts.add(host.toLowerCase());
    }
    return hosts;
  }

  /// True when [baseUrl] may be used with this client.
  ///
  /// HTTPS always passes. HTTP passes only for an explicit intranet host (see
  /// [permittedCleartextHosts]) that is also a private address.
  static bool isPermittedBaseUrl(String baseUrl) {
    final normalized = normalizeBaseUrl(baseUrl);
    if (!isValidBaseUrl(normalized)) return false;
    final uri = Uri.tryParse(normalized);
    if (uri == null || uri.host.isEmpty) return false;
    if (uri.scheme == 'https') return true;
    if (uri.scheme != 'http') return false;
    if (!isPrivateNetworkHost(uri.host)) return false;
    return permittedCleartextHosts().contains(uri.host.toLowerCase());
  }

  /// Refuses a cleartext address outside the intranet whitelist.
  ///
  /// Throws [OdooValidationException] with an operator-facing sentence; the
  /// caller must not silently downgrade to HTTP.
  static void ensureCleartextAllowed(String baseUrl) {
    final normalized = normalizeBaseUrl(baseUrl);
    if (isPermittedBaseUrl(normalized)) return;
    if (normalized.startsWith('http://')) {
      throw OdooValidationException(
        '不允许使用该 HTTP 地址：仅构建默认内网地址、设置中填写的当前内网地址'
        '或 $legacyLanHost 可以使用明文 HTTP。其它服务器请使用 HTTPS。',
      );
    }
    throw OdooValidationException(
      '服务器地址不合法，必须以 http:// 或 https:// 开头。',
    );
  }

  /// True when the build baked in a server address, so the login form can hide
  /// the address field and the operator only types account + password.
  ///
  /// The value still comes from `--dart-define=LAB_ODOO_URL=...`; nothing is
  /// hard-coded in source, so one build can target the LAN and another a
  /// public address without touching code.
  static bool get hasFixedServer => defaultBaseUrl.trim().isNotEmpty;

  /// Same for the database name (`--dart-define=LAB_ODOO_DB=...`).
  static bool get hasFixedDatabase => defaultDatabase.trim().isNotEmpty;

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
