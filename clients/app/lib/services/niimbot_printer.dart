import 'dart:convert';
import 'dart:ffi';
import 'dart:io';
import 'dart:isolate';

import 'package:ffi/ffi.dart';

import '../features/unified/models/labels.dart';
import 'niimbot_layout.dart';

/// NIIMBOT (精臣) PC C++ SDK 4.0.6, `jcPrinterApi.dll` (x64), driven over
/// `dart:ffi`.
///
/// The DLL family and the exact functions bound here are documented in
/// `windows/niimbot/README.md`; the SDK header (`jcPrinterApi.h`) is the source
/// of every signature below:
///
/// ```
/// bool initSdk(char* fontDir);
/// char* getAllPrinters();                       // FreeBuffer() it
/// bool selectPrinter(char* printerName, int port);
/// bool startJob_New(StartJobParameter param);   // 7 × int32, BY VALUE
/// bool InitDrawingBoard(float w, float h, int rotate, const char* font,
///                       int verticalShift, int horizontalShift);
/// bool DrawLableText(float x, float y, float w, float h, const char* value,
///                    const char* fontFamily, float fontSize, int rotate,
///                    int alignH, int alignV, int lineMode,
///                    float letterSpacing, float lineSpacing,
///                    bool fontStyle[4]);
/// bool DrawLableQrCode(float x, float y, float w, float h, const char* value,
///                      int codeType, int rotate);
/// bool commitJob();  bool endJob();  bool isConnected();
/// int  getPrintLastError();
/// void FreeBuffer(char* ptr);
/// ```
///
/// Every SDK call is synchronous and blocks until the printer answers, so the
/// job runs in a background isolate (`Isolate.run`).

// ---------------------------------------------------------------------------
// Native signatures (dart:ffi types)
// ---------------------------------------------------------------------------

typedef _BoolCharPtrNative = Bool Function(Pointer<Utf8>);
typedef _BoolCharPtrDart = bool Function(Pointer<Utf8>);

typedef _BoolVoidNative = Bool Function();
typedef _BoolVoidDart = bool Function();

typedef _IntVoidNative = Int32 Function();
typedef _IntVoidDart = int Function();

typedef _CharPtrVoidNative = Pointer<Utf8> Function();
typedef _CharPtrVoidDart = Pointer<Utf8> Function();

typedef _CharPtrIntNative = Bool Function(Pointer<Utf8>, Int32);
typedef _CharPtrIntDart = bool Function(Pointer<Utf8>, int);

typedef _StartJobNative = Bool Function(StartJobParameter);
typedef _StartJobDart = bool Function(StartJobParameter);

typedef _InitBoardNative = Bool Function(
  Float,
  Float,
  Int32,
  Pointer<Utf8>,
  Int32,
  Int32,
);
typedef _InitBoardDart = bool Function(
  double,
  double,
  int,
  Pointer<Utf8>,
  int,
  int,
);

typedef _DrawTextNative = Bool Function(
  Float,
  Float,
  Float,
  Float,
  Pointer<Utf8>,
  Pointer<Utf8>,
  Float,
  Int32,
  Int32,
  Int32,
  Int32,
  Float,
  Float,
  Pointer<Bool>,
);
typedef _DrawTextDart = bool Function(
  double,
  double,
  double,
  double,
  Pointer<Utf8>,
  Pointer<Utf8>,
  double,
  int,
  int,
  int,
  int,
  double,
  double,
  Pointer<Bool>,
);

// `DrawLableBarCode` is deliberately NOT bound. The 40 x 20 mm label carries
// exactly one code and it is the QR (`DrawLableQrCode`): a 1-D strip costs a
// whole text line and phones cannot read it. Leaving the symbol unlooked-up
// also means a future DLL that drops it still loads here.

typedef _DrawQrNative = Bool Function(
  Float,
  Float,
  Float,
  Float,
  Pointer<Utf8>,
  Int32,
  Int32,
);
typedef _DrawQrDart = bool Function(
  double,
  double,
  double,
  double,
  Pointer<Utf8>,
  int,
  int,
);

typedef _FreeBufferNative = Void Function(Pointer<Utf8>);
typedef _FreeBufferDart = void Function(Pointer<Utf8>);

