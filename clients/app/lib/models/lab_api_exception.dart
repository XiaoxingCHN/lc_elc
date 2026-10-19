/// Errors returned by the Odoo `/lab/api/...` business endpoints.
///
/// The business envelope is fixed by `lc_elc/docs/business_api_contract.json`:
///
///   success: {"ok": true,  "data": {...}, "error": null}
///   failure: {"ok": false, "data": null,  "error": {"code": "...",
///                                                    "message": "<Chinese>",
///                                                    "fields": {}}}
///
/// A failure must NEVER be surfaced as data, and a JSON-RPC level error
/// (`{"error": {...}}` instead of `{"result": ...}`) must never be mistaken for
/// success either. [OdooClient.callRoute] enforces both.
class LabApiException implements Exception {
  const LabApiException({
    required this.code,
    required this.message,
    this.fields = const <String, dynamic>{},
    this.statusCode,
    this.originalError,
  });

  /// Builds an exception from the contract's `error` object.
  factory LabApiException.fromEnvelope(
    Object? envelope, {
    int? statusCode,
    Object? originalError,
  }) {
    if (envelope is Map) {
      final code = envelope['code']?.toString();
      final message = envelope['message']?.toString();
      final fields = envelope['fields'];
      return LabApiException(
        code: (code == null || code.isEmpty) ? 'UNKNOWN_ERROR' : code,
        message: (message == null || message.isEmpty)
            ? '服务器拒绝了本次操作。'
            : message,
        fields: fields is Map
            ? fields.map((key, value) => MapEntry(key.toString(), value))
            : const <String, dynamic>{},
        statusCode: statusCode,
        originalError: originalError,
      );
    }
    return LabApiException(
      code: 'UNKNOWN_ERROR',
      message: '服务器返回了无法识别的错误信息。',
      statusCode: statusCode,
      originalError: originalError,
    );
  }

  /// Machine-readable code from the server, e.g. `VALIDATION_ERROR`.
  final String code;

  /// Operator-facing Chinese message. Shown as-is.
  final String message;

  /// Field-level details when the server supplies them (e.g. form validation).
  final Map<String, dynamic> fields;

  final int? statusCode;
  final Object? originalError;

  /// True when the caller should be sent back to the login screen instead of
  /// being shown a business error.
  bool get isSessionExpired => false;

  @override
  String toString() => 'LabApiException($code): $message';
}

/// The session behind the cookie is gone: HTTP 401, an Odoo session-expired
/// JSON-RPC error, or a session-invalid business code.
///
/// The app reacts by returning to the login screen. It must NOT immediately
/// retry an automatic sign-in: that is exactly the loop this class exists to
/// prevent.
class LabSessionExpiredException extends LabApiException {
  const LabSessionExpiredException({
    super.code = 'SESSION_INVALID',
    super.message = '登录状态已失效，请重新登录。',
    super.statusCode,
    super.originalError,
  });

  @override
  bool get isSessionExpired => true;
}
