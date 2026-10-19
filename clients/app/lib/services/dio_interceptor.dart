import 'package:dio/dio.dart';
import 'package:logger/logger.dart';

import '../models/odoo_exception.dart';

final logger = Logger();

/// Header names whose values must never reach a log sink.
///
/// `cookie` carries the Odoo `session_id`, which is a bearer credential:
/// anyone holding it can act as the signed-in user until it expires.
const _sensitiveHeaders = <String>{
  'cookie',
  'set-cookie',
  'authorization',
  'proxy-authorization',
  'x-api-key',
  'x-auth-token',
};

/// Masks anything that looks like a credential in [text].
///
/// This is a last line of defence for strings we do not fully control (Dio
/// error text, URLs). Request bodies are never logged in the first place: the
/// payload posted to `/web/session/authenticate` contains the account password.
String redactForLog(String text) {
  var out = text;

  // JSON style: {"password":"..."} / {"token":"..."}
  out = out.replaceAllMapped(
    RegExp(r'("(?:password|passwd|pwd|token|api[_-]?key)"\s*:\s*)"[^"]*"',
        caseSensitive: false),
    (m) => '${m.group(1)}"***"',
  );

  // Query/header style: password=... / api_key=...
  out = out.replaceAllMapped(
    RegExp(r'\b(password|passwd|pwd|token|api[_-]?key)=([^&\s;]+)',
        caseSensitive: false),
    (m) => '${m.group(1)}=***',
  );

  // Odoo session cookie value.
  out = out.replaceAllMapped(
    RegExp(r'\bsession_id=([^;&\s]+)', caseSensitive: false),
    (m) => 'session_id=***',
  );

  return out;
}

/// Header names only, with sensitive names marked and never valued.
///
/// Enough to answer "was the session cookie actually attached?" without ever
/// writing the cookie itself into a log file.
List<String> printableHeaderNames(Map<String, dynamic>? headers) {
  if (headers == null || headers.isEmpty) return const <String>[];
  final names = headers.keys.map((k) => k.toLowerCase()).toSet().toList()
    ..sort();
  return names
      .map((name) => _sensitiveHeaders.contains(name) ? '$name=[redacted]' : name)
      .toList();
}

/// Interceptor for Odoo-specific behaviour:
/// - error response parsing
/// - request/response logging that is safe to keep switched on
///
/// LOGGING POLICY - do not weaken this:
///   * request and response BODIES are never logged. The authentication body
///     contains the account password, and RPC bodies contain record data.
///   * header VALUES are never logged. Use [printableHeaderNames] if you need
///     to see which headers were sent.
///   * only method + path + status code may be emitted verbatim.
class OdooInterceptor extends Interceptor {
  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    logger.d('-> ${options.method} ${options.baseUrl}${options.path}');
    handler.next(options);
  }

  @override
  void onResponse(Response response, ResponseInterceptorHandler handler) {
    logger.d('<- ${response.statusCode} ${response.requestOptions.path}');

    // Check for an Odoo JSON-RPC error response.
    if (response.data is Map && response.data.containsKey('error')) {
      final errorData = response.data['error'];
      final errorCode = errorData['code'];
      final errorMessage = errorData['message'] ?? 'Unknown error';
      final errorDetails = errorData['data']?['message'] ?? '';

      logger.e('Odoo RPC Error: $errorMessage (code: $errorCode)');
      logger.e('Details: ${redactForLog(errorDetails.toString())}');

      handler.reject(
        DioException(
          requestOptions: response.requestOptions,
          response: response,
          type: DioExceptionType.unknown,
          error: OdooRpcException(
            '$errorMessage',
            rpcErrorCode: errorCode is int ? errorCode : null,
            rpcErrorData: '$errorDetails',
          ),
        ),
      );
      return;
    }

    handler.next(response);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    logger.e('X ${err.requestOptions.method} ${err.requestOptions.path}');
    logger.e('  Error: ${redactForLog(err.message ?? '')}');
    logger.e('  Type: ${err.type}');

    final headerNames = printableHeaderNames(err.requestOptions.headers);
    if (headerNames.isNotEmpty) {
      final joinedNames = headerNames.join(', ');
      logger.e('  Request headers (names only): $joinedNames');
    }

    if (err.response != null) {
      logger.e('  Status: ${err.response!.statusCode}');
    }

    // Convert DioException to OdooException.
    late OdooException odooError;

    if (err.type == DioExceptionType.connectionTimeout ||
        err.type == DioExceptionType.receiveTimeout ||
        err.type == DioExceptionType.sendTimeout) {
      odooError = OdooNetworkException(
        'Connection timeout. Please check Odoo server.',
        originalError: err,
      );
    } else if (err.response?.statusCode == 401) {
      odooError = OdooAuthException(
        'Authentication failed. Session expired?',
        originalError: err,
      );
    } else if (err.response?.statusCode == 404) {
      odooError = OdooException(
        'Odoo server not found at ${err.requestOptions.baseUrl}',
        originalError: err,
      );
    } else if (err.response?.statusCode == 500) {
      odooError = OdooRpcException(
        'Odoo server error (500)',
        originalError: err,
      );
    } else {
      odooError = OdooNetworkException(
        redactForLog(err.message ?? 'Network error'),
        originalError: err,
      );
    }

    handler.reject(
      DioException(
        requestOptions: err.requestOptions,
        response: err.response,
        type: err.type,
        error: odooError,
      ),
    );
  }
}
