import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:cookie_jar/cookie_jar.dart';
import 'package:dio/dio.dart';
import 'package:dio_cookie_manager/dio_cookie_manager.dart';
import 'package:logger/logger.dart';

import '../config/odoo_config.dart';
import '../models/lab_api_exception.dart';
import '../models/odoo_exception.dart';
import 'auth_gateway.dart';
import 'dio_interceptor.dart';

final logger = Logger();

/// Business codes that mean "the session is gone", not "the request was bad".
const _sessionInvalidCodes = <String>{
  'SESSION_INVALID',
  'SESSION_EXPIRED',
  'NOT_AUTHENTICATED',
  'AUTH_REQUIRED',
};

/// Odoo's own JSON-RPC code for `SessionExpiredException`.
const int _odooSessionExpiredCode = 100;

/// Redirect hops allowed while fetching one same-origin asset.
const int _maxAssetRedirects = 5;

/// Core Odoo JSON-RPC client.
///
/// Handles authentication, RPC calls, and field probing.
/// This is the foundation for all Odoo communication.
///
/// Session model:
///   1. [authenticate] posts the credentials to `/web/session/authenticate`.
///      Odoo answers with the user id and a `session_id` cookie.
///   2. `CookieManager` keeps that cookie in [_cookieJar] and replays it on
///      every following request, so [executeKw] needs no password.
///   3. [logout] destroys the server-side session and drops the local cookie.
///
/// [baseUrl] and [database] are mutable so the login screen can point one
/// client instance at whatever server the operator typed in ([configure]).
class OdooClient implements AuthGateway {
  @override
  String baseUrl;
  @override
  String database;

  late final Dio _dio;
  late final CookieJar _cookieJar;
  int? _uid;
  final _updateEvents = StreamController<void>.broadcast();
  Stream<void> get updateConnectionEvents => _updateEvents.stream;
  int _activeRpc = 0;
  bool get hasActiveRequests => _activeRpc > 0;
  bool _clientInstallPending = false;
  bool beginClientInstall() {
    if (hasActiveRequests || _clientInstallPending) return false;
    _clientInstallPending = true; return true;
  }
  void endClientInstall() { _clientInstallPending = false; }

  /// Request counter for the JSON-RPC `id` field (diagnostics only).
  int _requestSeq = 0;

  void Function()? _onSessionInvalid;

  /// Invoked when the server reports that the session cookie is no longer
  /// valid. Wired by the auth layer so the app can return to the login screen.
  /// It is only a notification: no automatic sign-in is triggered.
  @override
  set onSessionInvalid(void Function()? handler) => _onSessionInvalid = handler;

  @override
  bool get isAuthenticated => _uid != null;
  @override
  int? get uid => _uid;

  OdooClient({
    String? baseUrl,
    String? database,
  })  : baseUrl =
            OdooConfig.normalizeBaseUrl(baseUrl ?? OdooConfig.defaultBaseUrl),
        database = (database ?? OdooConfig.defaultDatabase).trim() {
    _initializeDio();
  }

  /// Repoints this client at another server/database and forgets any session.
  ///
  /// Called by the login flow with the values typed on the login screen.
  @override
  void configure({required String baseUrl, required String database}) {
    final normalized = OdooConfig.normalizeBaseUrl(baseUrl);
    final trimmedDb = database.trim();

    if (!OdooConfig.isValidBaseUrl(normalized)) {
      throw OdooValidationException(
        'Invalid Odoo server URL: "$baseUrl". Expected http://host:port.',
      );
    }
    if (trimmedDb.isEmpty) {
      throw OdooValidationException('Odoo database name must not be empty.');
    }

    this.baseUrl = normalized;
    this.database = trimmedDb;
    _dio.options.baseUrl = normalized;

    // A different server means a different session. The jar is in-memory, so
    // the wipe is not awaited; a failure here cannot corrupt anything.
    _uid = null;
    unawaited(_cookieJar.deleteAll());
  }

