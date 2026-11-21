import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/lab_api_exception.dart';
import '../../../services/lab_api_client.dart';
import '../../unified/models/catalog_query.dart';
import '../../unified/models/detail_models.dart';
import '../../unified/models/unified_item.dart';
import '../../unified/providers/lab_errors.dart';
import '../../unified/providers/unified_providers.dart';

/// The contract `code` of a failure, for [ErrorView]'s actionable hint.
String? errorCodeOf(Object error) =>
    error is LabApiException ? error.code : null;

/// Totals shown by 库存速览.
///
/// Every figure here is a NUMBER THE SERVER REPORTED, never a client-side sum
/// of one page:
///   * [itemCount] / [inStockItemCount] come from the library's own `total`
///     counters (one query with `stock_only` on and off);
///   * [locationCount] / [totalQuantity] come from the per-location aggregates
///     (`stock.quant` sums), so they match Odoo's own location report.
///
/// `totalQuantity` is deliberately the QUANT on-hand sum, not the bags' cached
/// figures: the two differ whenever a native Odoo operation (a count, a
/// transfer, a scrap) touched the stock, and the quant is the authority.
class StockOverview {
  const StockOverview({
    required this.itemCount,
    required this.inStockItemCount,
    required this.locationCount,
    required this.bagCount,
    required this.totalQuantity,
    required this.topItems,
    required this.locations,
  });

  /// Every card in the captured library (in stock or not).
  final int itemCount;

  /// Cards the server says hold lab stock right now.
  final int inStockItemCount;

  final int locationCount;

  /// Bags with a non-zero quantity, summed over every location.
  final int bagCount;

  /// Sum of `stock.quant` quantities over every internal location.
  final double totalQuantity;

  /// The first page of in-stock cards, for the "有库存器件" list.
  final List<UnifiedItem> topItems;

  /// Per-location rows, for the compact distribution strip.
  final List<LabStockLocation> locations;

  bool get isEmpty => itemCount == 0 && locationCount == 0;
}

/// 库存速览 data: two library counters + the location aggregates.
///
/// The library query is asked twice - once unfiltered (for the card count) and
/// once with `stock_only` (for the in-stock count and the list). Two cheap
/// keyset queries beat one full scan summed on the client, and the counters are
/// then the server's own numbers.
final stockOverviewProvider = FutureProvider<StockOverview>((ref) async {
  ref.watch(dataRevisionProvider);
  ref.watch(effectiveSessionScopeProvider);
  final api = ref.watch(labApiProvider);

  final results = await Future.wait<Object>(<Future<Object>>[
    api.search(const CatalogQuery(), limit: 1),
    api.search(const CatalogQuery(stockOnly: true), limit: 10),
    api.locations(withStats: true),
  ]);
  final all = results[0] as CatalogSearchPage;
  final inStock = results[1] as CatalogSearchPage;
  final locations = results[2] as List<LabStockLocation>;

  var bagCount = 0;
  var totalQuantity = 0.0;
  for (final location in locations) {
    bagCount += location.bagCount ?? 0;
    totalQuantity += location.quantity ?? 0;
  }

  return StockOverview(
    itemCount: all.total,
    inStockItemCount: inStock.total,
    locationCount: locations.length,
    bagCount: bagCount,
    totalQuantity: totalQuantity,
    topItems: inStock.items,
    locations: locations,
  );
});

/// One location's bags, paged.
class LocationBagsState {
  const LocationBagsState({
    this.bags = const <LabBag>[],
    this.nextCursor,
    this.loading = false,
    this.loadingMore = false,
    this.error,
    this.errorCode,
    this.loaded = false,
  });

  final List<LabBag> bags;
  final String? nextCursor;
  final bool loading;
  final bool loadingMore;
  final String? error;
  final String? errorCode;

  /// True once at least one page has come back, so an empty list can be
  /// distinguished from "not asked yet".
  final bool loaded;

  bool get hasMore => nextCursor != null && nextCursor!.isNotEmpty;
  bool get isEmpty => loaded && bags.isEmpty && error == null;

  LocationBagsState copyWith({
    List<LabBag>? bags,
    Object? nextCursor = _unset,
    bool? loading,
    bool? loadingMore,
    Object? error = _unset,
    Object? errorCode = _unset,
    bool? loaded,
  }) {
    return LocationBagsState(
      bags: bags ?? this.bags,
      nextCursor: identical(nextCursor, _unset)
          ? this.nextCursor
          : nextCursor as String?,
      loading: loading ?? this.loading,
      loadingMore: loadingMore ?? this.loadingMore,
      error: identical(error, _unset) ? this.error : error as String?,
      errorCode: identical(errorCode, _unset)
          ? this.errorCode
          : errorCode as String?,
      loaded: loaded ?? this.loaded,
    );
  }

  static const Object _unset = Object();
}

/// Bags of ONE location, keyset-paged by the server's `next_cursor`.
///
/// A stale page is dropped by comparing a request generation, the same guard the
/// catalog uses: switching between two locations quickly must not let the first
/// one's slower answer overwrite the second one's list.
class LocationBagsNotifier extends StateNotifier<LocationBagsState> {
  LocationBagsNotifier({
    required this.api,
    required this.locationId,
    this.pageSize = 50,
  }) : super(const LocationBagsState());

  final LabApiClient api;
  final int locationId;
  final int pageSize;

  int _generation = 0;

  Future<void> load() async {
    final generation = ++_generation;
    state = state.copyWith(loading: true, error: null, errorCode: null);
    try {
      final page = await api.bags(locationId: locationId, limit: pageSize);
      if (generation != _generation || !mounted) return;
      state = LocationBagsState(
        bags: page.bags,
        nextCursor: page.nextCursor,
        loaded: true,
      );
    } catch (error) {
      if (generation != _generation || !mounted) return;
      state = state.copyWith(
        loading: false,
        loaded: true,
        error: describeLabError(error),
        errorCode: errorCodeOf(error),
      );
    }
  }

  Future<void> loadMore() async {
    if (state.loading || state.loadingMore || !state.hasMore) return;
    final generation = _generation;
    state = state.copyWith(loadingMore: true);
    try {
      final page = await api.bags(
        locationId: locationId,
        cursor: state.nextCursor,
        limit: pageSize,
      );
      if (generation != _generation || !mounted) return;
      final seen = state.bags.map((bag) => bag.id).toSet();
      state = state.copyWith(
        bags: <LabBag>[
          ...state.bags,
          ...page.bags.where((bag) => !seen.contains(bag.id)),
        ],
        nextCursor: page.nextCursor,
        loadingMore: false,
      );
    } catch (error) {
      if (generation != _generation || !mounted) return;
      state = state.copyWith(
        loadingMore: false,
        error: describeLabError(error),
        errorCode: errorCodeOf(error),
      );
    }
  }

  Future<void> refresh() => load();
}

final locationBagsProvider = StateNotifierProvider.autoDispose
    .family<LocationBagsNotifier, LocationBagsState, int>((ref, locationId) {
  ref.watch(effectiveSessionScopeProvider);
  final notifier = LocationBagsNotifier(
    api: ref.watch(labApiProvider),
    locationId: locationId,
  );
  unawaited(notifier.load());
  // A receipt into this location must show up without a manual reload.
  ref.listen<DataRevision>(dataRevisionProvider, (previous, next) {
    if (previous?.sequence == next.sequence) return;
    unawaited(notifier.refresh());
  });
  return notifier;
});
