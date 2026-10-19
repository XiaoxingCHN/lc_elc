import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// What this device can use to enter a code.
///
/// The business is identical on every platform; only the *input device*
/// differs, and the app never shows an action the device cannot perform:
///
///   * Windows / Linux: a hardware scanner gun types like a keyboard, and the
///     clipboard covers codes pasted from the Odoo web UI. There is no camera
///     path at all (`mobile_scanner` has no Windows/Linux implementation), so no
///     camera button is rendered - nothing "clicks and reports unsupported";
///   * Android: the same keyboard/paste path PLUS the phone camera.
///
/// Every path ends in the same `/lab/api/inventory/resolve_code` call.
class ScannerCapabilities {
  const ScannerCapabilities({
    required this.camera,
    required this.keyboardWedge,
    required this.clipboard,
  });

  /// A phone/tablet camera is available (Android/iOS).
  final bool camera;

  /// A scanner gun / typed code works (always true - it is a text field).
  final bool keyboardWedge;

  /// Clipboard import works (always true).
  final bool clipboard;

  /// One-line hint shown under the input.
  String get hint {
    if (camera) {
      return '可用手机摄像头扫码，也可直接输入/粘贴编码，或使用蓝牙扫码枪。';
    }
    return '可用扫码枪输入（键盘方式）、手动输入或粘贴编码。';
  }
}

/// Camera scanning needs `mobile_scanner`, which only implements Android/iOS.
bool cameraScannerSupported() {
  if (kIsWeb) return false;
  switch (defaultTargetPlatform) {
    case TargetPlatform.android:
    case TargetPlatform.iOS:
      return true;
    default:
      return false;
  }
}

/// Detects the input devices available on this platform.
ScannerCapabilities detectScannerCapabilities() => ScannerCapabilities(
      camera: cameraScannerSupported(),
      keyboardWedge: true,
      clipboard: true,
    );

/// Cleans up a scanned / pasted code.
///
/// A scanner gun appends CR/LF (and sometimes TAB) after the payload, and the
/// operator may paste a code with surrounding whitespace or a stray newline from
/// a spreadsheet. The payload itself (`LABB:...`, `LABL:...`, `C123456`, a
/// supplier QR) is passed through UNCHANGED to the server, because only the
/// server decides what a code means.
String normalizeScanInput(String raw) {
  return raw.replaceAll(RegExp(r'[\r\n\t\u0000]'), '').trim();
}

/// Reads the clipboard as a candidate code, or `null` when it is empty.
///
/// Implemented with the Flutter services channel (no extra plugin), so it works
/// on Windows, Linux and Android identically.
Future<String?> readClipboardCode() async {
  final data = await Clipboard.getData(Clipboard.kTextPlain);
  final text = normalizeScanInput(data?.text ?? '');
  if (text.isEmpty) return null;
  return text;
}

/// Copies a code back to the clipboard (used to move a code between devices).
Future<void> writeClipboardCode(String text) async {
  await Clipboard.setData(ClipboardData(text: normalizeScanInput(text)));
}
