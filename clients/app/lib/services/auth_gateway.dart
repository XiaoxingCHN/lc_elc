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

  /// Authenticates against [baseUrl]/[database] and commits ONLY on success.
  ///
  /// Used by the atomic server switch: the live session (uid + cookie jar) is
  /// left untouched while the new server is being contacted, so a rejection or
  /// a network failure keeps the operator signed in on the old server.
  ///
  /// The default implementation is the non-atomic
  /// [configure] + [authenticate] pair; [OdooClient] overrides it with a
  /// temporary session.
  Future<int> authenticateAt({
    required String baseUrl,
    required String database,
    required String login,
    required String password,
  }) async {
    configure(baseUrl: baseUrl, database: database);
    return authenticate(login, password);
  }

  /// Checks credentials WITHOUT touching the live session.
  ///
  /// "测试连接" uses this. The default implementation is the atomic
  /// [authenticateAt] (which already leaves the live session alone on failure);
  /// [OdooClient] implements it on a throw-away client so a SUCCESSFUL probe
  /// also leaves the live session untouched.
  Future<int> probe({
    required String baseUrl,
    required String database,
    required String login,
    required String password,
  }) =>
      authenticateAt(
        baseUrl: baseUrl,
        database: database,
        login: login,
        password: password,
      );

  /// Cancels every request issued under the current session.
  ///
  /// Called before switching servers so an answer to an old request cannot be
  /// mistaken for a failure of the new session. The default is a no-op.
  void cancelInFlightRequests() {}

  /// Destroys the server-side session (may fail; local state is cleared).
  Future<void> logout();

  /// Drops the in-memory session (uid + cookie jar) WITHOUT any request.
  ///
  /// Used when a stored credential is judged stale: a stale password must not
  /// leave a usable session behind, and no network call may be made on that
  /// path.
  void resetLocalSession();

  /// Monotonic id of the live session. It changes whenever the gateway is
  /// repointed at another server/database or its session is dropped.
  ///
  /// The auth layer records it after a successful sign-in/switch so a late
  /// answer from the PREVIOUS session (e.g. a 401 that was already in flight)
  /// cannot tear down the new one.
  int get sessionGeneration;

  /// Handler invoked when the server reports that the session cookie is no
  /// longer valid (HTTP 401 or an Odoo session-expired error).
  ///
  /// Purely a notification: the auth layer switches the app back to the login
  /// screen. Nothing may start an automatic sign-in from here, or a dead
  /// session would turn into an endless login loop. The auth layer compares
  /// [sessionGeneration] with the generation it recorded after sign-in and
  /// ignores a notification that belongs to an older session.
  set onSessionInvalid(void Function()? handler);
}