  void _initializeDio() {
    _dio = Dio(
      BaseOptions(
        baseUrl: baseUrl,
        connectTimeout: Duration(seconds: OdooConfig.requestTimeout),
        receiveTimeout: Duration(seconds: OdooConfig.rpcTimeout),
        contentType: 'application/json',
      ),
    );

    // Session cookie jar. In-memory on purpose: nothing is written to disk and
    // the operator signs in again after a restart.
    _cookieJar = CookieJar();
    _dio.interceptors.add(CookieManager(_cookieJar));

    // Odoo-specific error translation / logging.
    _dio.interceptors.add(OdooInterceptor());
    // Track before translators: an earlier handler.reject can short-circuit
    // following error interceptors and otherwise leave the install gate busy.
    _dio.interceptors.insert(0, InterceptorsWrapper(
      onRequest: (options, handler) {
        if (_clientInstallPending) {
          handler.reject(DioException(requestOptions: options, error: '安装更新期间暂停服务器操作'));
          return;
        }
        _activeRpc++; handler.next(options);
      },
      onResponse: (response, handler) {
        if (_activeRpc > 0) _activeRpc--;
        _updateEvents.add(null);
        handler.next(response);
      },
      onError: (error, handler) {
        if (_activeRpc > 0) _activeRpc--;
        if (error.requestOptions.path.contains('/lab/client/updates/assets/') &&
            [401, 302, 303].contains(error.response?.statusCode)) {
          _notifySessionInvalid();
        }
        handler.next(error);
      },
    ));
  }

  Future<void> downloadClientUpdate({required String server, required String path,
      required File target, required int expectedBytes, required CancelToken token,
      required void Function(int) onProgress}) async {
    final base = Uri.parse(baseUrl);
    final uri = Uri.parse(server).resolve(path);
    if (server != baseUrl || !_isSameOrigin(uri, base) ||
        !path.startsWith('/lab/client/updates/assets/') || !isAuthenticated) {
      throw StateError('请连接当前服务器并登录后下载');
    }
    final response = await _dio.get<ResponseBody>(uri.toString(), cancelToken: token,
        options: Options(responseType: ResponseType.stream, followRedirects: false,
            validateStatus: (code) => code == 200));
    final declared = int.tryParse(response.headers.value('content-length') ?? '');
    if (declared != null && declared != expectedBytes) throw const FormatException('安装包大小不符');
    final output = target.openWrite();
    var received = 0;
    try {
      await for (final chunk in response.data!.stream) {
        if (token.isCancelled) throw token.cancelError!;
        if (baseUrl != server || !isAuthenticated) throw StateError('登录或服务器已切换');
        received += chunk.length;
        if (received > expectedBytes) throw const FormatException('安装包超过声明大小');
        output.add(chunk);
        onProgress(received);
      }
      await output.flush();
      if (received != expectedBytes) throw const FormatException('安装包下载不完整');
    } finally { await output.close(); }
  }

  void _ensureConfigured() {
    if (baseUrl.isEmpty) {
      throw OdooValidationException(
        'No Odoo server configured. Pass --dart-define=LAB_ODOO_URL=... at '
        'build time, or fill in the server field on the login screen.',
      );
    }
    if (database.isEmpty) {
      throw OdooValidationException(
        'No Odoo database configured. Pass --dart-define=LAB_ODOO_DB=... at '
        'build time, or fill in the database field on the login screen.',
      );
    }
  }

  /// Authenticate with Odoo using username and password.
  ///
  /// Returns the user ID (uid) on success.
  /// Throws [OdooAuthException] on failure.
  ///
  /// The password is used for this one request and is never logged: the request
  /// body is not logged either (see dio_interceptor.dart).
  @override
  Future<int> authenticate(String login, String password) async {
    try {
      _ensureConfigured();

      logger.i('Authenticating as $login...');

      final response = await _dio.post(
        OdooConfig.authPath,
        data: {
          'jsonrpc': '2.0',
          'params': {
            'db': database,
            'login': login,
            'password': password,
          },
        },
      );

      final result = response.data['result'];
      if (result == null || result['uid'] == null) {
        throw OdooAuthException(
          'Authentication response missing UID. Response: $result',
        );
      }

      _uid = result['uid'] as int;
      logger.i('Authentication successful. UID: $_uid');

      return _uid!;
    } on OdooException {
      rethrow;
    } on DioException catch (e) {
      // A transport failure is NOT a rejected password: reporting it as an
      // authentication error sends the operator looking for the wrong problem
      // (and, on Android, hides the real cause - a cleartext HTTP address that
      // the platform's network security config refuses).
      if (_isTransportFailure(e)) {
        throw OdooNetworkException(
          '无法连接服务器。${_cleartextHint()}',
          originalError: e,
        );
      }
      throw OdooAuthException(
        'Failed to authenticate: ${redactForLog(e.message ?? '')}',
        originalError: e.error,
      );
    } catch (e) {
      throw OdooAuthException(
        'Unexpected authentication error: ${redactForLog(e.toString())}',
        originalError: e,
      );
    }
  }

