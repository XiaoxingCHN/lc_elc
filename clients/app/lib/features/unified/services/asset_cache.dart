import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:dio/dio.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// What kind of captured asset is being cached.
enum MediaKind {
  /// Product thumbnail from the captured catalog data.
  image,

  /// Datasheet / manual file (usually a PDF).
  manual,
}

/// Downloads bytes for one absolute URL.
///
/// Production uses the private [Dio] instance inside [AssetCacheStore]; tests
/// inject a function that counts calls, so "the second read is served from disk"
/// can be proven without any network.
typedef AssetDownloader = Future<Uint8List> Function(String url);

/// Fetches an asset from the ODOO SERVER with the authenticated session.
///
/// Wired to `OdooClient` (see `lib/features/unified/README.md`). It is used only
/// for same-origin references such as `/lab/api/asset/data`; an external CDN
/// never sees the session cookie.
typedef AuthenticatedAssetFetcher = Future<Uint8List> Function(Uri uri);

/// Resolves the Odoo base URI, needed to turn `/lab/api/asset/...` into an
/// absolute same-origin URL.
typedef BaseUriResolver = Future<Uri?> Function();

/// A failed asset fetch (offline with nothing cached, HTTP error, wrong MIME,
/// oversized or truncated file, ...).
class AssetCacheException implements Exception {
  const AssetCacheException(this.message, {this.url, this.cause});

  final String message;
  final String? url;
  final Object? cause;

  @override
  String toString() => 'AssetCacheException($message)';
}

/// Limits applied to every downloaded asset.
class AssetFetchPolicy {
  const AssetFetchPolicy({
    this.maxImageBytes = 8 * 1024 * 1024,
    this.maxManualBytes = 32 * 1024 * 1024,
    this.memoryBudgetBytes = 16 * 1024 * 1024,
    this.memoryEntryMaxBytes = 512 * 1024,
  });

  /// A single image may not exceed 8 MiB.
  final int maxImageBytes;

  /// A single manual may not exceed 32 MiB.
  final int maxManualBytes;

  /// Total bytes of DECODED assets kept in memory.
  final int memoryBudgetBytes;

  /// An entry larger than this is never kept in memory (a 30 MiB PDF must not
  /// sit in the 48-entry image cache).
  final int memoryEntryMaxBytes;

  int limitFor(MediaKind kind) =>
      kind == MediaKind.image ? maxImageBytes : maxManualBytes;
}

/// File-backed cache for images and manuals, plus the offline metadata store.
///
/// Root's requirements implemented here:
///   * images/manuals load from the network during normal work;
///   * a VIEWED or STOCKED item is cached as real bytes on disk, so an offline
///     read performs no request at all (never a "cached URL");
///   * the DETAIL metadata of a viewed item is cached too, so an offline open
///     still shows the parameter/manual list and can open the cached manual -
///     caching only the file bytes would leave the UI unable to reach them;
///   * an authenticated `/lab/api/asset/...` reference is fetched from the same
///     origin with the session; an external CDN is fetched WITHOUT cookies;
///   * every download is size-capped, MIME-checked, magic-byte-checked (so an
///     HTML login page is never stored as an image), written to a temp file and
///     atomically renamed;
///   * pinned assets (viewed / received) are never evicted.
class AssetCacheStore {
  AssetCacheStore({
    required Future<Directory> Function() resolveDirectory,
    AssetDownloader? downloader,
    AuthenticatedAssetFetcher? authenticatedFetcher,
    BaseUriResolver? baseUriResolver,
    Future<SharedPreferences> Function()? preferences,
    this.scopeKey = '',
    this.persistBusinessData = true,
    this.cacheOnly = false,
    this.policy = const AssetFetchPolicy(),
    this.maxCacheBytes = 256 * 1024 * 1024,
  })  : _resolveDirectory = resolveDirectory,
        _downloader = downloader,
        _authenticatedFetcher = authenticatedFetcher,
        _baseUriResolver = baseUriResolver ?? _noBaseUri,
        _preferences = preferences ?? SharedPreferences.getInstance;

