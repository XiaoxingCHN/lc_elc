import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/lab_api_exception.dart';
import '../../../services/lab_api_client.dart';
import '../models/detail_models.dart';
import '../models/catalog_query.dart';
import '../models/identity.dart';
import '../models/unified_item.dart';
import 'cache_writer_providers.dart';
import 'lab_errors.dart';
import 'unified_providers.dart';

/// State of the ONE unified list.
class CatalogState {
  const CatalogState({
    this.query = const CatalogQuery(),
    this.items = const <UnifiedItem>[],
    this.nextCursor,
    this.total = 0,
    this.loading = false,
    this.loadingMore = false,
    this.error,
    this.errorCode,
    this.inventoryRevision = '',
    this.catalogRevision = '',
  });

  final CatalogQuery query;
  final List<UnifiedItem> items;

  /// Opaque keyset cursor of the next page (`null` = no more pages).
  final String? nextCursor;

  /// Total matching rows in the whole captured library.
  final int total;

  /// True while the FIRST page is being fetched (the list shows a spinner).
  final bool loading;

  /// True while an additional page is being appended.
  final bool loadingMore;

  /// Actionable Chinese failure text. An error is never shown as "no results".
  final String? error;
  final String? errorCode;

  final String inventoryRevision;
  final String catalogRevision;

  bool get hasMore => nextCursor != null && nextCursor!.isNotEmpty;

  /// True only when the server really answered with zero rows and no error.
  bool get isEmpty => items.isEmpty && !loading && error == null;

  bool get hasError => error != null;

  int get loadedCount => items.length;

  CatalogState copyWith({
    CatalogQuery? query,
    List<UnifiedItem>? items,
    Object? nextCursor = _unset,
    int? total,
    bool? loading,
    bool? loadingMore,
    Object? error = _unset,
    Object? errorCode = _unset,
    String? inventoryRevision,
    String? catalogRevision,
  }) {
    return CatalogState(
      query: query ?? this.query,
      items: items ?? this.items,
      nextCursor:
          identical(nextCursor, _unset) ? this.nextCursor : nextCursor as String?,
      total: total ?? this.total,
      loading: loading ?? this.loading,
      loadingMore: loadingMore ?? this.loadingMore,
      error: identical(error, _unset) ? this.error : error as String?,
      errorCode: identical(errorCode, _unset) ? this.errorCode : errorCode as String?,
      inventoryRevision: inventoryRevision ?? this.inventoryRevision,
      catalogRevision: catalogRevision ?? this.catalogRevision,
    );
  }

  static const Object _unset = Object();
}

/// Drives the unified list: filters, server paging, merge protection, refresh.
///
/// Rules that are deliberately enforced here (and pinned by
/// `test/features/unified/catalog_paging_test.dart`):
///
///   * only the SERVER decides what matches and in which order - the client
///     never filters or re-sorts a page, and never asks for `limit: 1000`;
///   * paging is the opaque `cursor`; a page is appended in the order received;
///   * rows are de-duplicated by canonical identity, so the SAME C code can
///     never appear as two cards (a page boundary that repeats a row collapses);
///   * a row whose identity could not be derived is NEVER merged - each such
///     server row stays its own card;
///   * changing the query while a request is in flight discards the stale
///     response instead of appending it to the new result set;
///   * a failure becomes an error state with the server's Chinese message. It is
///     never converted into an empty list.
class CatalogNotifier extends StateNotifier<CatalogState> {
  CatalogNotifier({
    required LabApiClient api,
    int pageSize = LabApiClient.defaultPageSize,
    CatalogQuery initialQuery = const CatalogQuery(),
    void Function(List<UnifiedItem> items)? onPageLoaded,
  })  : _api = api,
        _pageSize = pageSize.clamp(1, LabApiClient.maxPageSize),
        _onPageLoaded = onPageLoaded,
        super(CatalogState(query: initialQuery));

  final LabApiClient _api;
  final int _pageSize;

  /// Called with every page the server returned, so the PUBLIC catalog metadata
  /// of what the operator actually looked at can be cached for offline browsing.
  final void Function(List<UnifiedItem> items)? _onPageLoaded;