  /// Fetches one SAME-ORIGIN asset (captured image / datasheet) with the session.
  ///
  /// The unified UI caches images and manuals; a reference such as
  /// `/lab/api/asset/...` is only readable with `session_id`, so the auth layer
  /// supplies this fetcher to `assetAuthenticatedFetcherProvider` (see main.dart).
  /// It uses the same [Dio] and the same [_cookieJar] as [callRoute] - a second
  /// jar would send the request anonymously and the server would answer 404/401.
  ///
  /// SECURITY - all three rules are enforced here, not by the caller:
  ///   * only this client's own origin is accepted (relative paths are resolved
  ///     against [baseUrl]); an absolute URL to another host is refused;
  ///   * redirects are followed MANUALLY and every hop is re-checked, so a
  ///     `302` to a foreign host cannot carry the session cookie off-site;
  ///   * the request is never anonymous-by-accident either: a missing session is
  ///     reported as a dead session instead of a silent 404.
  ///
  /// A 401 / session-expired answer is reported like any other dead session.
  Future<Uint8List> fetchAssetBytes(Uri uri) async {
    _ensureConfigured();

    final base = Uri.tryParse(baseUrl);
    if (base == null || base.host.isEmpty) {
      throw const LabApiException(
        code: 'BAD_REQUEST',
        message: '尚未配置服务器地址，无法加载图片或手册。',
      );
    }

    var current = uri.hasScheme ? uri : base.resolveUri(uri);
    if (!_isSameOrigin(current, base)) {
      throw const LabApiException(
        code: 'FORBIDDEN_HOST',
        message: '只能携带登录会话访问本机服务器上的资源。',
      );
    }
    if (!isAuthenticated) {
      _notifySessionInvalid();
      throw const LabSessionExpiredException(
        code: 'NOT_AUTHENTICATED',
        message: '尚未登录或登录状态已失效，请重新登录。',
      );
    }

    for (var hop = 0; hop <= _maxAssetRedirects; hop++) {
      final Response<List<int>> response;
      try {
        response = await _dio.get<List<int>>(
          current.toString(),
          options: Options(
            responseType: ResponseType.bytes,
            // Followed by hand so each hop's origin can be checked before the
            // cookie jar is allowed to answer again.
            followRedirects: false,
            validateStatus: (status) => status != null && status < 400,
          ),
        );
      } on DioException catch (e) {
        throw _businessFailure(e, path: current.path);
      }

      final status = response.statusCode ?? 0;
      if (status >= 300 && status < 400) {
        // Header lookup is case-insensitive in Dio's Headers.
        final location = response.headers.value('location');
        if (location == null || location.isEmpty) {
          throw LabApiException(
            code: 'BAD_RESPONSE',
            message: '服务器返回了无跳转地址的重定向。',
            statusCode: status,
          );
        }
        final next = current.resolve(location);
        if (!_isSameOrigin(next, base)) {
          throw const LabApiException(
            code: 'FORBIDDEN_HOST',
            message: '资源被重定向到其它站点，已拒绝携带登录会话。',
          );
        }
        current = next;
        continue;
      }

      final bytes = response.data;
      if (bytes == null || bytes.isEmpty) {
        throw LabApiException(
          code: 'EMPTY_ASSET',
          message: '服务器没有返回该图片或手册内容。',
          statusCode: response.statusCode,
        );
      }
      return Uint8List.fromList(bytes);
    }

    throw const LabApiException(
      code: 'TOO_MANY_REDIRECTS',
      message: '资源跳转次数过多，已停止加载。',
    );
  }

  /// True when [candidate] addresses exactly the same scheme/host/port as [base].
  static bool _isSameOrigin(Uri candidate, Uri base) {
    if (candidate.scheme != 'http' && candidate.scheme != 'https') return false;
    return candidate.scheme == base.scheme &&
        candidate.host == base.host &&
        candidate.port == base.port;
  }