/// `struct StartJobParameter` from `define.h`: seven `int32_t` fields passed
/// BY VALUE on x64.
final class StartJobParameter extends Struct {
  @Int32()
  external int printLabelType;

  @Int32()
  external int printDensity;

  @Int32()
  external int printMode;

  @Int32()
  external int colorType;

  @Int32()
  external int qualityType;

  @Int32()
  external int printCount;

  @Int32()
  external int printCopies;
}

/// Error codes of `getPrintLastError()`, from `jcPrinterApi.h` and the SDK
/// document V4.0.6. Unknown values are reported as "未知打印错误（代码 N）".
const Map<int, String> kNiimbotErrorMessages = <int, String>{
  0: '无错误',
  1: '盒盖打开（请合上打印机上盖）',
  2: '缺纸（请装入标签纸）',
  3: '电量不足（请充电或接电源）',
  4: '电池异常',
  5: '手动停止',
  6: '数据错误',
  7: '打印头温度过高（请等待冷却）',
  8: '走纸异常',
  9: '打印机正在打印',
  10: '未检测到打印头',
  11: '环境温度过低',
  12: '打印头松动',
  13: '未检测到碳带',
  14: '耗材不匹配',
  15: '碳带用完',
  16: '纸张类型不支持',
  17: '设置纸张类型失败',
  18: '设置打印模式失败',
  19: '设置浓度失败',
  20: '写入 RFID 失败',
  21: '边距参数错误',
  22: '打印超时',
  23: '打印机已断开连接',
  24: '画板参数设置错误',
  25: '旋转角度参数错误',
  26: 'JSON 参数错误',
  27: '出纸异常（关闭上盖检测，已废弃）',
  28: '请检查纸张类型',
  29: '碳带与打印模式不匹配',
  30: '当前机型不支持设置浓度',
  31: '当前机型不支持该打印模式',
  32: '设置材质失败',
  34: '不支持 RFID 写入',
  35: '打印机打印状态异常',
  50: '非法标签',
  51: '非法碳带和标签',
  52: '固件接收数据超时',
  53: '非专用色带（色带型号不匹配）',
  58: '非正品耗材（标签与色带均未识别）',
  59: '非正品色带（色带未识别）',
  60: '耗材超限（标签与色带均超过使用限制）',
  61: '色带超限（色带超过使用限制）',
  62: '非正品标签（标签未识别）',
  63: '标签超限（标签超过使用限制）',
  255: '未定义错误',
  -1: '未定义错误',
};

/// Chinese message for an SDK error code.
///
/// `startJob_New` additionally documents `-1/-2/-3` in its own comment, so those
/// are translated too even though they are not in the error table.
String niimbotErrorMessage(int code) {
  switch (code) {
    case -1:
      return '开启打印任务失败';
    case -2:
      return '打印机忙碌';
    case -3:
      return '打印机不支持该打印参数';
  }
  return kNiimbotErrorMessages[code] ?? '未知打印错误（代码 $code）';
}

/// One USB printer reported by `getAllPrinters()`.
///
/// The SDK returns a JSON object shaped like `{"S6_0011223344": "4"}` - a map
/// of printer name to port.
class NiimbotPrinterInfo {
  const NiimbotPrinterInfo({required this.name, required this.port});

  final String name;
  final int port;

  @override
  String toString() => '$name (端口 $port)';
}

/// Parses the `getAllPrinters()` JSON (`{"NAME": "PORT"}`).
///
/// Tolerates a JSON array of `{name, port}` objects as well, and skips entries
/// without a usable name/port rather than throwing: one malformed row must not
/// hide the real printer.
List<NiimbotPrinterInfo> parsePrintersJson(String raw) {
  if (raw.trim().isEmpty) return const <NiimbotPrinterInfo>[];
  Object? decoded;
  try {
    decoded = jsonDecode(raw);
  } on FormatException {
    return const <NiimbotPrinterInfo>[];
  }

  final result = <NiimbotPrinterInfo>[];
  void add(Object? name, Object? port) {
    final printerName = '${name ?? ''}'.trim();
    if (printerName.isEmpty) return;
    final value = port is int ? port : int.tryParse('${port ?? ''}'.trim());
    if (value == null) return;
    result.add(NiimbotPrinterInfo(name: printerName, port: value));
  }

  if (decoded is Map) {
    decoded.forEach((key, value) => add(key, value));
  } else if (decoded is List) {
    for (final entry in decoded) {
      if (entry is Map) {
        add(entry['name'] ?? entry['printerName'],
            entry['port'] ?? entry['portName']);
      }
    }
  }
  return result;
}