  /// Keys of the persisted pin list (viewed / stocked assets).
  static const String pinnedKey = 'lab_asset_pinned_urls';

  /// Directory holding PUBLIC (external CDN) files, shared by every session
  /// because they carry no account data.
  static const String publicDirName = 'public';

  /// Hash of `(server, database, uid, company)` this store belongs to.
  ///
  /// Same-origin files and the offline detail metadata are stored under it, so a
  /// different operator (or the same uid on another server) cannot read them.
  final String scopeKey;

  /// False for a signed-out scope: a hash alone cannot tell whether a session
  /// exists, and business data must not be written without one.
  final bool persistBusinessData;

  /// True only when there is a session AND a scope hash to isolate its files.
  bool get canPersistScoped => persistBusinessData && scopeKey.trim().isNotEmpty;

  /// Cache-ONLY mode (the public offline browser).
  ///
  /// A miss is reported instead of being fetched: browsing a cache while the
  /// server is unreachable must not open a connection, and an unauthenticated
  /// entry must never fetch anything.
  final bool cacheOnly;

  final Future<Directory> Function() _resolveDirectory;
  final AssetDownloader? _downloader;
  final AuthenticatedAssetFetcher? _authenticatedFetcher;
  final BaseUriResolver _baseUriResolver;
  final Future<SharedPreferences> Function() _preferences;
  final AssetFetchPolicy policy;

  /// Soft cap for the on-disk cache (pinned assets are exempt).
  final int maxCacheBytes;

  Directory? _directory;
  Directory? _metaDirectory;
  Dio? _dio;

  final Map<String, Uint8List> _memory = <String, Uint8List>{};
  int _memoryBytes = 0;
  final Map<String, Future<Uint8List>> _inFlight = <String, Future<Uint8List>>{};
  Set<String>? _pinned;

  static Future<Uri?> _noBaseUri() async => null;

  /// The cache directory, created on first use.
  Future<Directory> directory() async {
    final existing = _directory;
    if (existing != null) return existing;
    final base = await _resolveDirectory();
    if (!base.existsSync()) {
      await base.create(recursive: true);
    }
    _directory = base;
    await _cleanOrphanParts(base);
    return base;
  }

  /// Name of the per-session directory.
  String get scopeDirectoryName =>
      scopeKey.trim().isEmpty ? 'scope-none' : 'scope-$scopeKey';

  /// True when [uri] points at the configured Odoo server itself.
  ///
  /// Same-origin responses can carry account-specific bytes (an authenticated
  /// `/lab/api/asset/...`), so they are stored per session; only an EXTERNAL CDN
  /// file may be shared between sessions.
  Future<bool> isSameOrigin(Uri uri) async {
    final base = await _baseUriResolver();
    if (base == null || base.host.isEmpty) return false;
    return base.host.toLowerCase() == uri.host.toLowerCase() &&
        base.port == uri.port &&
        base.scheme == uri.scheme;
  }

  /// Directory an asset belongs to: shared for a CDN, per-session otherwise.
  Future<Directory> assetDirectoryFor(Uri uri) async {
    final base = await directory();
    final sameOrigin = await isSameOrigin(uri);
    final name = sameOrigin ? scopeDirectoryName : publicDirName;
    final dir = Directory('${base.path}/$name');
    if (!dir.existsSync()) await dir.create(recursive: true);
    return dir;
  }

  /// Where the offline detail metadata lives (per session).
  Future<Directory> metaDirectory() async {
    final existing = _metaDirectory;
    if (existing != null) return existing;
    final base = await directory();
    final dir = Directory('${base.path}/$scopeDirectoryName/details');
    if (!dir.existsSync()) await dir.create(recursive: true);
    _metaDirectory = dir;
    return dir;
  }

