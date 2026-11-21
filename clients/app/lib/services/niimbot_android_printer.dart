import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../features/unified/models/labels.dart';
import 'niimbot_layout.dart';
import 'niimbot_printer.dart';

/// Direct Bluetooth printing to a NIIMBOT (精臣) printer from an **Android**
/// phone/tablet.
///
/// The native half is `NiimbotPrinterBridge.kt` (MethodChannel `lab/printer`,
/// EventChannel `lab/printer/scan`) around the vendor's Android SDK 4.1.1.
/// Geometry is computed HERE by the same [planThermalLabel] the Windows FFI
/// path uses, so the two platforms cannot disagree about the QR box, the text
/// lines, the font floor or the three-line cap; the native side only draws the
/// plan it is given.
///
/// Failure is never reported as success: a refused permission, a missing
/// printer, an SDK error code or a timeout all return a failed
/// [NiimbotPrintResult] carrying a specific Chinese reason.
class NiimbotAndroidPrinter {
  NiimbotAndroidPrinter({MethodChannel? channel, EventChannel? events})
      : _channel = channel ?? const MethodChannel('lab/printer'),
        _events = events ?? const EventChannel('lab/printer/scan');

  final MethodChannel _channel;
  final EventChannel _events;

  /// Platform probe, injectable so tests can exercise the Android branch on
  /// any host. When null the real platform is used; `flutter_test` reports
  /// Android as [defaultTargetPlatform] on every host, so a test that needs a
  /// non-Android host MUST set this explicitly.
  @visibleForTesting
  static ({bool android, bool windows, bool linux})? platformOverride;

  static bool get _isAndroid => platformOverride?.android ??
      (!kIsWeb && defaultTargetPlatform == TargetPlatform.android);

  /// True only on Android; every other platform hides the Bluetooth area and
  /// uses the Windows FFI / system print paths instead.
  static bool get supported => _isAndroid;

  /// 300 dpi models (the demo's `PrinterCapabilityManager` list). B1 Pro is
  /// explicitly a 300 dpi thermal portable; everything else defaults to the
  /// 200 dpi factor, and the native side overrides with the SDK's own
  /// `getMultiple()` once connected.
  static const List<String> _models300Dpi = <String>[
    'B1 Pro',
    'B2 Pro',
    'B21 Pro',
    'B32',
    'Z401',
    'T8',
    'M2',
    'M3',
    'EP2M',
    'D11_H',
    'B4 Pro',
  ];

  /// Millimetre→pixel factor for a scanned device name (11.81 at 300 dpi,
  /// 8.0 at 200 dpi). Only a hint: once connected the native bridge replaces it
  /// with the SDK's own `getMultiple()` (doc 5.2), which is authoritative.
  static double printMultipleForModel(String? modelName) {
    final name = (modelName ?? '').trim();
    for (final model in _models300Dpi) {
      if (name.toLowerCase().startsWith(model.toLowerCase())) return 11.81;
    }
    return 8.0;
  }

  /// Whether the native SDK initialised successfully.
  ///
  /// [reason] is a Chinese explanation when it did not; it is never invented —
  /// a missing plugin (non-Android host) reports "not supported".
  Future<({bool available, String? reason})> available() async {
    if (!_isAndroid) {
      return (available: false, reason: '当前系统不支持安卓蓝牙直打。');
    }
    try {
      final result = await _channel.invokeMapMethod<String, Object?>('available');
      return (
        available: result?['available'] == true,
        reason: result?['reason'] as String?,
      );
    } on MissingPluginException {
      return (available: false, reason: '当前安装包没有蓝牙打印组件。');
    } on PlatformException catch (error) {
      return (available: false, reason: _platformReason(error));
    }
  }

  /// Asks Android for the Bluetooth permissions (12+: SCAN + CONNECT,
  /// 6–11: fine location). Returns false when refused; the caller should show
  /// the Chinese explanation and offer a retry.
  Future<bool> requestPermissions() async {
    if (!_isAndroid) return false;
    try {
      final granted = await _channel.invokeMethod<bool>('requestPermissions');
      return granted ?? false;
    } on MissingPluginException {
      return false;
    } on PlatformException {
      return false;
    }
  }

