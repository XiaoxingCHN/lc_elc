import 'dart:convert';
import 'dart:io';

import '../models/json_read.dart';

/// One cached PUBLIC catalog entry.
/// Only mall/catalog facts: what the component IS. Never what the laboratory
/// holds, who borrowed it or what happened to it.
class PublicCatalogEntry {
  const PublicCatalogEntry({
    required this.itemKey,
    required this.item,
    required this.files,
    required this.parameters,
    required this.savedAt,
  });

  /// `lcsc:C123` - local (`lab:`) identities are never stored here.
  final String itemKey;

  /// Whitelisted public row fields (name/mpn/brand/package/category/image).
  final Map<String, dynamic> item;

  /// Whitelisted public file entries (datasheets / manuals).
  final List<Map<String, dynamic>> files;

  /// Whitelisted public parameters.
  final List<Map<String, dynamic>> parameters;

  final DateTime savedAt;

  Map<String, dynamic> toJson() => <String, dynamic>{
        'item_key': itemKey,
        'item': item,
        'files': files,
        'parameters': parameters,
        'saved_at': savedAt.toIso8601String(),
      };

  static PublicCatalogEntry? fromJson(Map<String, dynamic> json) {
    final itemKey = asString(json['item_key']);
    // Never trust an existing index file: a foreign, older or hand-edited entry
    // must not smuggle business data in. Identity AND every field are re-checked.
    if (itemKey == null || !PublicCatalogStore.isPublicIdentity(itemKey)) return null;
    return PublicCatalogEntry(
      itemKey: itemKey,
      item: PublicCatalogStore.sanitizeItem(json['item']),
      files: PublicCatalogStore.sanitizeFiles(json['files']),
      parameters: PublicCatalogStore.sanitizeParameters(json['parameters']),
      savedAt: DateTime.tryParse(json['saved_at']?.toString() ?? '') ??
          DateTime.fromMillisecondsSinceEpoch(0),
    );
  }
}

/// Whitelist-stripped, session-independent store of PUBLIC catalog metadata.
///
/// Why this exists (root's offline design): at a cold start the server may be
/// unreachable and automatic login fails, so the app sits on the login screen and
/// a previously cached manual would be unreachable. The login screen therefore
/// offers "查看本机缓存资料", which reads THIS store - the same unified library,
/// read-only, with no stock.
///
/// Hard rules:
///   * every stored document is built through [sanitizeItem]/[sanitizeDetail], so
///     local SNs, quantities, bags, locations, borrowers, projects and history can
///     never reach the file (they are dropped, not merely hidden by the UI);
///   * only `lcsc:` identities are stored. An unbound local material (`lab:42`) is
///     private business data and is refused even when the operator is signed in;
///   * no secrets, no login timestamps, no server session state: the store reads
///     and writes its own JSON files only, so it cannot refresh the 10-day login
///     window or any credential;
///   * the index is bounded (LRU by save time) so an offline snack does not grow
///     without limit.
class PublicCatalogStore {
  PublicCatalogStore({
    required Future<Directory> Function() resolveDirectory,
    this.maxEntries = 500,
  }) : _resolveDirectory = resolveDirectory;

  /// Directory name under the app support directory.
  static const String directoryName = 'public_catalog';

  /// Fields copied from a list/detail item row. Everything else is dropped.
  static const Set<String> publicItemFields = <String>{
    'item_key',
    'catalog_code',
    'lcsc_code',
    'code',
    'part_number',
    'name',
    'display_name',
    'mpn',
    'brand',
    'brand_name',
    'package',
    'package_name',
    'footprint',
    'category',
    'category_name',
    'category_id',
    'image_url',
    'thumb_url',
    'thumbnail',
    'original_url',
    'image_original_url',
    // MALL stock/price are public catalog facts; they are displayed as reference
    // only and are NOT laboratory stock.
    'catalog_stock',
    'price',
    'currency',
    'revision',
  };

  /// Field names that must NEVER be persisted by this store. Kept explicit so a
  /// future refactor cannot quietly widen the whitelist.
  static const Set<String> forbiddenFields = <String>{
    'lab_quantity',
    'lab_available_quantity',
    'quantity',
    'qty',
    'has_stock',
    'lab_template_ids',
    'sn_codes',
    'sn',
    'lab_sn',
    'materials',
    'bags',
    'bag_ids',
    'locations',
    'location_ids',
    'history',
    'operations',
    'borrower',
    'borrower_id',
    'actor',
    'project',
    'note',
    'outstanding_quantity',
    'inventory_revision',
  };

  final Future<Directory> Function() _resolveDirectory;

  /// Maximum number of cached catalog entries.
  final int maxEntries;

  Directory? _directory;
  List<PublicCatalogEntry>? _index;