/// Result of one direct-print job.
class NiimbotPrintResult {
  const NiimbotPrintResult({
    required this.ok,
    required this.printed,
    required this.errorCode,
    required this.errorMessage,
    required this.truncated,
    this.printerName,
  });

  final bool ok;

  /// Labels actually committed to the printer (0 on failure).
  final int printed;

  /// `getPrintLastError()` code, or null when the SDK was never reached.
  final int? errorCode;

  /// Operator-facing Chinese reason, or null on success.
  final String? errorMessage;

  /// At least one label had to drop a line or will be ellipsized.
  final bool truncated;

  final String? printerName;

  /// A failed result with no SDK involvement (DLL missing, no printer, ...).
  factory NiimbotPrintResult.failure(String message, {int? errorCode}) =>
      NiimbotPrintResult(
        ok: false,
        printed: 0,
        errorCode: errorCode,
        errorMessage: message,
        truncated: false,
      );

  /// Operator-facing one-line summary. Never says 成功 unless [ok].
  String get summary {
    if (ok) {
      return '已直打 $printed 张标签'
          '${printerName == null ? '' : '（$printerName）'}'
          '${truncated ? '；部分文字行因空间不足已省略或截断' : ''}。';
    }
    return '精臣直打失败：${errorMessage ?? '未知原因'}'
        '${errorCode == null ? '' : '（错误码 $errorCode）'}';
  }

  @override
  String toString() => summary;
}

// ---------------------------------------------------------------------------
// Platform / runtime discovery
// ---------------------------------------------------------------------------

/// Whether this build can attempt direct printing at all.
///
/// Pure function so a test can assert the non-Windows branch on any host.
bool isNiimbotPlatformSupported({
  required bool isWindows,
  required bool is64Bit,
  required bool dllExists,
}) =>
    isWindows && is64Bit && dllExists;

/// Where the SDK files live for the running executable.
class NiimbotRuntime {
  const NiimbotRuntime({required this.libraryPath, required this.fontDir});

  final String libraryPath;
  final String fontDir;

  /// Resolves the SDK next to the executable; null when direct printing is
  /// impossible (wrong OS/arch, or the DLL is missing).
  ///
  /// The CMake `install()` rule copies `windows/niimbot/runtime/` beside
  /// `lab_inventory_client.exe`, so `exeDir/jcPrinterApi.dll` is the production
  /// location and `exeDir/font/` is handed to `initSdk`.
  static NiimbotRuntime? resolve() {
    if (!Platform.isWindows) return null;
    String exeDir;
    try {
      exeDir = File(Platform.resolvedExecutable).parent.path;
    } catch (_) {
      return null;
    }
    final separator = Platform.pathSeparator;
    final dll = File('$exeDir${separator}jcPrinterApi.dll');
    final supported = isNiimbotPlatformSupported(
      isWindows: true,
      is64Bit: sizeOf<IntPtr>() == 8,
      dllExists: dll.existsSync(),
    );
    if (!supported) return null;
    return NiimbotRuntime(
      libraryPath: dll.path,
      fontDir: '$exeDir${separator}font',
    );
  }
}

// ---------------------------------------------------------------------------
// Native binding
// ---------------------------------------------------------------------------