  /// Starts a scan. The stream emits devices, then a `finished` event, or an
  /// `error` event. Call [stopScan] (or cancel the subscription) to stop early.
  ///
  /// The EventChannel is subscribed first and the native `scan` call is issued
  /// only after that, so no early device event is dropped.
  Stream<NiimbotAndroidScanEvent> scan() {
    if (!_isAndroid) {
      return Stream<NiimbotAndroidScanEvent>.value(
        const NiimbotAndroidScanEvent.error(
          code: 'UNSUPPORTED_PLATFORM',
          message: '当前系统不支持安卓蓝牙直打。',
        ),
      );
    }
    late StreamController<NiimbotAndroidScanEvent> controller;
    StreamSubscription<dynamic>? subscription;

    controller = StreamController<NiimbotAndroidScanEvent>(
      onListen: () {
        subscription = _events.receiveBroadcastStream().listen(
          (event) {
            final map = _asMap(event);
            final type = '${map['type'] ?? ''}';
            if (type == 'device') {
              controller.add(
                NiimbotAndroidScanEvent.device(
                  NiimbotAndroidDevice(
                    name: '${map['name'] ?? ''}',
                    address: '${map['address'] ?? ''}',
                  ),
                ),
              );
            } else if (type == 'finished') {
              controller.add(const NiimbotAndroidScanEvent.finished());
            } else if (type == 'error') {
              controller.add(
                NiimbotAndroidScanEvent.error(
                  code: '${map['code'] ?? 'SCAN_FAILED'}',
                  message: '${map['message'] ?? '蓝牙搜索失败。'}',
                ),
              );
            }
          },
          onError: (Object error) {
            controller.add(
              NiimbotAndroidScanEvent.error(
                code: error is PlatformException ? error.code : 'SCAN_FAILED',
                message: _platformReason(error),
              ),
            );
          },
          onDone: () {
            if (!controller.isClosed) controller.close();
          },
        );
        unawaited(_startScan(controller));
      },
      onCancel: () async {
        await subscription?.cancel();
        await stopScan();
      },
    );
    return controller.stream;
  }

  Future<void> _startScan(StreamController<NiimbotAndroidScanEvent> controller) async {
    try {
      await _channel.invokeMethod<void>('scan');
    } on MissingPluginException {
      _addError(controller, 'UNSUPPORTED_PLATFORM', '当前安装包没有蓝牙打印组件。');
    } on PlatformException catch (error) {
      _addError(controller, error.code, _platformReason(error));
    }
  }

  void _addError(StreamController<NiimbotAndroidScanEvent> controller, String code, String message) {
    if (controller.isClosed) return;
    controller.add(NiimbotAndroidScanEvent.error(code: code, message: message));
  }

  Future<void> stopScan() async {
    if (!_isAndroid) return;
    try {
      await _channel.invokeMethod<void>('stopScan');
    } on PlatformException {
      // Stopping a scan that already ended is not an error.
    } on MissingPluginException {
      // Same.
    }
  }

  /// Connects to [address]. The native call is synchronous and may block for
  /// seconds, so it runs on a worker thread there.
  Future<NiimbotAndroidConnectResult> connect(String address) async {
    if (!_isAndroid) {
      return const NiimbotAndroidConnectResult(
        connected: false,
        message: '当前系统不支持安卓蓝牙直打。',
      );
    }
    try {
      final result = await _channel.invokeMapMethod<String, Object?>(
        'connect',
        <String, Object?>{'address': address},
      );
      final code = (result?['code'] as num?)?.toInt() ?? -1;
      return NiimbotAndroidConnectResult(
        connected: result?['connected'] == true && code == 0,
        code: code,
        message: result?['message'] as String? ?? (code == 0 ? null : '连接失败（代码 $code）。'),
      );
    } on MissingPluginException {
      return const NiimbotAndroidConnectResult(
        connected: false,
        message: '当前安装包没有蓝牙打印组件。',
      );
    } on PlatformException catch (error) {
      return NiimbotAndroidConnectResult(
        connected: false,
        message: _platformReason(error),
      );
    }
  }

  Future<void> disconnect() async {
    if (!_isAndroid) return;
    try {
      await _channel.invokeMethod<void>('disconnect');
    } on PlatformException {
      // Already disconnected.
    } on MissingPluginException {
      // No bridge.
    }
  }

  Future<bool> isConnected() async {
    if (!_isAndroid) return false;
    try {
      return await _channel.invokeMethod<bool>('isConnected') ?? false;
    } on PlatformException {
      return false;
    } on MissingPluginException {
      return false;
    }
  }