  /// Serializes read-modify-write cycles of the index.
  ///
  /// The live catalog caches a whole search page while a detail view may cache
  /// its own payload at the same moment; without this chain two concurrent
  /// `_upsert`s could each write a list missing the other's entry.
  Future<void> _writeQueue = Future<void>.value();

  /// Monotonic counter for unique temporary file names.
  int _writeSeq = 0;

  Future<T> _serialized<T>(Future<T> Function() action) {
    final result = _writeQueue.then((_) => action());
    // Keep the chain alive even when a single write fails.
    _writeQueue = result.then<void>((_) {}, onError: (Object _) {});
    return result;
  }

  Future<Directory> directory() async {
    final existing = _directory;
    if (existing != null) return existing;
    final base = await _resolveDirectory();
    final dir = Directory('${base.path}/$directoryName');
    if (!dir.existsSync()) await dir.create(recursive: true);
    _directory = dir;
    return dir;
  }

  Future<File> _indexFile() async => File('${(await directory()).path}/index.json');

  /// True when anything at all has been cached (the login entry uses this).
  Future<bool> hasEntries() async => (await list()).isNotEmpty;

  /// All cached entries, newest first.
  Future<List<PublicCatalogEntry>> list() async {
    final cached = _index;
    if (cached != null) return cached;
    _index = await _readIndexFromDisk();
    return _index!;
  }

  /// Parses the index file. Every entry is re-sanitized and identity-checked.
  Future<List<PublicCatalogEntry>> _readIndexFromDisk() async {
    final file = await _indexFile();
    if (!file.existsSync()) return <PublicCatalogEntry>[];
    try {
      final decoded = jsonDecode(await file.readAsString());
      final entries = asMapList(decoded)
          .map(PublicCatalogEntry.fromJson)
          .whereType<PublicCatalogEntry>()
          .toList();
      entries.sort((a, b) => b.savedAt.compareTo(a.savedAt));
      return entries;
    } catch (_) {
      // A corrupt index is discarded rather than trusted.
      return <PublicCatalogEntry>[];
    }
  }

  /// Persists the public part of one search row.
  ///
  /// MERGES with what is already cached: a search row carries no file list and
  /// often no parameters, so overwriting them would destroy the manual the operator
  /// already looked at. Returns `false` when the row is not a public catalog
  /// identity.
  Future<bool> saveItem(Map<String, dynamic> row) async {
    final itemKey = asString(row['item_key']) ?? '';
    if (!isPublicIdentity(itemKey)) return false;

    final existing = await _find(itemKey);
    final incomingItem = sanitizeItem(row);
    final incomingParameters =
        sanitizeParameters(row['parameters'] ?? row['params']);

    final entry = PublicCatalogEntry(
      itemKey: itemKey,
      // An empty sanitized row must not erase a previously cached row.
      item: incomingItem.isEmpty ? (existing?.item ?? <String, dynamic>{}) : incomingItem,
      // A search row never carries files: keep the ones the detail cached.
      files: existing?.files ?? const <Map<String, dynamic>>[],
      parameters: incomingParameters.isNotEmpty
          ? incomingParameters
          : (existing?.parameters ?? const <Map<String, dynamic>>[]),
      savedAt: DateTime.now(),
    );
    await _upsert(entry);
    return true;
  }

  /// Persists the public part of one detail payload, MERGING with a saved row.
  ///
  /// Only a non-empty fresh list replaces what is stored: a detail response that
  /// omits files/parameters must not wipe a manual that is already on disk.
  Future<bool> saveDetail(String itemKey, Map<String, dynamic> detail) async {
    if (!isPublicIdentity(itemKey)) return false;

    final itemJson = asMap(detail['item']);
    final existing = await _find(itemKey);
    final incomingItem = itemJson.isEmpty ? null : sanitizeItem(itemJson);
    final incomingFiles = sanitizeFiles(detail['files'] ?? detail['attachments']);
    final incomingParameters = sanitizeParameters(
      itemJson['parameters'] ?? detail['parameters'],
    );

    final entry = PublicCatalogEntry(
      itemKey: itemKey,
      item: incomingItem ?? (existing?.item ?? <String, dynamic>{}),
      files: incomingFiles.isNotEmpty
          ? incomingFiles
          : (existing?.files ?? const <Map<String, dynamic>>[]),
      parameters: incomingParameters.isNotEmpty
          ? incomingParameters
          : (existing?.parameters ?? const <Map<String, dynamic>>[]),
      savedAt: DateTime.now(),
    );
    await _upsert(entry);
    return true;
  }

  /// The cached public metadata of one catalog identity, or `null`.
  Future<PublicCatalogEntry?> read(String itemKey) async {
    if (!isPublicIdentity(itemKey)) return null;
    return _find(itemKey);
  }

  Future<PublicCatalogEntry?> _find(String itemKey) async {
    for (final entry in await list()) {
      if (entry.itemKey == itemKey) return entry;
    }
    return null;
  }