/// Loaded symbols of `jcPrinterApi.dll`.
class _NiimbotApi {
  _NiimbotApi(DynamicLibrary lib)
      : initSdk = lib.lookupFunction<_BoolCharPtrNative, _BoolCharPtrDart>(
          'initSdk',
        ),
        unInitSdk = lib.lookupFunction<_BoolVoidNative, _BoolVoidDart>(
          'unInitSdk',
        ),
        getAllPrinters =
            lib.lookupFunction<_CharPtrVoidNative, _CharPtrVoidDart>(
          'getAllPrinters',
        ),
        selectPrinter = lib.lookupFunction<_CharPtrIntNative, _CharPtrIntDart>(
          'selectPrinter',
        ),
        disconnectPrinter = lib.lookupFunction<_BoolVoidNative, _BoolVoidDart>(
          'disconnectPrinter',
        ),
        startJobNew = lib.lookupFunction<_StartJobNative, _StartJobDart>(
          'startJob_New',
        ),
        commitJob = lib.lookupFunction<_BoolVoidNative, _BoolVoidDart>(
          'commitJob',
        ),
        endJob = lib.lookupFunction<_BoolVoidNative, _BoolVoidDart>('endJob'),
        isConnected = lib.lookupFunction<_BoolVoidNative, _BoolVoidDart>(
          'isConnected',
        ),
        getPrintLastError = lib.lookupFunction<_IntVoidNative, _IntVoidDart>(
          'getPrintLastError',
        ),
        initDrawingBoard =
            lib.lookupFunction<_InitBoardNative, _InitBoardDart>(
          'InitDrawingBoard',
        ),
        drawLableText = lib.lookupFunction<_DrawTextNative, _DrawTextDart>(
          'DrawLableText',
        ),
        drawLableQrCode = lib.lookupFunction<_DrawQrNative, _DrawQrDart>(
          'DrawLableQrCode',
        ),
        freeBuffer = lib.lookupFunction<_FreeBufferNative, _FreeBufferDart>(
          'FreeBuffer',
        );

  final _BoolCharPtrDart initSdk;
  final _BoolVoidDart unInitSdk;
  final _CharPtrVoidDart getAllPrinters;
  final _CharPtrIntDart selectPrinter;
  final _BoolVoidDart disconnectPrinter;
  final _StartJobDart startJobNew;
  final _BoolVoidDart commitJob;
  final _BoolVoidDart endJob;
  final _BoolVoidDart isConnected;
  final _IntVoidDart getPrintLastError;
  final _InitBoardDart initDrawingBoard;
  final _DrawTextDart drawLableText;
  final _DrawQrDart drawLableQrCode;
  final _FreeBufferDart freeBuffer;
}

/// Synchronous driver around `jcPrinterApi.dll`.
///
/// Not used directly by the UI; [NiimbotLabelPrinter] wraps a whole job in one
/// background isolate.
class NiimbotPrinter {
  NiimbotPrinter._(this._api);

  final _NiimbotApi _api;

  /// Opens the DLL and resolves every symbol.
  ///
  /// Throws [StateError] with a Chinese message when a symbol is missing.
  static NiimbotPrinter open(NiimbotRuntime runtime) {
    final library = DynamicLibrary.open(runtime.libraryPath);
    try {
      return NiimbotPrinter._(_NiimbotApi(library));
    } on ArgumentError catch (error) {
      throw StateError(
        'jcPrinterApi.dll 已找到，但缺少接口：${error.message}。'
        '请确认使用的是 4.0.6 x64 接入包。',
      );
    }
  }

  /// `initSdk(fontDir)` - must be called before any drawing call.
  bool initSdk(String fontDir) {
    final path = fontDir.toNativeUtf8();
    try {
      return _api.initSdk(path);
    } finally {
      malloc.free(path);
    }
  }

  bool unInitSdk() => _api.unInitSdk();

  /// USB printers reported by the SDK. The returned buffer is released with
  /// `FreeBuffer` (never `malloc.free` - it is the SDK's own allocator).
  List<NiimbotPrinterInfo> getAllPrinters() {
    final pointer = _api.getAllPrinters();
    if (pointer == nullptr) return const <NiimbotPrinterInfo>[];
    try {
      return parsePrintersJson(pointer.toDartString());
    } finally {
      _api.freeBuffer(pointer);
    }
  }

  bool selectPrinter(NiimbotPrinterInfo printer) {
    final name = printer.name.toNativeUtf8();
    try {
      return _api.selectPrinter(name, printer.port);
    } finally {
      malloc.free(name);
    }
  }

  bool disconnectPrinter() => _api.disconnectPrinter();

  bool isConnected() => _api.isConnected();

  int getPrintLastError() => _api.getPrintLastError();

