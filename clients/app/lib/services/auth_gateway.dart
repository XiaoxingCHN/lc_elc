/// The three things the login flow needs from an Odoo session.
///
/// [OdooClient] implements this directly, so production is unchanged; tests
/// substitute a recording fake instead of reaching a real server (this client
/// must never authenticate against the laboratory server from a test run).
abstract class AuthGateway {
  /// Server this gateway currently points at (display/diagnostics only).
  String get baseUrl;

  /// Database this gateway currently points at (display only).
  String get database;

  /// Odoo user id of the live session, or `null` when signed out.
  int? get uid;

  /// True while a session is established.
  bool get isAuthenticated;

  /// Repoints the client at a server/database and forgets the old session.
  void configure({required String baseUrl, required String database});

  /// Posts credentials to `/web/session/authenticate`.
  ///
  /// Returns the Odoo uid. Throws on rejection, timeout or transport failure.
  Future<int> authenticate(String login, String password);

  /// Destroys the server-side session (may fail; local state is cleared).
  Future<void> logout();

  /// Drops the in-memory session (uid + cookie jar) WITHOUT any request.
  ///
  /// Used when a stored credential is judged stale: a stale password must not
  /// leave a usable session behind, and no network call may be made on that
  /// path.
  void resetLocalSession();

  /// Handler invoked when the server reports that the session cookie is no
  /// longer valid (HTTP 401 or an Odoo session-expired error).
  ///
  /// Purely a notification: the auth layer switches the app back to the login
  /// screen. Nothing may start an automatic sign-in from here, or a dead
  /// session would turn into an endless login loop.
  set onSessionInvalid(void Function()? handler);
}