  /// Calls a business endpoint defined by `lc_elc/docs/business_api_contract.json`.
  ///
  /// Transport is the SAME [Dio] instance and the SAME [_cookieJar] as
  /// [authenticate]: a second cookie jar would silently drop `session_id` and
  /// turn every business call into an anonymous one. The request is a plain
  /// Odoo `type="jsonrpc"` call
  /// (`{"jsonrpc":"2.0","method":"call","id":...,"params":{...}}`) because these
  /// controllers bind their arguments by name, unlike `/web/dataset/call_kw`.
  ///
  /// The server answers `{"result": {"ok": bool, "data": ..., "error": ...}}`:
  ///   * `ok == true`  -> `data` is returned (empty map when there is none);
  ///   * `ok == false` -> [LabApiException] with the server `code` and its
  ///                      Chinese `message`; `data` is NEVER returned;
  ///   * no `result` (JSON-RPC error, Odoo AccessError/UserError) -> failure;
  ///   * HTTP 401 or an Odoo session-expired error -> [LabSessionExpiredException],
  ///     and [onSessionInvalid] fires so the app can go back to the login
  ///     screen. Nothing is retried here - a dead session must not become a
  ///     request loop.
  ///
  /// Not part of [AuthGateway]: any screen or provider that needs business data
  /// uses [odooClientProvider] and calls this. Tests can subclass [OdooClient]
  /// and override this one method (constructing the client opens no socket).
  Future<Map<String, dynamic>> callRoute(
    String path,
    Map<String, dynamic> params,
  ) async {
    _ensureConfigured();

    final routePath = path.trim();
    if (routePath.isEmpty) {
      throw const LabApiException(
        code: 'BAD_REQUEST',
        message: '接口路径为空。',
      );
    }

    if (!isAuthenticated) {
      // An anonymous business call must never leave this client.
      _notifySessionInvalid();
      throw const LabSessionExpiredException(
        code: 'NOT_AUTHENTICATED',
        message: '尚未登录或登录状态已失效，请重新登录。',
      );
    }

    final Response<dynamic> response;
    try {
      response = await _dio.post<dynamic>(
        routePath,
        data: <String, dynamic>{
          'jsonrpc': '2.0',
          'method': 'call',
          'id': 'lc-elc-${++_requestSeq}',
          'params': params,
        },
      );
    } on DioException catch (e) {
      throw _businessFailure(e, path: routePath);
    }

    final body = response.data;
    if (body is! Map) {
      throw LabApiException(
        code: 'BAD_RESPONSE',
        message: '服务器返回了非预期的响应格式。',
        statusCode: response.statusCode,
      );
    }

    // A JSON-RPC level error is a failure, never a result.
    if (!body.containsKey('result')) {
      throw _failureFromRpcError(
        body['error'],
        statusCode: response.statusCode,
        path: routePath,
      );
    }

    final result = body['result'];
    if (result is! Map) {
      throw LabApiException(
        code: 'BAD_RESPONSE',
        message: '服务器未返回业务数据。',
        statusCode: response.statusCode,
      );
    }

    if (result['ok'] == true) {
      final data = result['data'];
      if (data == null) return <String, dynamic>{};
      if (data is Map<String, dynamic>) return data;
      if (data is Map) {
        return data.map((key, value) => MapEntry(key.toString(), value));
      }
      throw LabApiException(
        code: 'BAD_RESPONSE',
        message: '业务数据格式不正确。',
        statusCode: response.statusCode,
      );
    }

    // ok is false, missing or malformed: report the server's own error.
    throw LabApiException.fromEnvelope(
      result['error'],
      statusCode: response.statusCode,
    );
  }