  /// Absolute URL of a reference, or the original when it already is absolute.
  ///
  /// Returns `null` when the reference cannot be resolved (a relative path with
  /// no known server) - the caller then shows the explicit placeholder instead
  /// of guessing a host.
  Future<Uri?> resolveReference(String reference) async {
    final text = reference.trim();
    if (text.isEmpty) return null;
    final parsed = Uri.tryParse(text);
    if (parsed == null) return null;
    if (parsed.scheme == 'http' || parsed.scheme == 'https') {
      return parsed.host.isEmpty ? null : parsed;
    }
    if (parsed.scheme.isNotEmpty) return null;
    final base = await _baseUriResolver();
    if (base == null) return null;
    return base.resolve(text);
  }

  /// Path of the cached file for an absolute URL (may not exist yet).
  Future<File> fileForUri(Uri uri, {MediaKind kind = MediaKind.image}) async {
    final dir = await assetDirectoryFor(uri);
    final hash = sha256.convert(utf8.encode(uri.toString())).toString();
    return File('${dir.path}/$hash${_extensionFor(uri, kind)}');
  }

  /// True when the asset is already on disk (usable offline).
  Future<bool> hasCached(String reference, {MediaKind kind = MediaKind.image}) async {
    final uri = await resolveReference(reference);
    if (uri == null) return false;
    return (await fileForUri(uri, kind: kind)).existsSync();
  }

  /// Reads a cached asset from memory or disk. Never touches the network.
  Future<Uint8List?> readCachedOnly(
    String reference, {
    MediaKind kind = MediaKind.image,
  }) async {
    final uri = await resolveReference(reference);
    if (uri == null) return null;
    final key = uri.toString();

    final memory = _memory[key];
    if (memory != null) return memory;

    final file = await fileForUri(uri, kind: kind);
    if (!file.existsSync()) return null;
    try {
      final bytes = await file.readAsBytes();
      if (bytes.isEmpty || !_looksLikeDeclaredKind(bytes, kind, file.path)) {
        // A truncated or corrupt file is removed rather than served.
        try {
          await file.delete();
        } on FileSystemException {
          // Ignore.
        }
        return null;
      }
      _remember(key, bytes);
      return bytes;
    } on FileSystemException {
      return null;
    }
  }

  /// Cache-first read: memory, disk, then (only if needed) the network.
  Future<Uint8List> read(String reference, {MediaKind kind = MediaKind.image}) async {
    final cached = await readCachedOnly(reference, kind: kind);
    if (cached != null) return cached;

    if (cacheOnly) {
      // Offline browse: never open a connection for a missing asset.
      final uri = await resolveReference(reference);
      throw AssetCacheException(
        '本机没有该文件(${kind == MediaKind.manual ? '手册' : '图片'})的缓存，'
        '离线模式下不会联网获取。',
        url: uri?.toString() ?? reference,
      );
    }

    final uri = await resolveReference(reference);
    if (uri == null) {
      throw AssetCacheException(
        '无法解析该资源地址（缺少服务器信息或地址不合法）。',
        url: reference,
      );
    }
    final key = uri.toString();
    final existing = _inFlight[key];
    if (existing != null) return existing;

    final future = _download(uri, kind: kind);
    _inFlight[key] = future;
    try {
      return await future;
    } finally {
      _inFlight.remove(key);
    }
  }

  /// Tries several candidate references in order (e.g. an authenticated
  /// same-origin link first, then the public original URL).
  Future<Uint8List> readPreferred(
    List<String> references, {
    MediaKind kind = MediaKind.image,
  }) async {
    final candidates = <String>[];
    for (final reference in references) {
      final text = reference.trim();
      if (text.isNotEmpty && !candidates.contains(text)) candidates.add(text);
    }
    if (candidates.isEmpty) {
      throw const AssetCacheException('没有可用的资源地址。');
    }
    Object? firstError;
    for (final candidate in candidates) {
      try {
        return await read(candidate, kind: kind);
      } catch (error) {
        firstError ??= error;
      }
    }
    throw firstError is AssetCacheException
        ? firstError
        : AssetCacheException('资源下载失败。', cause: firstError);
  }

