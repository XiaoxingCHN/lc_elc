import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../providers/auth_provider.dart';
import '../../../services/lab_api_client.dart';
import '../models/session_scope.dart';
import '../services/asset_cache.dart';
import '../services/pdf_output.dart';
import '../services/scan_sources.dart';

/// The raw inputs of the session scope, read from the auth layer.
///
/// Kept as a separate provider so a test (or the auth worker) can override the
/// scope source without touching the login feature.
final sessionScopeSourceProvider = Provider<LabSessionScope>((ref) {
  final auth = ref.watch(authProvider);
  return LabSessionScope(
    baseUrl: auth.baseUrl ?? '',
    database: auth.database ?? '',
    uid: auth.uid,
  );
});

/// Active company context of the session.
///
/// Odoo users can belong to several companies and the stock/history differ per
/// company, so the cache scope must include it. The login flow does not learn it,
/// so it defaults to `''` (single company / unknown) and can be published by
/// whoever discovers it - the auth layer, or a screen reading the bootstrap
/// permissions.
final companyScopeProvider = StateProvider<String>((ref) => '');

/// The full scope every business provider depends on:
/// `(server, database, uid, company)`.
///
/// Every provider that reads or writes business data watches THIS value, so a
/// change (different server with the same uid, a different account, a company
/// switch, a sign-out) rebuilds the API client, rotates request tokens, drops the
/// previous list/detail/bootstrap/form state and switches the cache directory.
final effectiveSessionScopeProvider = Provider<LabSessionScope>((ref) {
  final base = ref.watch(sessionScopeSourceProvider);
  return base.withCompany(ref.watch(companyScopeProvider));
});

/// Typed business API, bound to the ONE authenticated [OdooClient].
///
/// It watches the FULL session scope, not just the uid: pointing the same client
/// at another server or database (same uid) must produce a different client
/// instance here, otherwise a stale scope could keep using the old business
/// state.
final labApiProvider = Provider<LabApiClient>((ref) {
  ref.watch(effectiveSessionScopeProvider);
  final client = ref.watch(odooClientProvider);
  return LabApiClient(call: client.callRoute);
});

/// Authenticated Odoo user id, or `null` while signed out.
///
/// Used to identify the operator's OWN borrower account and to separate the
/// actor (server-recorded) from the borrower (selected account).
final currentUidProvider = Provider<int?>((ref) {
  return ref.watch(effectiveSessionScopeProvider).uid;
});

/// Inventory/catalog revision of the data on screen.
///
/// Every successful write returns the new `inventory_revision`. Bumping this
/// value makes the unified list, the open detail and the history re-query, so the
/// UI can never keep showing a stale quantity after a receipt / issue / return.
/// The sequence counter makes the bump effective even when the server echoes the
/// same revision string.
///
/// The provider itself watches the session scope, so switching server / account
/// starts from a clean revision instead of carrying the previous session's.
class DataRevision {
  const DataRevision({this.inventory = '', this.catalog = '', this.sequence = 0});

  final String inventory;
  final String catalog;
  final int sequence;

  @override
  String toString() =>
      'DataRevision(inventory: $inventory, catalog: $catalog, seq: $sequence)';
}

class DataRevisionNotifier extends StateNotifier<DataRevision> {
  DataRevisionNotifier() : super(const DataRevision());

  /// Records a revision from the server and notifies every dependent provider.
  void bump({String? inventory, String? catalog}) {
    state = DataRevision(
      inventory: inventory ?? state.inventory,
      catalog: catalog ?? state.catalog,
      sequence: state.sequence + 1,
    );
  }
}

final dataRevisionProvider =
    StateNotifierProvider<DataRevisionNotifier, DataRevision>((ref) {
  // Recreated (and therefore reset) when the session scope changes.
  ref.watch(effectiveSessionScopeProvider);
  return DataRevisionNotifier();
});

/// Idempotency-key factory. Injectable so a test can pin the key and assert that
/// a retry reuses it.
final requestKeyFactoryProvider = Provider<String Function()>(
  (ref) => newRequestKey,
);

/// Where the file cache lives. Overridden in tests with a temporary directory.
final assetCacheDirectoryProvider = Provider<Future<Directory> Function()>(
  (ref) => defaultAssetCacheDirectory,
);

/// Fetches a same-origin asset WITH the authenticated Odoo session.
///
/// `/lab/api/asset/...` style references are only readable with `session_id`.
/// The auth layer owns the cookie jar, so it supplies this fetcher (one override
/// in `main.dart`):
///
/// ```dart
/// assetAuthenticatedFetcherProvider.overrideWithValue(client.fetchAssetBytes)
/// ```
///
/// Default `null`: such a reference is then fetched ANONYMOUSLY from the same
/// origin (harmless - no credential is sent, and a public route still works) or
/// falls back to the public original URL. An external CDN is ALWAYS fetched
/// without cookies, whatever this returns.
final assetAuthenticatedFetcherProvider = Provider<AuthenticatedAssetFetcher?>(
  (ref) => null,
);

/// The Odoo server URI of the CURRENT scope, used to resolve
/// `/lab/api/asset/...` references.
final odooBaseUriProvider = Provider<Uri?>((ref) {
  final baseUrl = ref.watch(effectiveSessionScopeProvider).baseUrl;
  final fallback = ref.watch(odooClientProvider).baseUrl;
  final text = baseUrl.trim().isEmpty ? fallback.trim() : baseUrl.trim();
  if (text.isEmpty) return null;
  return Uri.tryParse(text);
});

/// File-backed cache for captured images and manuals, plus the offline detail
/// metadata of viewed items.
///
/// [AssetCacheStore.scopeKey] isolates BUSINESS-carrying artifacts:
///   * same-origin (session-authenticated) files live under `<scopeKey>/`;
///   * public CDN files are shared, because they carry no account data;
///   * offline detail metadata lives under `<scopeKey>/details/`.
///
/// The store is rebuilt when the scope changes, so a new operator can never read
/// the previous operator's files.
final assetCacheProvider = Provider<AssetCacheStore>((ref) {
  final scope = ref.watch(effectiveSessionScopeProvider);
  return AssetCacheStore(
    resolveDirectory: ref.watch(assetCacheDirectoryProvider),
    scopeKey: scope.key,
    // Signed out => a hash exists but there is no session: nothing business-
    // carrying may be written or read.
    persistBusinessData: scope.canPersistBusinessData,
    authenticatedFetcher: ref.watch(assetAuthenticatedFetcherProvider),
    baseUriResolver: () async => ref.read(odooBaseUriProvider),
  );
});

/// Real PDF output (save / system print / share).
final pdfOutputProvider = Provider<PdfOutputService>((ref) => PdfOutputService());

/// Which scan input devices this platform offers.
///
/// Consulted by the UI so Windows/Linux show the keyboard + paste path only, and
/// Android additionally offers the camera. No platform ever renders a control
/// that exists only to report "not supported".
final scannerCapabilitiesProvider = Provider<ScannerCapabilities>(
  (ref) => detectScannerCapabilities(),
);