  /// `startJob_New` with the operator's fixed profile:
  /// gap paper (1), density 3, thermal (1), monochrome (0), high speed (1).
  bool startJob({
    int printLabelType = 1,
    int printDensity = 3,
    int printMode = 1,
    int colorType = 0,
    int qualityType = 1,
    required int printCount,
    int printCopies = 1,
  }) {
    final parameter = calloc<StartJobParameter>();
    try {
      parameter.ref
        ..printLabelType = printLabelType
        ..printDensity = printDensity
        ..printMode = printMode
        ..colorType = colorType
        ..qualityType = qualityType
        ..printCount = printCount
        ..printCopies = printCopies;
      return _api.startJobNew(parameter.ref);
    } finally {
      calloc.free(parameter);
    }
  }

  bool commitJob() => _api.commitJob();

  bool endJob() => _api.endJob();

  /// Initialises a drawing board of [widthMm] × [heightMm] with [fontFamily].
  bool initDrawingBoard({
    required double widthMm,
    required double heightMm,
    String fontFamily = 'ZT001.ttf',
    int rotate = 0,
  }) {
    final font = fontFamily.toNativeUtf8();
    try {
      return _api.initDrawingBoard(widthMm, heightMm, rotate, font, 0, 0);
    } finally {
      malloc.free(font);
    }
  }

  /// Draws one text box.
  ///
  /// [lineMode] defaults to 3 (fixed box, ellipsis on overflow): the plan has
  /// already chosen a size that fits, so this only guards against a font metric
  /// mismatch and never silently crops the QR.
  bool drawText({
    required double x,
    required double y,
    required double width,
    required double height,
    required String value,
    required double fontSizeMm,
    String fontFamily = 'ZT001.ttf',
    int alignHorizontal = 0,
    int alignVertical = 0,
    int lineMode = 3,
    double letterSpacing = 0,
    double lineSpacing = 0.2,
    List<bool> fontStyle = const <bool>[false, false, false, false],
  }) {
    final text = value.toNativeUtf8();
    final font = fontFamily.toNativeUtf8();
    final style = calloc<Bool>(4);
    try {
      for (var index = 0; index < 4; index++) {
        style[index] = index < fontStyle.length ? fontStyle[index] : false;
      }
      return _api.drawLableText(
        x,
        y,
        width,
        height,
        text,
        font,
        fontSizeMm,
        0,
        alignHorizontal,
        alignVertical,
        lineMode,
        letterSpacing,
        lineSpacing,
        style,
      );
    } finally {
      calloc.free(style);
      malloc.free(font);
      malloc.free(text);
    }
  }

  /// Draws the ONE QR of a label (`codeType` 31 = QR_CODE).
  bool drawQrCode({
    required double x,
    required double y,
    required double width,
    required double height,
    required String value,
    int codeType = 31,
    int rotate = 0,
  }) {
    final payload = value.toNativeUtf8();
    try {
      return _api.drawLableQrCode(
        x,
        y,
        width,
        height,
        payload,
        codeType,
        rotate,
      );
    } finally {
      malloc.free(payload);
    }
  }
}

// ---------------------------------------------------------------------------
// Job
// ---------------------------------------------------------------------------

/// A label plan flattened to plain values so it can cross the isolate boundary.
class _LabelJob {
  const _LabelJob({
    required this.widthMm,
    required this.heightMm,
    required this.qrX,
    required this.qrY,
    required this.qrSizeMm,
    required this.qrPayload,
    required this.textX,
    required this.textWidthMm,
    required this.lines,
    required this.caption,
    required this.truncated,
  });

  final double widthMm;
  final double heightMm;
  final double qrX;
  final double qrY;
  final double qrSizeMm;
  final String qrPayload;
  final double textX;
  final double textWidthMm;
  final List<_TextJob> lines;

  /// Lines drawn UNDER the QR, in the QR's own column (a location's 库码).
  final List<_TextJob> caption;
  final bool truncated;

