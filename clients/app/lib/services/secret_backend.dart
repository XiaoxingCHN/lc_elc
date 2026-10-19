import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Raised when the operating system key store cannot be used.
///
/// This is a HARD STOP, never a reason to fall back to a file: the caller must
/// tell the operator that this machine cannot remember a password and continue
/// with a normal (memory-only) login.
class SecretStorageUnavailableException implements Exception {
  const SecretStorageUnavailableException(this.message, {this.cause});

  /// Operator-facing, already free of secrets.
  final String message;
  final Object? cause;

  @override
  String toString() => 'SecretStorageUnavailableException: $message';
}

/// The narrow key-value contract the login code needs from the platform.
///
/// Kept behind an interface so tests can drive the "keyring is missing"
/// branch (Linux without gnome-keyring/KWallet) deterministically, and so the
/// production implementation stays a thin, auditable wrapper.
abstract class SecretBackend {
  /// Returns the stored value, or `null` when the key is absent.
  ///
  /// Throws [SecretStorageUnavailableException] when the platform key store
  /// itself cannot be reached.
  Future<String?> read(String key);

  /// Stores [value] under [key].
  ///
  /// Throws [SecretStorageUnavailableException] when the platform key store
  /// cannot be reached or refuses the write.
  Future<void> write(String key, String value);

  /// Removes [key]. Deleting a missing key is not an error.
  Future<void> delete(String key);
}

/// Production [SecretBackend] backed by `flutter_secure_storage`.
///
/// Where the value actually lands:
///   * Windows - AES-GCM blob in the app support directory; the data key is
///     kept in the Windows Credential Manager and protected by DPAPI for the
///     current Windows user.
///   * Android - data key wrapped by an Android Keystore RSA key (API 23+),
///     payload encrypted with AES-GCM.
///   * Linux - libsecret / `org.freedesktop.Secret` (GNOME Keyring, KWallet,
///     any Secret Service provider).
///
/// If none of those exist (headless Linux is the realistic case) the platform
/// channel answers with a [PlatformException], which is translated here into
/// [SecretStorageUnavailableException]. Nothing is written anywhere else.
class FlutterSecureStorageBackend implements SecretBackend {
  const FlutterSecureStorageBackend();

  static const FlutterSecureStorage _storage = FlutterSecureStorage();

  @override
  Future<String?> read(String key) async {
    try {
      return await _storage.read(key: key);
    } on PlatformException catch (e) {
      throw SecretStorageUnavailableException(_describe(e), cause: e);
    } on MissingPluginException catch (e) {
      throw SecretStorageUnavailableException(_describeMissingPlugin(), cause: e);
    }
  }

  @override
  Future<void> write(String key, String value) async {
    try {
      await _storage.write(key: key, value: value);
    } on PlatformException catch (e) {
      throw SecretStorageUnavailableException(_describe(e), cause: e);
    } on MissingPluginException catch (e) {
      throw SecretStorageUnavailableException(_describeMissingPlugin(), cause: e);
    }
  }

  @override
  Future<void> delete(String key) async {
    try {
      await _storage.delete(key: key);
    } on PlatformException catch (e) {
      throw SecretStorageUnavailableException(_describe(e), cause: e);
    } on MissingPluginException catch (e) {
      throw SecretStorageUnavailableException(_describeMissingPlugin(), cause: e);
    }
  }

  /// Operator-facing explanation, deliberately free of platform jargon: the
  /// login screen shows this text to normal users. The raw platform message is
  /// summarised, never echoed verbatim (it can name keyring internals).
  static String _describe(PlatformException _) =>
      '当前系统没有可用的安全存储，无法保存密码。';

  static String _describeMissingPlugin() =>
      '当前系统没有可用的安全存储，无法保存密码。';
}
