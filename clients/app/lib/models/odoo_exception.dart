/// Base exception for Odoo-related errors
class OdooException implements Exception {
  final String message;
  final int? rpcErrorCode;
  final String? rpcErrorData;
  final Object? originalError;

  OdooException(
    this.message, {
    this.rpcErrorCode,
    this.rpcErrorData,
    this.originalError,
  });

  @override
  String toString() => 'OdooException: $message'
      '${rpcErrorCode != null ? ' (code: $rpcErrorCode)' : ''}'
      '${rpcErrorData != null ? ' - $rpcErrorData' : ''}';
}

/// Authentication failed
class OdooAuthException extends OdooException {
  OdooAuthException(String message, {Object? originalError})
      : super(message, originalError: originalError);
}

/// Network or connection error
class OdooNetworkException extends OdooException {
  OdooNetworkException(String message, {Object? originalError})
      : super(message, originalError: originalError);
}

/// RPC method call error
class OdooRpcException extends OdooException {
  OdooRpcException(
    String message, {
    int? rpcErrorCode,
    String? rpcErrorData,
    Object? originalError,
  }) : super(
    message,
    rpcErrorCode: rpcErrorCode,
    rpcErrorData: rpcErrorData,
    originalError: originalError,
  );
}

/// Field or model not found
class OdooFieldException extends OdooException {
  OdooFieldException(String message) : super(message);
}

/// Data validation error
class OdooValidationException extends OdooException {
  OdooValidationException(String message) : super(message);
}