  /// Ensures the asset is on disk and returns the real file (for manuals).
  Future<File> ensureFile(
    String reference, {
    MediaKind kind = MediaKind.manual,
  }) async {
    await read(reference, kind: kind);
    final uri = await resolveReference(reference);
    if (uri == null) {
      throw const AssetCacheException('无法解析该资源地址。');
    }
    return fileForUri(uri, kind: kind);
  }

  /// Marks assets as "keep": a viewed item or one that was received into stock.
  ///
  /// Missing assets are fetched in the background (best effort, never fatal).
  Future<void> pin(Iterable<({String url, MediaKind kind})> assets) async {
    final pins = await _loadPins();
    var changed = false;
    final toFetch = <({String url, MediaKind kind})>[];

    for (final asset in assets) {
      final url = asset.url.trim();
      if (url.isEmpty) continue;
      if (pins.add(url)) changed = true;
      if (!await hasCached(url, kind: asset.kind)) {
        toFetch.add((url: url, kind: asset.kind));
      }
    }

    if (changed) {
      final preferences = await _preferences();
      await preferences.setStringList(_pinsKey, pins.toList());
    }
    for (final asset in toFetch) {
      unawaited(
        read(asset.url, kind: asset.kind).catchError((Object _) => Uint8List(0)),
      );
    }
  }

  Future<Set<String>> _loadPins() async {
    final cached = _pinned;
    if (cached != null) return cached;
    try {
      final preferences = await _preferences();
      _pinned =
          (preferences.getStringList(_pinsKey) ?? const <String>[]).toSet();
    } catch (_) {
      _pinned = <String>{};
    }
    return _pinned!;
  }

  /// Pins are per session as well: a pinned same-origin file of another operator
  /// must not be kept (or evicted) on this operator's behalf.
  String get _pinsKey => scopeKey.trim().isEmpty
      ? pinnedKey
      : '$pinnedKey:${scopeDirectoryName}';

  /// True when this reference was pinned (viewed or stocked) at some point.
  Future<bool> isPinned(String reference) async {
    final pins = await _loadPins();
    if (pins.contains(reference.trim())) return true;
    final uri = await resolveReference(reference);
    return uri != null && pins.contains(uri.toString());
  }

  /// Total size of the on-disk cache (files + metadata + sidecars).
  ///
  /// A directory that disappears while it is being measured (another process, a
  /// cleanup) is reported as far as it could be read instead of throwing.
  Future<int> sizeBytes() async {
    try {
      final dir = await directory();
      var total = 0;
      await for (final entity in dir.list(recursive: true)) {
        if (entity is File) total += await entity.length();
      }
      return total;
    } on FileSystemException {
      return 0;
    }
  }

  /// Deletes the oldest non-pinned ASSET files until the cache fits
  /// [maxCacheBytes].
  ///
  /// Offline detail metadata (`/details/`) is left alone: it is small, and
  /// dropping it would break the offline detail page this cache exists for.
  Future<int> evictIfNeeded() async {
    final total = await sizeBytes();
    if (total <= maxCacheBytes) return 0;

    final pins = await _loadPins();
    final dir = await directory();
    final entries = <({File file, DateTime modified})>[];
    try {
      await for (final entity in dir.list(recursive: true)) {
        if (entity is! File) continue;
        if (entity.path.endsWith('.json') || entity.path.endsWith('.part')) continue;
        if (entity.path.contains('${Platform.pathSeparator}details'
            '${Platform.pathSeparator}')) {
          continue;
        }
        final meta = await _readMeta(entity);
        final url = meta?['url']?.toString();
        if (url != null && pins.contains(url)) continue;
        entries.add((file: entity, modified: (await entity.stat()).modified));
      }
    } on FileSystemException {
      // The directory changed while it was being scanned; nothing to evict.
      return 0;
    }
    entries.sort((a, b) => a.modified.compareTo(b.modified));

    var freed = 0;
    var remaining = total;
    for (final entry in entries) {
      if (remaining <= maxCacheBytes) break;
      final length = await entry.file.length();
      final meta = await _readMeta(entry.file);
      try {
        await entry.file.delete();
        final sidecar = File('${entry.file.path}.json');
        if (sidecar.existsSync()) await sidecar.delete();
        remaining -= length;
        freed += length;
        final url = meta?['url']?.toString();
        if (url != null) _forget(url);
      } on FileSystemException {
        // A locked file is skipped, not fatal.
      }
    }
    return freed;
  }

