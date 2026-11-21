import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Reads the SSID of the Wi-Fi network this device is currently joined to.
///
/// The value is used only to decide whether to offer the in-memory LAN
/// acceleration switch; it is never written to disk by this service. The
/// caller is responsible for keeping it in memory only.
///
/// Platform behaviour:
///  * Android: WifiManager via `lab/wifi_ssid`; requires the location
///    permission (and location services enabled) on Android 10+.
///  * Windows: WLAN API via the same channel; returns empty when the machine
///    is on Ethernet or the WLAN service is unavailable.
///  * Linux: `nmcli` (read-only); returns null when NetworkManager is absent.
///  * Any other platform: null.
class WifiSsidService {
  WifiSsidService._();

  static const MethodChannel _channel = MethodChannel('lab/wifi_ssid');

  /// Platform probe, injectable so a test can exercise any branch on any host.
  ///
  /// Setting ANY field makes the override REPLACE the real platform detection
  /// rather than OR-ing with it. OR-ing was wrong: on a Linux test host,
  /// `platformOverride = (android: true, ...)` still matched `Platform.isLinux`
  /// and ran `nmcli`, so the Android contract tests failed on exactly one
  /// platform - the one CI runs Linux builds on.
  @visibleForTesting
  static ({bool android, bool windows, bool linux}) platformOverride =
      const (android: false, windows: false, linux: false);

  static bool get _overrideActive =>
      platformOverride.android ||
      platformOverride.windows ||
      platformOverride.linux;

  static bool get _isAndroid =>
      _overrideActive ? platformOverride.android : Platform.isAndroid;
  static bool get _isWindows =>
      _overrideActive ? platformOverride.windows : Platform.isWindows;
  static bool get _isLinux =>
      _overrideActive ? platformOverride.linux : Platform.isLinux;

  /// The current SSID, or null when unknown/not on Wi-Fi.
  ///
  /// Throws [WifiPermissionException] when Android refuses to read it without
  /// the location permission; callers should offer [requestPermission] and
  /// retry.
  static Future<String?> current() async {
    if (_isLinux) return _linuxSsid();
    if (!_isAndroid && !_isWindows) return null;
    try {
      final value = await _channel.invokeMethod<String>('currentSsid');
      return _clean(value);
    } on PlatformException catch (error) {
      if (error.code == 'PERMISSION_DENIED' || error.code == 'LOCATION_OFF') {
        throw WifiPermissionException(error.code);
      }
      return null;
    } on MissingPluginException {
      return null;
    }
  }

  /// Asks Android for the location permission needed to read the SSID.
  ///
  /// Returns true when the platform accepted the request; the caller must
  /// re-read [current] afterwards because the user may still refuse.
  static Future<bool> requestPermission() async {
    if (!_isAndroid) return true;
    try {
      final granted = await _channel.invokeMethod<bool>('requestPermission');
      return granted ?? false;
    } on PlatformException {
      return false;
    } on MissingPluginException {
      return false;
    }
  }

  static String? _clean(String? raw) {
    if (raw == null) return null;
    final value = raw.trim();
    if (value.isEmpty || value == '<unknown ssid>' || value == '0x') {
      return null;
    }
    return value;
  }

  /// `nmcli -t` escapes ':' inside the SSID as '\:', so split on the first
  /// unescaped colon and unescape the remainder.
  static Future<String?> _linuxSsid() async {
    try {
      final result = await Process.run(
        'nmcli',
        <String>['-t', '-f', 'active,ssid', 'dev', 'wifi'],
      );
      if (result.exitCode == 0) {
        for (final line in result.stdout.toString().split('\n')) {
          if (!line.startsWith('yes:')) continue;
          final raw = line.substring(4).replaceAll(r'\:', ':');
          return _clean(raw);
        }
      }
    } on ProcessException {
      // NetworkManager/nmcli is not installed; LAN acceleration stays manual.
    }
    return null;
  }
}

/// Android could not read the SSID without an operator-granted permission.
class WifiPermissionException implements Exception {
  const WifiPermissionException(this.code);

  /// `PERMISSION_DENIED` or `LOCATION_OFF`.
  final String code;
}