  /// Guards against a stale response overwriting a newer query's results.
  int _requestToken = 0;

  /// Identity of the rows already on screen (merge protection).
  final Set<String> _seenKeys = <String>{};

  int get pageSize => _pageSize;

  /// Replaces the query and loads the first page (the list resets).
  Future<void> updateQuery(CatalogQuery query) {
    _requestToken++;
    _seenKeys.clear();
    state = state.copyWith(
      query: query,
      items: const <UnifiedItem>[],
      nextCursor: null,
      total: 0,
      loading: true,
      loadingMore: false,
      error: null,
      errorCode: null,
    );
    return _loadFirstPage(_requestToken);
  }

  /// Reloads the first page of the current query (used after a write).
  Future<void> refresh() {
    _requestToken++;
    _seenKeys.clear();
    state = state.copyWith(
      items: const <UnifiedItem>[],
      nextCursor: null,
      loading: true,
      loadingMore: false,
      error: null,
      errorCode: null,
    );
    return _loadFirstPage(_requestToken);
  }

  /// Appends the next page (no-op while a request is running or at the end).
  Future<void> loadMore() async {
    if (state.loading || state.loadingMore || !state.hasMore) return;
    final token = _requestToken;
    final cursor = state.nextCursor;
    state = state.copyWith(loadingMore: true, error: null);
    try {
      final page = await _api.search(state.query, cursor: cursor, limit: _pageSize);
      if (token != _requestToken) return;
      _onPageLoaded?.call(page.items);
      state = state.copyWith(
        items: _append(state.items, page.items),
        nextCursor: page.nextCursor,
        total: page.total > 0 ? page.total : state.total,
        loading: false,
        loadingMore: false,
        inventoryRevision: page.inventoryRevision,
        catalogRevision: page.catalogRevision,
      );
    } on LabApiException catch (error) {
      if (token != _requestToken) return;
      state = state.copyWith(loadingMore: false, error: error.message, errorCode: error.code);
    } catch (error) {
      if (token != _requestToken) return;
      state = state.copyWith(loadingMore: false, error: '$error');
    }
  }

  Future<void> _loadFirstPage(int token) async {
    try {
      final page = await _api.search(state.query, limit: _pageSize);
      if (token != _requestToken) return;
      _onPageLoaded?.call(page.items);
      state = state.copyWith(
        items: _append(const <UnifiedItem>[], page.items),
        nextCursor: page.nextCursor,
        total: page.total,
        loading: false,
        loadingMore: false,
        error: null,
        errorCode: null,
        inventoryRevision: page.inventoryRevision,
        catalogRevision: page.catalogRevision,
      );
    } on LabApiException catch (error) {
      if (token != _requestToken) return;
      state = state.copyWith(
        loading: false,
        loadingMore: false,
        error: error.message,
        errorCode: error.code,
      );
    } catch (error) {
      if (token != _requestToken) return;
      state = state.copyWith(
        loading: false,
        loadingMore: false,
        error: '$error',
      );
    }
  }

  /// De-duplicates by canonical identity while preserving server order.
  List<UnifiedItem> _append(List<UnifiedItem> existing, List<UnifiedItem> incoming) {
    final result = List<UnifiedItem>.of(existing);
    for (final item in incoming) {
      // A row with no usable identity is kept as its own card: merging two
      // unidentified rows could hide a real component.
      if (identityKindOf(item.itemKey) == IdentityKind.unknown) {
        result.add(item);
        continue;
      }
      if (_seenKeys.add(item.itemKey)) {
        result.add(item);
      }
    }
    return result;
  }
}