  factory _LabelJob.fromPlan(ThermalLabelPlan plan) => _LabelJob(
        widthMm: plan.widthMm,
        heightMm: plan.heightMm,
        qrX: plan.qrX,
        qrY: plan.qrY,
        qrSizeMm: plan.qrSizeMm,
        qrPayload: plan.payload,
        textX: plan.textX,
        textWidthMm: plan.textWidthMm,
        lines: <_TextJob>[
          for (final line in plan.lines)
            _TextJob(
              text: line.text,
              yMm: line.yMm,
              heightMm: line.heightMm,
              fontMm: line.fontMm,
              isTitle: line.isTitle,
            ),
        ],
        caption: <_TextJob>[
          for (final line in plan.caption)
            _TextJob(
              text: line.text,
              yMm: line.yMm,
              heightMm: line.heightMm,
              fontMm: line.fontMm,
              isTitle: false,
            ),
        ],
        truncated: plan.truncated,
      );
}

class _TextJob {
  const _TextJob({
    required this.text,
    required this.yMm,
    required this.heightMm,
    required this.fontMm,
    required this.isTitle,
  });

  final String text;
  final double yMm;
  final double heightMm;
  final double fontMm;
  final bool isTitle;
}

/// High-level job: [LabelSpec] dimensions + structured [LabelContent] → real
/// labels.
///
/// Flow (per the SDK's documented order):
///   initSdk → getAllPrinters → selectPrinter → startJob_New →
///   per label { InitDrawingBoard → DrawLableQrCode → DrawLableText × n →
///   commitJob } → endJob → disconnectPrinter.
///
/// Every failure is reported with `getPrintLastError()` translated to Chinese;
/// a failed `commitJob` stops the job immediately so the operator is never told
/// "成功" for a label the printer refused.
class NiimbotLabelPrinter {
  NiimbotLabelPrinter({NiimbotRuntime? runtime, this.printerName})
      : _runtime = runtime ?? NiimbotRuntime.resolve();

  final NiimbotRuntime? _runtime;

  /// Preferred printer; null means the first USB printer reported.
  final String? printerName;

  /// Whether a job can be attempted (Windows x64 + DLL present).
  bool get available => _runtime != null;