  /// True when a [DioException] is a transport problem rather than a rejection.
  static bool _isTransportFailure(DioException error) {
    if (error.error is OdooNetworkException) return true;
    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      case DioExceptionType.transformTimeout:
      case DioExceptionType.connectionError:
      case DioExceptionType.badCertificate:
        return true;
      case DioExceptionType.badResponse:
      case DioExceptionType.cancel:
      case DioExceptionType.unknown:
        return false;
    }
  }

  /// Short operator-facing explanation when this client is pointed at a
  /// cleartext HTTP address on a platform that only permits HTTP for the
  /// configured intranet server.
  ///
  /// It explains the rule; it does NOT change it - the Android network security
  /// config stays strict (`base-config cleartextTrafficPermitted="false"` plus
  /// one explicit intranet domain), and no host allowlist is duplicated here.
  String _cleartextHint() {
    if (!Platform.isAndroid) return '';
    if (!baseUrl.startsWith('http://')) return '';
    return '当前地址使用 HTTP。Android 只允许已配置的内网服务器使用 HTTP，'
        '其它地址请改用 HTTPS。';
  }

  /// Maps a transport/JSON-RPC failure onto a business exception.
  LabApiException _businessFailure(DioException error, {required String path}) {
    final status = error.response?.statusCode;

    if (status == 401) {
      _notifySessionInvalid();
      return LabSessionExpiredException(
        statusCode: status,
        originalError: error,
      );
    }

    final inner = error.error;
    if (inner is OdooRpcException) {
      if (_isSessionError(inner.rpcErrorCode, inner.message)) {
        _notifySessionInvalid();
        return LabSessionExpiredException(originalError: error);
      }
      // Odoo puts the human-readable text (often Chinese) in `data.message`;
      // the top-level `message` is only a category such as "Odoo Server Error".
      final detail = inner.rpcErrorData;
      final text = (detail != null && detail.isNotEmpty)
          ? detail
          : inner.message;
      return LabApiException(
        code: 'RPC_ERROR',
        message: redactForLog(text),
        statusCode: status,
        originalError: error,
      );
    }

    if (inner is OdooNetworkException ||
        error.type == DioExceptionType.connectionTimeout ||
        error.type == DioExceptionType.receiveTimeout ||
        error.type == DioExceptionType.sendTimeout ||
        error.type == DioExceptionType.connectionError) {
      return LabApiException(
        code: 'NETWORK_ERROR',
        message: '无法连接服务器。${_cleartextHint()}',
        statusCode: status,
        originalError: error,
      );
    }

    return LabApiException(
      code: 'TRANSPORT_ERROR',
      message: redactForLog(error.message ?? '请求失败。'),
      statusCode: status,
      originalError: error,
    );
  }

  /// Safety net for a response that reached us without the interceptor
  /// rewriting it (the interceptor normally turns `error` bodies into
  /// [OdooRpcException]).
  LabApiException _failureFromRpcError(
    Object? rpcError, {
    required int? statusCode,
    required String path,
  }) {
    if (rpcError is Map) {
      final data = rpcError['data'];
      final detail = data is Map ? data['message']?.toString() : null;
      final code = rpcError['code'];
      final message = detail ?? rpcError['message']?.toString();

      if (_isSessionError(code is int ? code : null, message)) {
        _notifySessionInvalid();
        return LabSessionExpiredException(
          statusCode: statusCode,
          originalError: rpcError,
        );
      }

      return LabApiException(
        code: code == null ? 'RPC_ERROR' : 'RPC_ERROR_$code',
        message: (message == null || message.isEmpty)
            ? '服务器拒绝了本次请求。'
            : redactForLog(message),
        statusCode: statusCode,
        originalError: rpcError,
      );
    }

    return LabApiException(
      code: 'BAD_RESPONSE',
      message: '服务器返回了无法识别的错误信息。',
      statusCode: statusCode,
      originalError: rpcError,
    );
  }

  bool _isSessionError(int? rpcCode, String? message) {
    if (rpcCode == _odooSessionExpiredCode) return true;
    if (message == null) return false;

    // A server that reports the failure by code in the message text
    // (e.g. "SESSION_INVALID") is treated the same way as a 401.
    final upper = message.toUpperCase();
    for (final code in _sessionInvalidCodes) {
      if (upper.contains(code)) return true;
    }

    final lowered = message.toLowerCase();
    if (lowered.contains('session') &&
        (lowered.contains('expired') ||
            lowered.contains('invalid') ||
            lowered.contains('not valid'))) {
      return true;
    }
    return false;
  }

  /// Tells the auth layer that the session is gone.
  ///
  /// The uid is dropped first, so any further business call fails fast as
  /// `NOT_AUTHENTICATED` instead of hammering the server.
  void _notifySessionInvalid() {
    _uid = null;
    final handler = _onSessionInvalid;
    if (handler == null) return;
    try {
      handler();
    } catch (e) {
      logger.w('session-invalid handler failed: ${redactForLog(e.toString())}');
    }
  }

  /// Execute an Odoo ORM method through `/web/dataset/call_kw`.
  ///
  /// The session cookie installed by [authenticate] authorises the call, so no
  /// password travels in the payload.
  Future<T> executeKw<T>(
    String model,
    String method,
    List<dynamic> args, {
    Map<String, dynamic> kwargs = const {},
  }) async {
    if (!isAuthenticated) {
      throw OdooException('Not authenticated. Call authenticate() first.');
    }

    try {
      // Call signature only. Request bodies are never logged: the
      // authentication body carries the password, and RPC bodies carry record
      // data.
      logger.d('Calling $model.$method '
          '(args=${args.length}, kwargs=${kwargs.length})');

      final response = await _dio.post(
        OdooConfig.callKwPath,
        data: {
          'jsonrpc': '2.0',
          'method': 'call',
          'params': {
            'model': model,
            'method': method,
            'args': args,
            'kwargs': kwargs,
          },
        },
      );

      final result = response.data['result'];
      logger.d('Result: ${_describeResult(result)}');

      return result as T;
    } on DioException catch (e) {
      if (e.error is OdooRpcException) {
        rethrow;
      }
      throw OdooNetworkException(
        'RPC call failed: ${redactForLog(e.message ?? '')}',
        originalError: e,
      );
    } catch (e) {
      throw OdooException(
        'Unexpected RPC error: ${redactForLog(e.toString())}',
        originalError: e,
      );
    }
  }

  /// Backwards-compatible alias for the original snake_case API.
  ///
  /// Existing call sites use `execute_kw(...)`; kept so screens and providers
  /// do not have to change.
  Future<T> execute_kw<T>(
    String model,
    String method,
    List<dynamic> args, {
    Map<String, dynamic> kwargs = const {},
  }) =>
      executeKw<T>(model, method, args, kwargs: kwargs);

  /// Search and read records from a model.
  Future<List<Map<String, dynamic>>> search_read(
    String model,
    List<dynamic> domain,
    List<String> fields, {
    int limit = 100,
    int offset = 0,
    String order = '',
  }) async {
    try {
      final result = await executeKw<dynamic>(
        model,
        'search_read',
        [domain],
        kwargs: {
          'fields': fields,
          'limit': limit,
          'offset': offset,
          if (order.isNotEmpty) 'order': order,
        },
      );

      final records = (result as List?)?.cast<Map<String, dynamic>>() ?? [];
      logger.d('search_read returned ${records.length} records');

      return records;
    } catch (e) {
      logger.e('search_read failed: $e');
      rethrow;
    }
  }

  /// Count records matching a domain.
  Future<int> search_count(
    String model,
    List<dynamic> domain,
  ) async {
    try {
      final result = await executeKw<dynamic>(model, 'search_count', [domain]);
      return (result as num?)?.toInt() ?? 0;
    } catch (e) {
      logger.e('search_count failed: $e');
      rethrow;
    }
  }

  /// Search for records (returns IDs only).
  Future<List<int>> search(
    String model,
    List<dynamic> domain, {
    int limit = 0,
    int offset = 0,
    String order = '',
  }) async {
    try {
      final result = await executeKw<dynamic>(
        model,
        'search',
        [domain],
        kwargs: {
          'limit': limit,
          'offset': offset,
          if (order.isNotEmpty) 'order': order,
        },
      );

      return (result as List?)?.cast<int>() ?? [];
    } catch (e) {
      logger.e('search failed: $e');
      rethrow;
    }
  }

  /// Read records by ID with specified fields.
  Future<List<Map<String, dynamic>>> read(
    String model,
    List<int> ids,
    List<String> fields,
  ) async {
    try {
      final result = await executeKw<dynamic>(
        model,
        'read',
        [ids],
        kwargs: {'fields': fields},
      );

      return (result as List?)?.cast<Map<String, dynamic>>() ?? [];
    } catch (e) {
      logger.e('read failed: $e');
      rethrow;
    }
  }

  /// Create a new record.
  Future<int> create(
    String model,
    Map<String, dynamic> values,
  ) async {
    try {
      final result = await executeKw<dynamic>(model, 'create', [values]);
      return (result as num).toInt();
    } catch (e) {
      logger.e('create failed: $e');
      rethrow;
    }
  }

  /// Update records.
  Future<void> write(
    String model,
    List<int> ids,
    Map<String, dynamic> values,
  ) async {
    try {
      await executeKw<dynamic>(model, 'write', [ids, values]);
    } catch (e) {
      logger.e('write failed: $e');
      rethrow;
    }
  }

  /// Delete records.
  Future<void> unlink(
    String model,
    List<int> ids,
  ) async {
    try {
      await executeKw<dynamic>(model, 'unlink', [ids]);
    } catch (e) {
      logger.e('unlink failed: $e');
      rethrow;
    }
  }

  /// Get field definitions for a model.
  Future<Map<String, dynamic>> fields_get(
    String model, {
    List<String> attributes = const [],
  }) async {
    try {
      logger.i('Probing fields on model: $model');

      final result = await executeKw<dynamic>(
        model,
        'fields_get',
        const [],
        kwargs: {
          if (attributes.isNotEmpty) 'attributes': attributes,
        },
      );

      final fields = (result as Map).cast<String, dynamic>();
      logger.d('Found ${fields.length} fields on $model');

      return fields;
    } catch (e) {
      logger.e('fields_get failed for $model: $e');
      throw OdooFieldException('Failed to probe fields on $model: $e');
    }
  }

  /// Check if specific fields exist on a model.
  ///
  /// Returns a map of field names to their type. Missing fields are omitted.
  Future<Map<String, String>> checkFieldsExist(
    String model,
    List<String> fieldNames,
  ) async {
    try {
      final allFields = await fields_get(model);
      final result = <String, String>{};

      for (final fieldName in fieldNames) {
        if (allFields.containsKey(fieldName)) {
          final fieldDef = allFields[fieldName];
          result[fieldName] = fieldDef is Map
              ? (fieldDef['type']?.toString() ?? 'unknown')
              : 'unknown';
        }
      }

      logger.d('Field check for $model: '
          '${result.length}/${fieldNames.length} exist');

      return result;
    } catch (e) {
      logger.e('checkFieldsExist failed: $e');
      rethrow;
    }
  }

  /// Name search (auto-completion search).
  Future<List<List<dynamic>>> name_search(
    String model,
    String name, {
    List<dynamic> domain = const [],
    String operator = 'ilike',
    int limit = 8,
  }) async {
    try {
      final result = await executeKw<dynamic>(
        model,
        'name_search',
        [name],
        kwargs: {
          'args': domain,
          'operator': operator,
          'limit': limit,
        },
      );

      return (result as List?)?.cast<List<dynamic>>() ?? [];
    } catch (e) {
      logger.e('name_search failed: $e');
      rethrow;
    }
  }

  /// Call a custom method on a specific record.
  Future<T> call_method<T>(
    String model,
    int recordId,
    String method,
    List<dynamic> args, {
    Map<String, dynamic> kwargs = const {},
  }) async {
    try {
      return await executeKw<T>(
        model,
        method,
        [recordId, ...args],
        kwargs: kwargs,
      );
    } catch (e) {
      logger.e('call_method failed: $e');
      rethrow;
    }
  }

  /// Logout and clear the local session cookie.
  @override
  Future<void> logout() async {
    try {
      await _dio.post(OdooConfig.sessionDestroyPath);
    } catch (e) {
      logger.w('Logout error (non-critical): ${redactForLog(e.toString())}');
    } finally {
      _uid = null;
      await _cookieJar.deleteAll();
    }
  }

  /// Drops the in-memory session (uid + `session_id` cookie) WITHOUT touching
  /// the network.
  ///
  /// Used when a remembered password is no longer considered fresh: a stale
  /// credential must not leave a usable session behind, and that decision path
  /// must not contact the server at all.
  @override
  void resetLocalSession() {
    _uid = null;
    // The jar is in-memory only, so this cannot fail in a way that matters.
    unawaited(_cookieJar.deleteAll());
  }
}

/// Compact, non-revealing description of an RPC result for debug logging.
///
/// Full payloads are deliberately never logged: `fields_get` returns hundreds
/// of field definitions, and record payloads are arbitrarily large.
String _describeResult(Object? result) {
  if (result == null) return 'null';
  if (result is bool || result is num) return '$result';
  if (result is String) {
    return result.length <= 80 ? result : 'String(${result.length} chars)';
  }
  if (result is List) return 'List(${result.length})';
  if (result is Map) return 'Map(${result.length} keys)';
  return result.runtimeType.toString();
}
