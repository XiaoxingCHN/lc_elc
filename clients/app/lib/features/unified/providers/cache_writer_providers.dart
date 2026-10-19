import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../models/unified_item.dart';
import '../services/asset_cache.dart';
import '../services/public_catalog_cache.dart';
import 'offline_providers.dart';
import 'unified_providers.dart';

/// Every cache WRITE the live catalog performs, behind ONE injectable seam.
///
/// Why this exists:
///   * a screen must never wait on disk I/O to be displayed, so the live providers
///     call these methods fire-and-forget;
///   * widget tests run inside `fakeAsync`, where real file I/O never completes -
///     without a seam, a "cache the page" side effect would hang a widget test that
///     only cares about layout. Tests override this provider with a recorder.
///
/// The production implementation delegates to the real stores; nothing else in the
/// app writes cache files.
abstract class CatalogCacheWriter {
  /// Persists the PUBLIC part of a freshly loaded search page.
  void savePublicPage(List<UnifiedItem> items);

  /// Persists the detail payload for offline use: the session-scoped business
  /// snapshot and the whitelisted public catalog metadata.
  void saveDetail(String itemKey, Map<String, dynamic> data);

  /// Marks the assets of a viewed/stocked item as "keep" (downloads missing ones
  /// in the background).
  void pinItemAssets(List<({String url, MediaKind kind})> assets);
}

/// The real implementation: writes through the session-scoped asset cache and the
/// public catalog store.
class StoreCatalogCacheWriter implements CatalogCacheWriter {
  StoreCatalogCacheWriter({
    required AssetCacheStore assetCache,
    required PublicCatalogStore publicStore,
  })  : _assetCache = assetCache,
        _publicStore = publicStore;

  final AssetCacheStore _assetCache;
  final PublicCatalogStore _publicStore;

  @override
  void savePublicPage(List<UnifiedItem> items) {
    if (items.isEmpty) return;
    // Best effort, never awaited, never fatal.
    cachePublicSearchPage(_publicStore, items).catchError((Object _) {});
  }

  @override
  void saveDetail(String itemKey, Map<String, dynamic> data) {
    _assetCache.saveDetail(itemKey, data).catchError((Object _) {});
    // PublicCatalogStore.saveDetail is Future<bool>: the swallow-on-error
    // callback MUST yield that same type or the future completes with a
    // TypeError on the error path.
    _publicStore.saveDetail(itemKey, data).catchError((Object _) => false);
  }

  @override
  void pinItemAssets(List<({String url, MediaKind kind})> assets) {
    if (assets.isEmpty) return;
    _assetCache.pin(assets).catchError((Object _) {});
  }
}

final catalogCacheWriterProvider = Provider<CatalogCacheWriter>((ref) {
  return StoreCatalogCacheWriter(
    assetCache: ref.watch(assetCacheProvider),
    publicStore: ref.watch(publicCatalogStoreProvider),
  );
});
