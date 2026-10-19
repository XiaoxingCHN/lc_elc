import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/catalog_query.dart';
import '../models/detail_models.dart';
import '../models/identity.dart';
import '../models/unified_item.dart';
import '../services/asset_cache.dart';
import '../services/public_catalog_cache.dart';
import 'unified_providers.dart';

/// True while the app shows the PUBLIC offline catalog.
///
/// Set by the `/catalog?offline=1` route (or by the "查看本机缓存资料" button on the
/// login screen). In this mode:
///   * nothing is treated as an authenticated server response;
///   * no stock figure, SN, bag, borrower, project or history is shown;
///   * every stock action (receipt / issue / return / bind / create / labels) is
///     unavailable, because there is no session to write with.
final offlineCatalogModeProvider = StateProvider<bool>((ref) => false);

/// The session-independent store of public catalog metadata.
///
/// Deliberately NOT scoped by server/database/user: it holds only public mall
/// catalog facts, which is exactly what may be browsed without a session. Business
/// data continues to live in the per-session scoped caches.
final publicCatalogStoreProvider = Provider<PublicCatalogStore>((ref) {
  // Reuses the asset cache base directory, so one injected temp dir covers the
  // file cache, the public catalog index and the offline detail metadata.
  return PublicCatalogStore(
    resolveDirectory: ref.watch(assetCacheDirectoryProvider),
  );
});

/// Asset cache used by the offline browser.
///
/// `scopeKey` is empty and persistence of business-carrying files is off, so it
/// reads ONLY the shared `public/` directory (external CDN images and manuals). A
/// same-origin authenticated file stays invisible here - it belongs to a session.
final offlineAssetCacheProvider = Provider<AssetCacheStore>((ref) {
  return AssetCacheStore(
    resolveDirectory: ref.watch(assetCacheDirectoryProvider),
    scopeKey: '',
    persistBusinessData: false,
    // Cache-ONLY: a missing asset reports a miss instead of opening a connection.
    cacheOnly: true,
    // No session fetcher: the offline browser must not send credentials.
    authenticatedFetcher: null,
    baseUriResolver: () async => null,
  );
});

/// The cache the MEDIA widgets must use.
///
/// In the public offline mode the answer is [offlineAssetCacheProvider], which
/// reads only the shared public directory and never sends credentials; a live
/// session uses the scoped cache. Keeping this behind ONE provider means an image
/// or manual widget can never accidentally pick the wrong store.
final effectiveAssetCacheProvider = Provider<AssetCacheStore>((ref) {
  if (ref.watch(offlineCatalogModeProvider)) {
    return ref.watch(offlineAssetCacheProvider);
  }
  return ref.watch(assetCacheProvider);
});

/// The cached public entries, filtered LOCALLY.
///
/// A local filter is the only honest option offline: there is no server to page
/// through. This never pretends to be the live merged list - the UI labels it.
final offlineCatalogEntriesProvider =
    FutureProvider<List<PublicCatalogEntry>>((ref) async {
  return ref.watch(publicCatalogStoreProvider).list();
});

/// One offline result row, in the shape the shared card widget understands.
///
/// Stock fields are deliberately zeroed/absent: the offline browser must not invent
/// a laboratory quantity, and the card renders "no stock information" instead.
class OfflineCatalogPage {
  const OfflineCatalogPage({required this.items, required this.totalAvailable});

  final List<UnifiedItem> items;

  /// How many entries the cache holds in total (for the empty-state message).
  final int totalAvailable;

  bool get isEmpty => items.isEmpty;
}

/// Builds a display row from one cached public entry.
UnifiedItem offlineItemFrom(PublicCatalogEntry entry) {
  final item = Map<String, dynamic>.of(entry.item);
  // The card is built from public fields only; no lab stock can be present
  // because the store never persisted any.
  item['item_key'] = entry.itemKey;
  if (entry.parameters.isNotEmpty) item['parameters'] = entry.parameters;
  item['lab_quantity'] = 0;
  item['has_stock'] = false;
  return UnifiedItem.fromJson(item);
}

/// Filter the offline browser applies (local, never server-side).
final offlineCatalogQueryProvider =
    StateProvider<CatalogQuery>((ref) => const CatalogQuery());