  /// Paper size reported by the printer, or null when unsupported.
  Future<({int paperType, double widthMm, double heightMm})?> paperInfo() async {
    if (!_isAndroid) return null;
    try {
      final info = await _channel.invokeMapMethod<String, Object?>('paperInfo');
      if (info == null || info['state'] == -1) return null;
      return (
        paperType: (info['paperType'] as num?)?.toInt() ?? 0,
        widthMm: (info['paperWidth'] as num?)?.toDouble() ?? 0,
        heightMm: (info['totalHeight'] as num?)?.toDouble() ?? 0,
      );
    } on PlatformException {
      return null;
    } on MissingPluginException {
      return null;
    }
  }

  /// Prints [contents] (one entry per physical label, the server already
  /// expanded copies) using the SAME 40 × 20 mm plan as the Windows path.
  ///
  /// [modelName] is the scanned device name; it only selects the 300/200 dpi
  /// hint (the native side still prefers the SDK's own value).
  Future<NiimbotPrintResult> print({
    required double widthMm,
    required double heightMm,
    required List<LabelContent> contents,
    String? modelName,
    int copies = 1,
  }) async {
    if (!_isAndroid) {
      return NiimbotPrintResult.failure('当前系统不支持安卓蓝牙直打，请改用「系统打印」。');
    }
    if (contents.isEmpty) {
      return NiimbotPrintResult.failure('没有可打印的标签内容。');
    }
    final missingQr = contents.where((content) => !content.hasQr).length;
    if (missingQr > 0) {
      return NiimbotPrintResult.failure(
        '有 $missingQr 张标签缺少二维码内容，已拒绝整批直打（避免打错）。',
      );
    }

    final labels = <Map<String, dynamic>>[];
    var truncated = false;
    ThermalLabelPlan? firstPlan;
    for (final content in contents) {
      final plan = planThermalLabel(content, widthMm: widthMm, heightMm: heightMm);
      if (plan == null) {
        return NiimbotPrintResult.failure(
          '标签尺寸 ${_mm(widthMm)}×${_mm(heightMm)} mm 放不下可读的二维码和文字，已拒绝直打。',
        );
      }
      firstPlan ??= plan;
      if (plan.truncated) truncated = true;
      labels.add(<String, dynamic>{
        'payload': plan.payload,
        'lines': <Map<String, dynamic>>[
          for (final line in plan.lines)
            <String, dynamic>{
              'text': line.text,
              'x': plan.textX,
              'y': line.yMm,
              'width': plan.textWidthMm,
              'height': line.heightMm,
              'fontSize': line.fontMm,
              'bold': line.isTitle,
            },
          // The 库码 under the QR: the QR's own column, not the text column.
          for (final line in plan.caption)
            <String, dynamic>{
              'text': line.text,
              'x': plan.qrX,
              'y': line.yMm,
              'width': plan.qrSizeMm,
              'height': line.heightMm,
              'fontSize': line.fontMm,
              'bold': false,
            },
        ],
      });
    }

    final plan = firstPlan!;
    final spec = <String, dynamic>{
      'widthMm': widthMm,
      'heightMm': heightMm,
      'copies': copies < 1 ? 1 : copies,
      'qrX': plan.qrX,
      'qrY': plan.qrY,
      'qrSize': plan.qrSizeMm,
      'printMultiple': printMultipleForModel(modelName),
      // 1 = 间隙纸, 1 = 热敏; density 3 is B1 Pro's documented default.
      'paperType': 1,
      'printMode': 1,
      'density': 3,
    };

    try {
      final result = await _channel.invokeMapMethod<String, Object?>(
        'print',
        <String, Object?>{'labels': labels, 'spec': spec},
      );
      if (result == null) {
        return NiimbotPrintResult.failure('打印组件没有返回结果，请重试。');
      }
      final ok = result['ok'] == true;
      final printed = (result['printed'] as num?)?.toInt() ?? 0;
      final errorCode = (result['errorCode'] as num?)?.toInt();
      final errorMessage = result['errorMessage'] as String?;
      if (!ok) {
        return NiimbotPrintResult(
          ok: false,
          printed: printed,
          errorCode: errorCode,
          errorMessage: _printFailureMessage(result, errorCode, errorMessage),
          truncated: truncated || result['truncated'] == true,
          printerName: modelName,
        );
      }
      return NiimbotPrintResult(
        ok: true,
        printed: printed > 0 ? printed : contents.length,
        errorCode: null,
        errorMessage: null,
        truncated: truncated || result['truncated'] == true,
        printerName: modelName,
      );
    } on MissingPluginException {
      return NiimbotPrintResult.failure('当前安装包没有蓝牙打印组件。');
    } on PlatformException catch (error) {
      return NiimbotPrintResult.failure(_platformReason(error));
    }
  }