  Future<void> _upsert(PublicCatalogEntry entry) {
    return _serialized(() async {
      // Read the CURRENT file contents instead of the in-memory memo: another
      // store instance (a second call site, another isolate) may have written in
      // the meantime, and a read-modify-write on a stale list would drop its
      // entries.
      final entries = List<PublicCatalogEntry>.of(await _readIndexFromDisk())
        ..removeWhere((existing) => existing.itemKey == entry.itemKey)
        ..insert(0, entry);

      while (entries.length > maxEntries) {
        entries.removeLast();
      }

      final file = await _indexFile();
      // A UNIQUE temporary file per write: two writers can never share
      // `index.json.part`, so one can neither truncate nor rename the other's
      // half-written file.
      final temporary = File('${file.path}.${_writeSeq++}.part');
      try {
        await temporary.writeAsString(
          jsonEncode(entries.map((item) => item.toJson()).toList()),
          flush: true,
        );
      } on FileSystemException {
        // The new content could not be written: keep the existing index intact.
        return;
      }

      try {
        // Replaces the target atomically on POSIX.
        await temporary.rename(file.path);
      } on FileSystemException {
        // Windows cannot always rename onto an existing file. Keep a backup so the
        // index is never simply deleted, then swap.
        final backup = File('${file.path}.bak');
        try {
          if (backup.existsSync()) await backup.delete();
          if (file.existsSync()) await file.rename(backup.path);
          await temporary.rename(file.path);
          if (backup.existsSync()) await backup.delete();
        } on FileSystemException {
          // Last resort: restore the backup and give up on this write.
          if (!file.existsSync() && backup.existsSync()) {
            try {
              await backup.rename(file.path);
            } on FileSystemException {
              // Nothing else can be done here.
            }
          }
          return;
        }
      }

      // Only now is the new list authoritative.
      _index = entries;
    });
  }

  /// Forgets everything (used by "clear cached content").
  Future<void> clear() async {
    _index = <PublicCatalogEntry>[];
    final file = await _indexFile();
    if (file.existsSync()) {
      try {
        await file.delete();
      } on FileSystemException {
        // Ignore.
      }
    }
  }

  /// Only a captured public catalog identity may be cached here.
  static bool isPublicIdentity(String itemKey) =>
      itemKey.startsWith('lcsc:') && itemKey.length > 5;

  // ---------------------------------------------------------------------------
  // Sanitizers (pure, unit-tested)
  // ---------------------------------------------------------------------------

  /// Copies ONLY the whitelisted public fields of a catalog row.
  static Map<String, dynamic> sanitizeItem(Object? row) {
    final source = asMap(row);
    final result = <String, dynamic>{};
    for (final field in publicItemFields) {
      if (forbiddenFields.contains(field)) continue;
      final value = source[field];
      if (value == null || value == false) continue;
      result[field] = value;
    }
    // Defence in depth: an aliased private field is dropped even if a future
    // whitelist entry collides with it.
    for (final field in forbiddenFields) {
      result.remove(field);
    }
    return result;
  }

  /// Copies only the public text fields of the parameter list.
  static List<Map<String, dynamic>> sanitizeParameters(Object? value) {
    final result = <Map<String, dynamic>>[];
    for (final entry in asMapList(value)) {
      final code = firstString(entry, const ['code', 'parameterCode', 'parameter_code']);
      final name = firstString(entry, const ['name', 'parameterName', 'parameter_name']);
      final text = firstString(
        entry,
        const [
          'value',
          'parameterDetailValue',
          'parameter_value',
          'display_value',
          'text',
        ],
      );
      if (text == null) continue;
      result.add(<String, dynamic>{
        if (code != null) 'code': code,
        if (name != null) 'name': name,
        'value': text,
      });
    }
    return result;
  }

  /// Copies only the public file entries (datasheet / manual name + URL).
  static List<Map<String, dynamic>> sanitizeFiles(Object? value) {
    final result = <Map<String, dynamic>>[];
    for (final file in asMapList(value)) {
      final url = firstString(file, const ['fileUrl', 'file_url', 'url']);
      if (url == null) continue;
      final name = firstString(file, const ['fileName', 'file_name', 'name']);
      final type = firstString(file, const ['fileType', 'file_type', 'type']);
      result.add(<String, dynamic>{
        if (name != null) 'fileName': name,
        'fileUrl': url,
        if (type != null) 'fileType': type,
      });
    }
    return result;
  }
}

/// Default location: `<asset cache base>/public_catalog`.
///
/// The app passes `assetCacheDirectoryProvider`, so both caches live under the same
/// per-user application support directory and tests inject one temp directory for
/// all of them.
Future<Directory> defaultPublicCatalogDirectory(
  Future<Directory> Function() assetCacheBase,
) async {
  final base = await assetCacheBase();
  return Directory('${base.path}/${PublicCatalogStore.directoryName}');
}
