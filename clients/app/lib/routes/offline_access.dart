/// Read-only OFFLINE access to already-cached public catalog data.
///
/// This is the auth/router owner's side of the offline feature; the UI owner
/// implements the index, the read-only list/detail and file opening. The whole
/// contract is written down in `lc_elc/docs/离线只读入口整合说明.md`.
///
/// POLICY - what the unauthenticated offline mode is and is not:
///   * it is the SAME unified library in read-only form; there is no second,
///     offline catalogue;
///   * it never pretends to be a server session: [AuthState.isAuthenticated]
///     stays false, `sessionIdentity` stays null, no cookie jar is used, the
///     10-day `lastSuccessfulLoginAt` is NOT refreshed and no secret is written;
///   * only these routes may be opened while signed out, and only with the
///     explicit `offline=1` flag:
///       /catalog?offline=1            (list)
///       /catalog/item?offline=1&...   (detail, incl. opening cached files)
///   * every write route (/receipt, /issue, /return, /labels) and every other
///     path keeps requiring a real sign-in, so an unauthenticated session can
///     never issue, return, print labels or bind anything;
///   * a 401 / ACL answer never turns into offline access by itself: the operator
///     reaches this mode only by choosing the login-screen entry.
class OfflineAccess {
  const OfflineAccess._();

  /// Query parameter that switches a read-only route into offline mode.
  static const String flag = 'offline';

  /// Value that enables it. Absent or anything else means "live mode".
  static const String flagOn = '1';

  /// The unified library list.
  static const String catalog = '/catalog';

  /// One card's detail (parameters, images, cached manuals).
  static const String itemDetail = '/catalog/item';

  /// Routes that may render cached public data without a session.
  static const Set<String> readOnlyPaths = <String>{catalog, itemDetail};

  /// True when the operator explicitly asked for the offline read-only view.
  ///
  /// Accepts the two spellings the UI recognises (`UnifiedRoutes.isOffline`):
  /// every link this app generates uses `offline=1`, but a hand-typed or
  /// deep-linked `offline=true` must not bounce back to the login form after
  /// the catalog screen already treated it as offline mode.
  static bool isRequested(Map<String, String> queryParameters) {
    final value = queryParameters[flag];
    return value == flagOn || value == 'true';
  }

  /// True when [path] may be shown while signed out.
  static bool allows(String path, Map<String, String> queryParameters) =>
      isRequested(queryParameters) && readOnlyPaths.contains(path);

  /// Location of the offline list.
  static String catalogLocation() =>
      Uri(path: catalog, queryParameters: <String, String>{flag: flagOn})
          .toString();

  /// Location of one cached card in offline mode.
  static String itemLocation(String itemKey) => Uri(
        path: itemDetail,
        queryParameters: <String, String>{
          flag: flagOn,
          'item_key': itemKey,
        },
      ).toString();
}