/// The unified list, wired to the authenticated API and auto-refreshed after a
/// successful stock write.
final catalogProvider = StateNotifierProvider<CatalogNotifier, CatalogState>((ref) {
  // Session isolation: switching server / database / account / company rebuilds
  // this notifier, dropping the previous session's rows, cursor and filters.
  ref.watch(effectiveSessionScopeProvider);
  final api = ref.watch(labApiProvider);
  final cacheWriter = ref.watch(catalogCacheWriterProvider);
  final notifier = CatalogNotifier(
    api: api,
    // Cache the PUBLIC part of what was actually looked at, so a later cold start
    // can offer the offline library (business fields are stripped by the store).
    // Fire-and-forget through the writer seam: no disk I/O on the UI path.
    onPageLoaded: cacheWriter.savePublicPage,
  );

  ref.listen<DataRevision>(dataRevisionProvider, (previous, next) {
    if (previous?.sequence == next.sequence) return;
    unawaited(notifier.refresh());
  });

  return notifier;
});
/// Query currently applied to the unified list (for the filter UI).
final catalogQueryProvider = Provider<CatalogQuery>((ref) {
  return ref.watch(catalogProvider.select((state) => state.query));
});

/// Category navigation tree. Fetched once, refreshed on demand.
final catalogCategoriesProvider =
    FutureProvider<List<CatalogCategory>>((ref) async {
  ref.watch(effectiveSessionScopeProvider);
  final api = ref.watch(labApiProvider);
  return api.categories();
});

/// Available filter values for the CURRENT query.
///
/// Watches only the query object, so appending a page does not re-request the
/// facets.
final catalogFacetsProvider = FutureProvider<CatalogFacets>((ref) async {
  ref.watch(effectiveSessionScopeProvider);
  final query = ref.watch(catalogProvider.select((state) => state.query));
  final api = ref.watch(labApiProvider);
  return api.facets(query);
});

/// Full detail of one card, with an offline fallback.
///
/// Online path: the live `/lab/api/catalog/detail` payload is fetched AND saved
/// to the local metadata cache, so a later offline open still shows the
/// parameters and the manual list (caching the file bytes alone would leave a
/// cached manual unreachable).
///
/// Offline path: when the server cannot be reached at all, the cached payload is
/// returned with [fromCache] set, and the screen says so explicitly. A
/// permission or session failure is NOT replaced by cached content.
class CachedDetailResult {
  const CachedDetailResult({
    required this.detail,
    required this.fromCache,
    this.savedAt,
    this.offlineError,
  });

  final CatalogDetail detail;

  /// True when this is the locally cached snapshot, not live server data.
  final bool fromCache;

  final DateTime? savedAt;

  /// Why the live request failed (shown next to the offline banner).
  final String? offlineError;
}

final catalogDetailProvider =
    FutureProvider.autoDispose.family<CachedDetailResult, String>((ref, itemKey) async {
  ref.watch(dataRevisionProvider);
  // Offline snapshots are stored per session scope, and a scope change must
  // re-request rather than serve the previous operator's cached detail.
  ref.watch(effectiveSessionScopeProvider);
  final api = ref.watch(labApiProvider);
  final cache = ref.watch(assetCacheProvider);

  try {
    final data = await api.detailJson(itemKey);
    // Persistence goes through the writer seam and is never awaited: showing the
    // detail must not wait on disk I/O, and a cache failure must not fail the
    // screen (a widget test overrides the writer, so no file I/O happens there).
    ref.read(catalogCacheWriterProvider).saveDetail(itemKey, data);
    return CachedDetailResult(
      detail: CatalogDetail.fromJson(data),
      fromCache: false,
    );
  } catch (error) {
    if (!isOfflineFailure(error)) rethrow;
    final cached = await cache.readDetail(itemKey);
    if (cached == null) rethrow;
    return CachedDetailResult(
      detail: CatalogDetail.fromJson(cached.data),
      fromCache: true,
      savedAt: cached.savedAt,
      offlineError: describeLabError(error),
    );
  }
});

/// The list row matching [itemKey], when the operator arrived from the list.
///
/// Lets the detail screen paint the card instantly while the detail request is
/// still in flight; it is never used as a substitute for server data.
final catalogRowProvider = Provider.family<UnifiedItem?, String>((ref, itemKey) {
  final items = ref.watch(catalogProvider.select((state) => state.items));
  for (final item in items) {
    if (item.itemKey == itemKey) return item;
  }
  return null;
});