  /// Drops this session's cache (same-origin assets + offline detail metadata)
  /// and the shared public files. Another session's directory is never touched.
  Future<void> clear() async {
    _memory.clear();
    _memoryBytes = 0;
    _pinned = <String>{};
    try {
      final preferences = await _preferences();
      await preferences.remove(_pinsKey);
    } catch (_) {
      // Preference storage is optional here.
    }

    final base = await directory();
    for (final name in <String>[scopeDirectoryName, publicDirName]) {
      final dir = Directory('${base.path}/$name');
      if (!dir.existsSync()) continue;
      await for (final entity in dir.list(recursive: true)) {
        if (entity is! File) continue;
        try {
          await entity.delete();
        } on FileSystemException {
          // Ignore locked files.
        }
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Offline detail metadata
  // ---------------------------------------------------------------------------

  /// Persists the raw `/lab/api/catalog/detail` payload of a viewed item.
  ///
  /// Refused without a session scope: business metadata must never be written to
  /// a directory that another (or no) account could read.
  Future<void> saveDetail(String itemKey, Map<String, dynamic> data) async {
    if (!canPersistScoped) return;
    if (itemKey.trim().isEmpty || data.isEmpty) return;
    try {
      final dir = await metaDirectory();
      final file = File('${dir.path}/${_hash(itemKey)}.json');
      final temporary = File('${file.path}.part');
      await temporary.writeAsString(
        jsonEncode(<String, dynamic>{
          'item_key': itemKey,
          'saved_at': DateTime.now().toIso8601String(),
          'data': data,
        }),
        flush: true,
      );
      if (file.existsSync()) await file.delete();
      await temporary.rename(file.path);
    } on FileSystemException {
      // Caching metadata is best effort; the live request already succeeded.
    }
  }

  /// Reads the cached detail metadata of [itemKey] for THIS session, or `null`.
  Future<({Map<String, dynamic> data, DateTime? savedAt})?> readDetail(
    String itemKey,
  ) async {
    if (!canPersistScoped) return null;
    try {
      final dir = await metaDirectory();
      final file = File('${dir.path}/${_hash(itemKey)}.json');
      if (!file.existsSync()) return null;
      final decoded = jsonDecode(await file.readAsString());
      if (decoded is! Map) return null;
      final data = decoded['data'];
      if (data is! Map) return null;
      return (
        data: data.map((key, value) => MapEntry(key.toString(), value)),
        savedAt: DateTime.tryParse(decoded['saved_at']?.toString() ?? ''),
      );
    } catch (_) {
      return null;
    }
  }

  // ---------------------------------------------------------------------------
  // Internals
  // ---------------------------------------------------------------------------

  Future<Uint8List> _download(Uri uri, {required MediaKind kind}) async {
    final base = await _baseUriResolver();
    final sameOrigin = base != null &&
        base.host.isNotEmpty &&
        base.host.toLowerCase() == uri.host.toLowerCase() &&
        base.port == uri.port &&
        base.scheme == uri.scheme;

    Uint8List bytes;
    String? contentType;
    int? declaredLength;

    if (sameOrigin && _authenticatedFetcher != null) {
      // Same-origin, session-authenticated asset: the cookie belongs here.
      try {
        bytes = await _authenticatedFetcher(uri);
      } catch (error) {
        throw AssetCacheException(
          '服务器资源下载失败（已使用登录会话）。',
          url: uri.toString(),
          cause: error,
        );
      }
    } else {
      // External CDN (or a same-origin route we must not authenticate with):
      // fetched WITHOUT cookies.
      final result = await _downloadAnonymous(uri, kind: kind);
      bytes = result.bytes;
      contentType = result.contentType;
      declaredLength = result.declaredLength;
    }

    _validate(uri, bytes, kind: kind, contentType: contentType, declaredLength: declaredLength);

    // A same-origin file may carry account-specific bytes. Without a session
    // scope there is no directory that is guaranteed private, so the bytes are
    // returned for immediate display but NOT persisted.
    final persist = !sameOrigin || canPersistScoped;
    if (!persist) return bytes;

    final file = await fileForUri(uri, kind: kind);
    // Write through a temporary file so a killed process can never leave a
    // truncated asset that would later be served as if it were complete.
    final temporary = File('${file.path}.part');
    try {
      await temporary.writeAsBytes(bytes, flush: true);
      if (file.existsSync()) await file.delete();
      await temporary.rename(file.path);
      final meta = File('${file.path}.json');
      await meta.writeAsString(
        jsonEncode(<String, dynamic>{
          'url': uri.toString(),
          'kind': kind.name,
          'content_type': contentType ?? _contentTypeFor(uri, kind),
          'fetched_at': DateTime.now().toIso8601String(),
          'bytes': bytes.length,
        }),
      );
    } on FileSystemException {
      // A cache write failure must not break viewing: the bytes are still
      // returned, they just will not survive a restart.
      if (temporary.existsSync()) {
        try {
          await temporary.delete();
        } on FileSystemException {
          // Nothing else to do.
        }
      }
    }

    _remember(uri.toString(), bytes);
    _scheduleEviction();
    return bytes;
  }

  /// Runs housekeeping in the background.
  ///
  /// A cache bookkeeping failure (a file deleted under us, a locked directory)
  /// must never surface as an application error: the bytes the caller asked for
  /// were already delivered.
  void _scheduleEviction() {
    unawaited(
      evictIfNeeded().catchError((Object _) => 0),
    );
  }

  Future<({Uint8List bytes, String? contentType, int? declaredLength})>
      _downloadAnonymous(Uri uri, {required MediaKind kind}) async {
    // An injected downloader (tests, or a host with its own HTTP stack) is used
    // for the anonymous/public path as well, so both branches are testable.
    final injected = _downloader;
    if (injected != null) {
      try {
        return (
          bytes: await injected(uri.toString()),
          contentType: null,
          declaredLength: null,
        );
      } catch (error) {
        throw AssetCacheException(
          '下载失败：$error',
          url: uri.toString(),
          cause: error,
        );
      }
    }

    final dio = _dio ??= Dio(
      BaseOptions(
        connectTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 30),
        responseType: ResponseType.bytes,
        // No cookie jar and no interceptor: the Odoo session must never be
        // replayed to a CDN, and this client is not a proxy.
        headers: <String, dynamic>{'Accept': '*/*'},
        maxRedirects: 3,
        validateStatus: (status) => status != null && status >= 200 && status < 400,
      ),
    );
    try {
      final response = await dio.get<List<int>>(
        uri.toString(),
        options: Options(
          // Refuse an oversized body before it is buffered completely.
          headers: <String, dynamic>{'Accept': '*/*'},
        ),
      );
      final data = response.data;
      if (data == null) {
        throw AssetCacheException('服务器没有返回文件内容。', url: uri.toString());
      }
      final contentType = response.headers.value(Headers.contentTypeHeader);
      final declared = int.tryParse(
        response.headers.value(Headers.contentLengthHeader) ?? '',
      );
      return (
        bytes: Uint8List.fromList(data),
        contentType: contentType,
        declaredLength: declared,
      );
    } on DioException catch (error) {
      throw AssetCacheException(
        error.response?.statusCode == 401 || error.response?.statusCode == 403
            ? '该资源需要登录服务器后才能获取。'
            : '网络请求失败：${error.type.name}',
        url: uri.toString(),
        cause: error,
      );
    }
  }

  /// Size, MIME and integrity checks - an HTML error page must never be stored
  /// as a product photo.
  void _validate(
    Uri uri,
    Uint8List bytes, {
    required MediaKind kind,
    String? contentType,
    int? declaredLength,
  }) {
    if (bytes.isEmpty) {
      throw AssetCacheException('服务器返回了空文件。', url: uri.toString());
    }

    final limit = policy.limitFor(kind);
    if (bytes.length > limit) {
      throw AssetCacheException(
        '文件过大（${(bytes.length / 1024 / 1024).toStringAsFixed(1)} MB，上限 '
        '${(limit / 1024 / 1024).toStringAsFixed(0)} MB），已拒绝缓存。',
        url: uri.toString(),
      );
    }
    if (declaredLength != null && declaredLength > limit) {
      throw AssetCacheException(
        '文件过大（声明 ${(declaredLength / 1024 / 1024).toStringAsFixed(1)} MB）。',
        url: uri.toString(),
      );
    }
    // A short body against a declared length means a truncated transfer.
    if (declaredLength != null &&
        declaredLength > 0 &&
        bytes.length < declaredLength) {
      throw AssetCacheException(
        '文件下载不完整（收到 ${bytes.length} 字节，应为 $declaredLength 字节）。',
        url: uri.toString(),
      );
    }

    if (contentType != null) {
      final mime = contentType.toLowerCase();
      if (mime.contains('text/html') || mime.contains('application/json')) {
        throw AssetCacheException(
          '服务器返回的不是文件内容（$contentType），可能是登录页或错误信息。',
          url: uri.toString(),
        );
      }
      if (kind == MediaKind.image && !mime.startsWith('image/') && !mime.contains('octet-stream')) {
        throw AssetCacheException('返回内容不是图片（$contentType）。', url: uri.toString());
      }
      if (kind == MediaKind.manual &&
          !mime.contains('pdf') &&
          !mime.contains('octet-stream') &&
          !mime.contains('msword') &&
          !mime.contains('officedocument') &&
          !mime.contains('text/plain') &&
          !mime.contains('zip')) {
        throw AssetCacheException('返回内容不是手册文件（$contentType）。', url: uri.toString());
      }
    }

    if (!_looksLikeDeclaredKind(bytes, kind, uri.path)) {
      throw AssetCacheException(
        '文件内容与类型不符，已拒绝缓存（可能损坏或不完整）。',
        url: uri.toString(),
      );
    }
  }

  /// Magic-byte check: recognises the formats this business actually receives.
  ///
  /// An unknown-but-declared file type is not rejected here (the MIME check
  /// above already caught the dangerous cases); only a clear mismatch - for
  /// example a PDF requested as an image, or an HTML page - is refused.
  bool _looksLikeDeclaredKind(Uint8List bytes, MediaKind kind, String pathOrName) {
    if (_looksLikeHtml(bytes)) return false;
    final signature = _signatureOf(bytes);

    if (kind == MediaKind.manual) {
      if (signature == 'pdf') return true;
      // Non-PDF manuals are allowed when the name says so.
      final lower = pathOrName.toLowerCase();
      if (signature == 'image' || signature == 'zip' || signature == 'unknown') {
        return lower.endsWith('.doc') ||
            lower.endsWith('.docx') ||
            lower.endsWith('.txt') ||
            lower.endsWith('.zip') ||
            lower.endsWith('.csv') ||
            signature != 'unknown';
      }
      return false;
    }

    // Image slot: accept the raster formats the capture produces.
    return signature == 'image' ||
        signature == 'pdf' || // some captures leak a datasheet into the image slot
        signature == 'unknown';
  }

  static bool _looksLikeHtml(Uint8List bytes) {
    final head = bytes.length > 64 ? bytes.sublist(0, 64) : bytes;
    final text = String.fromCharCodes(head).toLowerCase();
    return text.contains('<!doctype html') ||
        text.contains('<html') ||
        text.contains('<?xml') && text.contains('<html');
  }

  static String _signatureOf(Uint8List bytes) {
    if (bytes.length >= 4) {
      if (bytes[0] == 0x25 && bytes[1] == 0x50 && bytes[2] == 0x44 && bytes[3] == 0x46) {
        return 'pdf';
      }
      if (bytes[0] == 0x89 && bytes[1] == 0x50 && bytes[2] == 0x4E) return 'image';
      if (bytes[0] == 0xFF && bytes[1] == 0xD8) return 'image';
      if (bytes[0] == 0x47 && bytes[1] == 0x49 && bytes[2] == 0x46) return 'image';
      if (bytes[0] == 0x42 && bytes[1] == 0x4D) return 'image';
      if (bytes[0] == 0x50 && bytes[1] == 0x4B) return 'zip';
    }
    if (bytes.length >= 12) {
      final riff = String.fromCharCodes(bytes.sublist(0, 4));
      final webp = String.fromCharCodes(bytes.sublist(8, 12));
      if (riff == 'RIFF' && webp == 'WEBP') return 'image';
    }
    return 'unknown';
  }

  Future<void> _cleanOrphanParts(Directory dir) async {
    try {
      await for (final entity in dir.list(recursive: true)) {
        if (entity is File && entity.path.endsWith('.part')) {
          try {
            await entity.delete();
          } on FileSystemException {
            // Ignore.
          }
        }
      }
    } on FileSystemException {
      // Ignore.
    }
  }

  Future<Map<String, dynamic>?> _readMeta(File asset) async {
    final meta = File('${asset.path}.json');
    if (!meta.existsSync()) return null;
    try {
      final decoded = jsonDecode(await meta.readAsString());
      return decoded is Map ? decoded.cast<String, dynamic>() : null;
    } catch (_) {
      return null;
    }
  }

  /// Byte-budgeted LRU: large manuals are never retained in memory.
  void _remember(String key, Uint8List bytes) {
    if (bytes.length > policy.memoryEntryMaxBytes) return;
    final previous = _memory.remove(key);
    if (previous != null) _memoryBytes -= previous.length;
    _memory[key] = bytes;
    _memoryBytes += bytes.length;

    while (_memoryBytes > policy.memoryBudgetBytes && _memory.isNotEmpty) {
      final oldest = _memory.keys.first;
      _memoryBytes -= _memory.remove(oldest)?.length ?? 0;
    }
  }

  void _forget(String key) {
    _memoryBytes -= _memory.remove(key)?.length ?? 0;
  }

  static String _hash(String value) =>
      sha256.convert(utf8.encode(value)).toString();

  static String _extensionFor(Uri uri, MediaKind kind) {
    final path = uri.path;
    final dot = path.lastIndexOf('.');
    if (dot >= 0 && dot < path.length - 1) {
      final extension = path.substring(dot).toLowerCase();
      if (extension.length <= 6 && RegExp(r'^\.[a-z0-9]+$').hasMatch(extension)) {
        return extension;
      }
    }
    return kind == MediaKind.manual ? '.pdf' : '.img';
  }

  static String _contentTypeFor(Uri uri, MediaKind kind) {
    final lower = uri.path.toLowerCase();
    if (lower.endsWith('.png')) return 'image/png';
    if (lower.endsWith('.jpg') || lower.endsWith('.jpeg')) return 'image/jpeg';
    if (lower.endsWith('.webp')) return 'image/webp';
    if (lower.endsWith('.gif')) return 'image/gif';
    if (lower.endsWith('.pdf')) return 'application/pdf';
    return kind == MediaKind.manual ? 'application/octet-stream' : 'image/*';
  }
}

/// Default cache location: the per-user application support directory.
///
/// Android: `/data/user/0/<pkg>/files/lab_assets` (persistent, unlike the OS
/// cache which can be purged at any moment). Windows:
/// `%APPDATA%\<app>\lab_assets`. Linux: `~/.local/share/<app>/lab_assets`.
Future<Directory> defaultAssetCacheDirectory() async {
  final base = await getApplicationSupportDirectory();
  return Directory('${base.path}/lab_assets');
}
