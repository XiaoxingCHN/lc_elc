import '../../../models/lab_api_exception.dart';

/// Actionable text for any failure the business layer can produce.
///
/// The server always supplies a Chinese `message`; that message is shown as-is
/// so the operator can act on it. Anything else is still surfaced - a failure is
/// never turned into an empty list.
String describeLabError(Object error) {
  if (error is LabApiException) return error.message;
  return '操作失败：$error';
}

/// True when the failure means "sign in again" rather than "wrong input".
bool isSessionExpired(Object error) =>
    error is LabSessionExpiredException ||
    (error is LabApiException && error.isSessionExpired);

/// True when the failure means "the server could not be reached".
///
/// Only this class of failure may fall back to cached offline content: a
/// permission or session failure must stay visible, because acting on data the
/// operator may no longer see would be worse than an error message.
bool isOfflineFailure(Object error) {
  if (error is! LabApiException) return false;
  return error.code == 'NETWORK_ERROR' || error.code == 'TRANSPORT_ERROR';
}