  /// Prints [contents] as one job on a background isolate.
  ///
  /// The server already expanded `copies` into [contents], so [contents] is
  /// one entry per physical label and [copies] is passed to the SDK as
  /// `printCopies` (default 1: one commit = one label).
  Future<NiimbotPrintResult> print({
    required double widthMm,
    required double heightMm,
    required List<LabelContent> contents,
    int copies = 1,
  }) async {
    final runtime = _runtime;
    if (runtime == null) {
      return NiimbotPrintResult.failure(
        '当前系统或安装目录没有精臣打印组件（仅 Windows x64 支持直打），请改用「系统打印」。',
      );
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

    final jobs = <_LabelJob>[];
    for (final content in contents) {
      final plan = planThermalLabel(
        content,
        widthMm: widthMm,
        heightMm: heightMm,
      );
      if (plan == null) {
        return NiimbotPrintResult.failure(
          '标签尺寸 ${widthMm.toStringAsFixed(0)}×${heightMm.toStringAsFixed(0)} mm '
          '放不下可读的二维码和文字，已拒绝直打。',
        );
      }
      jobs.add(_LabelJob.fromPlan(plan));
    }

    return Isolate.run(
      () => _runJob(
        libraryPath: runtime.libraryPath,
        fontDir: runtime.fontDir,
        jobs: jobs,
        printCount: jobs.length,
        copies: copies < 1 ? 1 : copies,
        printerName: printerName,
      ),
    );
  }

  static NiimbotPrintResult _runJob({
    required String libraryPath,
    required String fontDir,
    required List<_LabelJob> jobs,
    required int printCount,
    required int copies,
    required String? printerName,
  }) {
    final truncated = jobs.any((job) => job.truncated);

    NiimbotPrinter printer;
    try {
      printer = NiimbotPrinter.open(
        NiimbotRuntime(libraryPath: libraryPath, fontDir: fontDir),
      );
    } catch (error) {
      return NiimbotPrintResult.failure('无法加载 jcPrinterApi.dll：$error');
    }

    if (!printer.initSdk(fontDir)) {
      final code = printer.getPrintLastError();
      return NiimbotPrintResult.failure(
        '初始化精臣打印组件失败：${niimbotErrorMessage(code)}',
        errorCode: code,
      );
    }

    var connected = false;
    var jobStarted = false;
    var jobEnded = false;
    try {
      final printers = printer.getAllPrinters();
      if (printers.isEmpty) {
        return NiimbotPrintResult.failure(
          '没有找到精臣打印机：请确认打印机已开机并用 USB 线连接本机。',
        );
      }
      final selected = printerName == null
          ? printers.first
          : printers.firstWhere(
              (candidate) => candidate.name == printerName,
              orElse: () => printers.first,
            );
      if (!printer.selectPrinter(selected)) {
        final code = printer.getPrintLastError();
        return NiimbotPrintResult.failure(
          '连接打印机 ${selected.name} 失败：${niimbotErrorMessage(code)}',
          errorCode: code,
        );
      }
      connected = true;

      if (!printer.startJob(printCount: printCount, printCopies: copies)) {
        final code = printer.getPrintLastError();
        return NiimbotPrintResult.failure(
          '开启打印任务失败：${niimbotErrorMessage(code)}',
          errorCode: code,
        ).withPrinter(selected.name);
      }
      jobStarted = true;

      var printed = 0;
      for (final job in jobs) {
        if (!printer.initDrawingBoard(
          widthMm: job.widthMm,
          heightMm: job.heightMm,
        )) {
          return _fail(printer, '初始化打印画板失败', printed, selected.name, truncated);
        }
        if (!printer.drawQrCode(
          x: job.qrX,
          y: job.qrY,
          width: job.qrSizeMm,
          height: job.qrSizeMm,
          value: job.qrPayload,
        )) {
          return _fail(printer, '绘制二维码失败', printed, selected.name, truncated);
        }
        for (final line in job.lines) {
          if (!printer.drawText(
            x: job.textX,
            y: line.yMm,
            width: job.textWidthMm,
            height: line.heightMm,
            value: line.text,
            fontSizeMm: line.fontMm,
            lineSpacing: 0.2,
            fontStyle: <bool>[false, line.isTitle, false, false],
          )) {
            return _fail(printer, '绘制文字失败', printed, selected.name, truncated);
          }
        }
        // The 库码 under the QR: same narrow column as the code itself, so the
        // printed value cannot drift away from what the QR encodes.
        for (final line in job.caption) {
          if (!printer.drawText(
            x: job.qrX,
            y: line.yMm,
            width: job.qrSizeMm,
            height: line.heightMm,
            value: line.text,
            fontSizeMm: line.fontMm,
            lineSpacing: 0.2,
            fontStyle: <bool>[false, false, false, false],
          )) {
            return _fail(printer, '绘制库码失败', printed, selected.name, truncated);
          }
        }
        if (!printer.commitJob()) {
          return _fail(printer, '提交打印任务失败', printed, selected.name, truncated);
        }
        printed++;
      }

      if (!printer.endJob()) {
        final code = printer.getPrintLastError();
        jobEnded = true;
        return NiimbotPrintResult(
          ok: false,
          printed: printed,
          errorCode: code,
          errorMessage: '结束打印任务时出错：${niimbotErrorMessage(code)}',
          truncated: truncated,
          printerName: selected.name,
        );
      }
      jobEnded = true;
      return NiimbotPrintResult(
        ok: true,
        printed: printed,
        errorCode: 0,
        errorMessage: null,
        truncated: truncated,
        printerName: selected.name,
      );
    } finally {
      if (jobStarted && !jobEnded) {
        try {
          printer.endJob();
        } catch (_) {}
      }
      if (connected) {
        try {
          printer.disconnectPrinter();
        } catch (_) {}
      }
      try {
        printer.unInitSdk();
      } catch (_) {}
    }
  }

  static NiimbotPrintResult _fail(
    NiimbotPrinter printer,
    String action,
    int printed,
    String printerName,
    bool truncated,
  ) {
    final code = printer.getPrintLastError();
    return NiimbotPrintResult(
      ok: false,
      printed: printed,
      errorCode: code,
      errorMessage: '$action：${niimbotErrorMessage(code)}',
      truncated: truncated,
      printerName: printerName,
    );
  }
}

extension on NiimbotPrintResult {
  NiimbotPrintResult withPrinter(String name) => NiimbotPrintResult(
        ok: ok,
        printed: printed,
        errorCode: errorCode,
        errorMessage: errorMessage,
        truncated: truncated,
        printerName: name,
      );
}