final offlineCatalogProvider = FutureProvider<OfflineCatalogPage>((ref) async {
  final query = ref.watch(offlineCatalogQueryProvider);
  final entries = await ref.watch(offlineCatalogEntriesProvider.future);
  final text = query.text.trim().toLowerCase();

  final filtered = entries.where((entry) {
    final item = offlineItemFrom(entry);
    if (query.brands.isNotEmpty && !query.brands.contains(item.brand)) return false;
    if (query.packages.isNotEmpty && !query.packages.contains(item.packageName)) {
      return false;
    }
    if (query.categoryId != null && item.categoryId != query.categoryId) return false;
    if (text.isEmpty) return true;
    return <String>[
      item.name,
      item.mpn,
      item.brand,
      item.packageName,
      displayCatalogCode(item.catalogCode),
    ].join(' ').toLowerCase().contains(text);
  }).toList();

  return OfflineCatalogPage(
    items: filtered.map(offlineItemFrom).toList(),
    totalAvailable: entries.length,
  );
});

/// Facet values available in the offline cache (brands / packages only).
final offlineCatalogFacetsProvider = FutureProvider<CatalogFacets>((ref) async {
  final entries = await ref.watch(offlineCatalogEntriesProvider.future);
  final brandCounts = <String, int>{};
  final packageCounts = <String, int>{};
  for (final entry in entries) {
    final item = offlineItemFrom(entry);
    if (item.brand.isNotEmpty) {
      brandCounts[item.brand] = (brandCounts[item.brand] ?? 0) + 1;
    }
    if (item.packageName.isNotEmpty) {
      packageCounts[item.packageName] = (packageCounts[item.packageName] ?? 0) + 1;
    }
  }
  return CatalogFacets(
    brands: brandCounts.entries
        .map((entry) => FacetOption(
              value: entry.key,
              label: entry.key,
              count: entry.value,
            ))
        .toList(),
    packages: packageCounts.entries
        .map((entry) => FacetOption(
              value: entry.key,
              label: entry.key,
              count: entry.value,
            ))
        .toList(),
    parameters: const <ParameterFacet>[],
  );
});

/// The cached public detail of one catalog identity (parameters + files).
///
/// Derived from the PUBLIC store only: no locations, no bags, no history, no
/// materials - so the offline detail page cannot leak business data even by
/// accident.
final offlineCatalogDetailProvider = FutureProvider.autoDispose
    .family<CatalogDetail, String>((ref, itemKey) async {
  final entry = await ref.watch(publicCatalogStoreProvider).read(itemKey);
  if (entry == null) {
    return CatalogDetail.empty;
  }

  final item = Map<String, dynamic>.of(entry.item)
    ..['item_key'] = entry.itemKey
    ..['parameters'] = entry.parameters
    ..['lab_quantity'] = 0
    ..['has_stock'] = false;

  return CatalogDetail(
    item: UnifiedItem.fromJson(item),
    locations: const <LabStockLocation>[],
    bags: const <LabBag>[],
    files: entry.files.map(_fileFrom).whereType<LabFile>().toList(),
    history: const <LabOperation>[],
    materials: const <LabMaterial>[],
  );
});

LabFile? _fileFrom(Map<String, dynamic> json) {
  final url = json['fileUrl']?.toString();
  if (url == null || url.isEmpty) return null;
  return LabFile(
    name: json['fileName']?.toString() ?? '',
    url: url,
    type: json['fileType']?.toString() ?? '',
  );
}

/// Saves the public part of a freshly loaded search page.
///
/// Called by the live catalog so a later offline session has something to browse.
Future<void> cachePublicSearchPage(
  PublicCatalogStore store,
  List<UnifiedItem> items,
) async {
  for (final item in items) {
    if (!item.isCatalogCard) continue;
    await store.saveItem(item.raw.isEmpty ? <String, dynamic>{
      'item_key': item.itemKey,
      'catalog_code': item.catalogCode,
      'name': item.name,
      'mpn': item.mpn,
      'brand': item.brand,
      'package': item.packageName,
      'category_name': item.categoryName,
      'category_id': item.categoryId,
      'image_url': item.imageUrl,
      'parameters': item.parameters
          .map((parameter) => <String, dynamic>{
                'code': parameter.code,
                'name': parameter.name,
                'value': parameter.value,
              })
          .toList(),
    } : item.raw);
  }
}