  static String _printFailureMessage(
    Map<String, Object?> result,
    int? errorCode,
    String? errorMessage,
  ) {
    final code = '${result['error'] ?? ''}';
    // The native side always supplies a Chinese reason; these prefixes make the
    // failure class explicit even if that text is ever replaced by a raw SDK
    // message.
    switch (code) {
      case 'NO_CONNECTION':
        return '打印机尚未连接，请先搜索并连接蓝牙打印机。';
      case 'BUSY':
        return '已有打印任务正在进行，请等待完成。';
      case 'TIMEOUT':
        return '打印超时，请检查打印机电源、纸张和蓝牙连接后重试。'
            '${errorMessage == null ? '' : '（$errorMessage）'}';
      case 'CANCELLED':
        return '打印已取消。';
      case 'RENDER_FAILED':
      case 'START_FAILED':
        return '打印失败，请重试。${errorMessage == null ? '' : '（$errorMessage）'}';
      case 'PRINT_ERROR':
        if (errorCode != null) {
          return '打印失败：${niimbotErrorMessage(errorCode)}（错误码 $errorCode）';
        }
        return '打印机报告错误。${errorMessage == null ? '' : '（$errorMessage）'}';
    }
    if (errorMessage != null && errorMessage.isNotEmpty) return errorMessage;
    if (errorCode != null) return '打印失败：${niimbotErrorMessage(errorCode)}（错误码 $errorCode）';
    return '打印失败（未知原因），请重试。';
  }

  static String _platformReason(Object error) {
    if (error is PlatformException) {
      switch (error.code) {
        case 'PERMISSION_DENIED':
          return error.message ?? '缺少蓝牙权限，请允许后重试。';
        case 'BLUETOOTH_OFF':
          return '请先打开手机蓝牙，再搜索打印机。';
        case 'LOCATION_OFF':
          return '请打开系统定位服务后再搜索蓝牙打印机（Android 10/11 的要求）。';
        case 'BLUETOOTH_UNAVAILABLE':
          return '此设备没有蓝牙模块，无法使用蓝牙打印机。';
        case 'SDK_UNAVAILABLE':
          return error.message ?? '精臣打印组件初始化失败。';
        case 'INVALID_ADDRESS':
          return error.message ?? '没有选择打印机。';
        case 'NO_CONNECTION':
          return error.message ?? '打印机尚未连接。';
        case 'BUSY':
          return error.message ?? '已有打印任务正在进行。';
      }
      if (error.message != null && error.message!.isNotEmpty) return error.message!;
      return '蓝牙打印失败（${error.code}）。';
    }
    return '蓝牙打印失败：$error';
  }

  static Map<String, Object?> _asMap(Object? value) {
    if (value is Map) {
      return value.map((key, item) => MapEntry('$key', item));
    }
    return const <String, Object?>{};
  }

  static String _mm(double value) {
    if (value == value.roundToDouble()) return value.toInt().toString();
    return value.toStringAsFixed(1);
  }
}

/// One device discovered by a scan.
class NiimbotAndroidDevice {
  const NiimbotAndroidDevice({required this.name, required this.address});

  final String name;
  final String address;

  /// Name plus MAC, for the device list.
  String get display => name.isEmpty ? address : '$name · $address';

  @override
  String toString() => display;
}

/// What one scan emitted: a device, the end of the scan, or a failure.
class NiimbotAndroidScanEvent {
  const NiimbotAndroidScanEvent.device(NiimbotAndroidDevice this.device)
      : finished = false,
        errorCode = null,
        errorMessage = null;

  const NiimbotAndroidScanEvent.finished()
      : device = null,
        finished = true,
        errorCode = null,
        errorMessage = null;

  const NiimbotAndroidScanEvent.error({required String code, required String message})
      : device = null,
        finished = false,
        errorCode = code,
        errorMessage = message;

  final NiimbotAndroidDevice? device;
  final bool finished;
  final String? errorCode;
  final String? errorMessage;

  bool get isDevice => device != null;
  bool get isFinished => finished;
  bool get isError => errorCode != null;
}

/// Result of one connect attempt.
class NiimbotAndroidConnectResult {
  const NiimbotAndroidConnectResult({
    required this.connected,
    this.code,
    this.message,
  });

  final bool connected;

  /// SDK return code: 0 success, -1 failed, -2 busy, -3 unsupported.
  final int? code;

  /// Chinese reason, null on success.
  final String? message;

  String get summary => connected ? '已连接蓝牙打印机。' : (message ?? '连接失败。');
}
