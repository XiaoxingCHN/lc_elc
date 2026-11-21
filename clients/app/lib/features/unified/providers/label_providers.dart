import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/lab_api_exception.dart';
import '../../../services/lab_api_client.dart';
import '../../../services/niimbot_android_printer.dart';
import '../../../services/niimbot_printer.dart';
import '../models/labels.dart';
import '../services/pdf_output.dart';
import 'unified_providers.dart';

/// Whether this build can print directly to a NIIMBOT (精臣) thermal printer.
///
/// True only on Windows x64 with `jcPrinterApi.dll` beside the executable; the
/// UI hides the direct-print action otherwise instead of showing a dead button.
/// Overridable in tests and on a machine where the SDK is provisioned later.
final niimbotAvailableProvider = Provider<bool>((ref) {
  return NiimbotRuntime.resolve() != null;
});

/// Builds the direct-print job for the current label selection.
final niimbotLabelPrinterProvider = Provider<NiimbotLabelPrinter>((ref) {
  return NiimbotLabelPrinter();
});

/// Android Bluetooth printing (精臣 B1 Pro via SDK 4.1.1).
///
/// Separate from [niimbotAvailableProvider]: that one gates the Windows FFI
/// path, this one the Android MethodChannel path. The UI shows the Bluetooth
/// area only when this platform is Android AND the native SDK initialised.
final niimbotAndroidPrinterProvider = Provider<NiimbotAndroidPrinter>((ref) {
  return NiimbotAndroidPrinter();
});

/// One Bluetooth scan/connect/print session on Android.
///
/// State is explicit so the UI can never show a success it did not get:
/// [error] is set on every failure, [notice] only after a real print job.
class AndroidPrinterState {
  const AndroidPrinterState({
    this.checking = false,
    this.available = false,
    this.unavailableReason,
    this.scanning = false,
    this.devices = const <NiimbotAndroidDevice>[],
    this.connected,
    this.printing = false,
    this.printed = 0,
    this.truncated = false,
    this.error,
    this.notice,
  });

  /// The native `available` call is in flight.
  final bool checking;

  /// SDK initialised successfully on this device.
  final bool available;

  /// Why it is not available (shown only when [available] is false).
  final String? unavailableReason;

  final bool scanning;
  final List<NiimbotAndroidDevice> devices;

  /// Connected printer, null when none.
  final NiimbotAndroidDevice? connected;

  final bool printing;
  final int printed;
  final bool truncated;

  /// Specific Chinese reason of the last failure (never a success message).
  final String? error;

  /// Success message of the last real print.
  final String? notice;

  bool get canScan => available && !scanning && !printing;
  bool get canPrint => available && connected != null && !printing;

  AndroidPrinterState copyWith({
    bool? checking,
    bool? available,
    Object? unavailableReason = _unset,
    bool? scanning,
    List<NiimbotAndroidDevice>? devices,
    Object? connected = _unset,
    bool? printing,
    int? printed,
    bool? truncated,
    Object? error = _unset,
    Object? notice = _unset,
  }) {
    return AndroidPrinterState(
      checking: checking ?? this.checking,
      available: available ?? this.available,
      unavailableReason: identical(unavailableReason, _unset)
          ? this.unavailableReason
          : unavailableReason as String?,
      scanning: scanning ?? this.scanning,
      devices: devices ?? this.devices,
      connected: identical(connected, _unset)
          ? this.connected
          : connected as NiimbotAndroidDevice?,
      printing: printing ?? this.printing,
      printed: printed ?? this.printed,
      truncated: truncated ?? this.truncated,
      error: identical(error, _unset) ? this.error : error as String?,
      notice: identical(notice, _unset) ? this.notice : notice as String?,
    );
  }

  static const Object _unset = Object();
}

class AndroidPrinterController extends StateNotifier<AndroidPrinterState> {
  AndroidPrinterController({
    required this._api,
    required this._printer,
    bool? supported,
  })  : _supported = supported ?? NiimbotAndroidPrinter.supported,
        super(const AndroidPrinterState());

  final LabApiClient _api;
  final NiimbotAndroidPrinter _printer;
  final bool _supported;

  StreamSubscription<NiimbotAndroidScanEvent>? _scan;
  bool _disposed = false;

  /// Whether the UI should show the Bluetooth area at all.
  bool get supported => _supported;

  /// Probes the native SDK once. Hidden (not an error) on non-Android hosts.
  Future<void> refresh() async {
    if (!_supported) {
      state = const AndroidPrinterState();
      return;
    }
    state = state.copyWith(checking: true, error: null);
    final result = await _printer.available();
    if (_disposed) return;
    state = state.copyWith(
      checking: false,
      available: result.available,
      unavailableReason: result.reason,
    );
  }

  /// Asks for the Bluetooth permissions; returns true when granted.
  ///
  /// A refusal is reported as a specific Chinese error with a retry hint.
  Future<bool> requestPermission() async {
    final granted = await _printer.requestPermissions();
    if (!granted && !_disposed) {
      state = state.copyWith(
        error: '未获得蓝牙权限。请在系统设置中允许本应用使用附近设备/位置权限后重试。',
      );
    }
    return granted;
  }

  Future<void> startScan() async {
    if (!_supported || state.scanning) return;
    if (!await requestPermission()) return;
    await stopScan();
    state = state.copyWith(
      scanning: true,
      devices: const <NiimbotAndroidDevice>[],
      error: null,
      notice: null,
    );
    final seen = <String>{};
    _scan = _printer.scan().listen(
      (event) {
        if (_disposed) return;
        if (event.isDevice) {
          final device = event.device!;
          if (!seen.add(device.address.toUpperCase())) return;
          state = state.copyWith(
            devices: <NiimbotAndroidDevice>[...state.devices, device],
          );
        } else if (event.isFinished) {
          state = state.copyWith(scanning: false);
        } else if (event.isError) {
          state = state.copyWith(
            scanning: false,
            error: event.errorMessage ?? '蓝牙搜索失败，请重试。',
          );
        }
      },
      onError: (Object error) {
        if (_disposed) return;
        state = state.copyWith(scanning: false, error: '蓝牙搜索失败：$error');
      },
      onDone: () {
        if (_disposed) return;
        if (state.scanning) state = state.copyWith(scanning: false);
      },
    );
  }

  Future<void> stopScan() async {
    await _scan?.cancel();
    _scan = null;
    await _printer.stopScan();
    if (!_disposed && state.scanning) {
      state = state.copyWith(scanning: false);
    }
  }

  /// Connects to [device]; a failure leaves [connected] null.
  ///
  /// Any running scan is stopped first: doc3 §4 requires discovery to be
  /// cancelled before a connection, and the UI must not keep saying
  /// "停止搜索" while connecting.
  Future<bool> connect(NiimbotAndroidDevice device) async {
    if (state.scanning) await stopScan();
    state = state.copyWith(error: null, notice: null);
    final result = await _printer.connect(device.address);
    if (_disposed) return result.connected;
    if (!result.connected) {
      state = state.copyWith(connected: null, error: result.summary);
      return false;
    }
    state = state.copyWith(
      connected: device,
      notice: '已连接 ${device.display}。',
      error: null,
    );
    return true;
  }

  Future<void> disconnect() async {
    await _printer.disconnect();
    if (_disposed) return;
    state = state.copyWith(connected: null, notice: '已断开打印机。');
  }

  /// Fetches the structured label content (the SAME read-only preview
  /// endpoint) and prints it over Bluetooth.
  ///
  /// Nothing here writes stock, and a failure never sets [notice].
  Future<NiimbotPrintResult> printSpec(LabelSpec spec) async {
    final layout = planLabels(spec);
    if (!layout.isValid) {
      final message = layout.errors.join('\n');
      state = state.copyWith(error: message);
      return NiimbotPrintResult.failure(message);
    }
    final device = state.connected;
    if (device == null) {
      const message = '尚未连接蓝牙打印机，请先搜索并连接。';
      state = state.copyWith(error: message);
      return NiimbotPrintResult.failure(message);
    }
    if (state.printing) {
      return NiimbotPrintResult.failure('已有打印任务正在进行，请等待完成。');
    }
    state = state.copyWith(printing: true, error: null, notice: null);
    try {
      final preview = await _api.previewLabels(spec, includeContent: true);
      if (!preview.hasContents) {
        const message = '服务器没有返回标签直打内容，请改用「系统打印」。';
        state = state.copyWith(printing: false, error: message);
        return NiimbotPrintResult.failure(message);
      }
      // The server already expanded copies into contents; one commit per page.
      final result = await _printer.print(
        widthMm: spec.widthMm,
        heightMm: spec.heightMm,
        contents: preview.contents,
        modelName: device.name,
      );
      if (_disposed) return result;
      if (!result.ok) {
        state = state.copyWith(
          printing: false,
          printed: result.printed,
          truncated: result.truncated,
          error: result.summary,
          notice: null,
        );
        return result;
      }
      state = state.copyWith(
        printing: false,
        printed: result.printed,
        truncated: result.truncated,
        notice: '${result.summary}重新打印不会改变库存。',
        error: null,
      );
      return result;
    } on LabApiException catch (error) {
      if (!_disposed) {
        state = state.copyWith(printing: false, error: error.message);
      }
      return NiimbotPrintResult.failure(error.message);
    } catch (error) {
      final message = '蓝牙直打失败：$error';
      if (!_disposed) state = state.copyWith(printing: false, error: message);
      return NiimbotPrintResult.failure(message);
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _scan?.cancel();
    _scan = null;
    super.dispose();
  }
}

final androidPrinterProvider =
    StateNotifierProvider<AndroidPrinterController, AndroidPrinterState>((ref) {
  final controller = AndroidPrinterController(
    api: ref.watch(labApiProvider),
    printer: ref.watch(niimbotAndroidPrinterProvider),
  );
  if (controller.supported) {
    // Probe once when the designer is built; a non-Android host stays hidden.
    unawaited(controller.refresh());
  }
  return controller;
});

/// Designer state for one label job.
///
/// The layout is computed locally from the millimetre inputs BEFORE anything is
/// requested, so an oversized label is refused with an explicit Chinese message
/// instead of being silently cropped by the server or the printer.
class LabelDesignerState {
  const LabelDesignerState({
    this.kind = LabelKind.bag,
    this.selection = const <int, String>{},
    this.copies = 1,
    this.widthMm = 60,
    this.heightMm = 40,
    this.marginMm = 10,
    this.gapMm = 2,
    this.fields = const <String>['trace_code', 'name', 'mpn', 'catalog_code', 'package', 'parameters'],
    this.submitting = false,
    this.error,
    this.errorCode,
    this.notice,
    this.pdf,
    this.printingDirect = false,
  });

  final LabelKind kind;

  /// Selected bag ids (kind == bag) or location ids (kind == location), with
  /// the label to show for each.
  final Map<int, String> selection;

  final int copies;
  final double widthMm;
  final double heightMm;
  final double marginMm;
  final double gapMm;
  final List<String> fields;

  final bool submitting;
  final String? error;
  final String? errorCode;
  final String? notice;

  /// The rendered PDF of the last successful preview.
  final LabelPdfResult? pdf;

  /// A direct thermal print is in flight (blocks a second submission).
  final bool printingDirect;

  List<int> get ids => selection.keys.toList();

  LabelSpec get spec => LabelSpec(
        kind: kind,
        ids: ids,
        copies: copies,
        widthMm: widthMm,
        heightMm: heightMm,
        marginMm: marginMm,
        gapMm: gapMm,
        fields: fields,
      );

  /// A4 plan: columns, rows, pages, and any blocking overflow message.
  LabelLayout get layout => planLabels(spec);

  bool get canPreview => !submitting && !printingDirect && layout.isValid;

  bool get hasPdf => pdf != null && pdf!.bytes.isNotEmpty;

  LabelDesignerState copyWith({
    LabelKind? kind,
    Map<int, String>? selection,
    int? copies,
    double? widthMm,
    double? heightMm,
    double? marginMm,
    double? gapMm,
    List<String>? fields,
    bool? submitting,
    bool? printingDirect,
    Object? error = _unset,
    Object? errorCode = _unset,
    Object? notice = _unset,
    Object? pdf = _unset,
  }) {
    return LabelDesignerState(
      kind: kind ?? this.kind,
      selection: selection ?? this.selection,
      copies: copies ?? this.copies,
      widthMm: widthMm ?? this.widthMm,
      heightMm: heightMm ?? this.heightMm,
      marginMm: marginMm ?? this.marginMm,
      gapMm: gapMm ?? this.gapMm,
      fields: fields ?? this.fields,
      submitting: submitting ?? this.submitting,
      printingDirect: printingDirect ?? this.printingDirect,
      error: identical(error, _unset) ? this.error : error as String?,
      errorCode: identical(errorCode, _unset) ? this.errorCode : errorCode as String?,
      notice: identical(notice, _unset) ? this.notice : notice as String?,
      pdf: identical(pdf, _unset) ? this.pdf : pdf as LabelPdfResult?,
    );
  }

  static const Object _unset = Object();
}

/// Drives the label designer: millimetre configuration, A4 preview, save, print.
///
/// Reprinting an existing label performs the SAME preview call and never
/// touches `/lab/api/inventory/*`: there is no code path from here to a stock
/// write of any kind.
class LabelDesignerNotifier extends StateNotifier<LabelDesignerState> {
  LabelDesignerNotifier({required LabApiClient api, PdfOutputService? pdfOutput})
      : _api = api,
        _pdfOutput = pdfOutput ?? PdfOutputService(),
        super(const LabelDesignerState());

  final LabApiClient _api;
  final PdfOutputService _pdfOutput;

  void setKind(LabelKind kind) {
    if (kind == state.kind) return;
    state = state.copyWith(
      kind: kind,
      selection: const <int, String>{},
      fields: kind.defaultFields,
      pdf: null,
      error: null,
      notice: null,
    );
  }

  /// Adds/removes one bag or location, with its display label.
  void toggleSelection(int id, String label) {
    final selection = Map<int, String>.of(state.selection);
    if (selection.containsKey(id)) {
      selection.remove(id);
    } else {
      selection[id] = label;
    }
    state = state.copyWith(
      selection: selection,
      pdf: null,
      error: null,
      notice: null,
    );
  }

  void setSelection(Map<int, String> selection) {
    state = state.copyWith(
      selection: selection,
      pdf: null,
      error: null,
      notice: null,
    );
  }

  void clearSelection() {
    state = state.copyWith(
      selection: const <int, String>{},
      pdf: null,
      error: null,
      notice: null,
    );
  }

  void setCopies(int copies) =>
      state = state.copyWith(copies: copies < 1 ? 1 : copies, pdf: null, error: null);

  void setWidth(double value) =>
      state = state.copyWith(widthMm: value, pdf: null, error: null);

  void setHeight(double value) =>
      state = state.copyWith(heightMm: value, pdf: null, error: null);

  void setMargin(double value) =>
      state = state.copyWith(marginMm: value, pdf: null, error: null);

  void setGap(double value) =>
      state = state.copyWith(gapMm: value, pdf: null, error: null);

  void setFields(List<String> fields) =>
      state = state.copyWith(fields: fields, pdf: null, error: null);

  void toggleField(String field) {
    final fields = List<String>.of(state.fields);
    if (fields.contains(field)) {
      fields.remove(field);
    } else {
      fields.add(field);
    }
    state = state.copyWith(fields: fields, pdf: null, error: null);
  }

  /// Asks the server for the A4 PDF of the current configuration.
  Future<bool> preview() async {
    final layout = state.layout;
    if (!layout.isValid) {
      state = state.copyWith(error: layout.errors.join('\n'), errorCode: 'LABEL_LAYOUT');
      return false;
    }
    if (state.submitting) return false;

    state = state.copyWith(submitting: true, error: null, notice: null, pdf: null);
    try {
      final result = await _api.previewLabels(state.spec);
      if (result.bytes.isEmpty) {
        state = state.copyWith(
          submitting: false,
          error: '服务器返回了空的 PDF 内容，请重试。',
          errorCode: 'EMPTY_PDF',
        );
        return false;
      }
      state = state.copyWith(
        submitting: false,
        pdf: result,
        notice: '已生成 ${result.summary}（重新打印不会改变库存）。',
      );
      return true;
    } on LabApiException catch (error) {
      state = state.copyWith(
        submitting: false,
        error: error.message,
        errorCode: error.code,
      );
      return false;
    } catch (error) {
      state = state.copyWith(submitting: false, error: '生成标签失败：$error');
      return false;
    }
  }

  /// Saves the generated PDF to a real file.
  Future<PdfExportResult> save() async {
    final pdf = state.pdf;
    if (pdf == null || pdf.bytes.isEmpty) {
      return const PdfExportResult.failure('请先生成标签 PDF。');
    }
    final result = await _pdfOutput.save(pdf.bytes, pdf.filename);
    if (result.ok) {
      state = state.copyWith(notice: result.message);
    } else {
      state = state.copyWith(error: result.message);
    }
    return result;
  }

  /// Direct print to a NIIMBOT (精臣) thermal printer on Windows.
  ///
  /// The structured content comes from the SAME read-only preview endpoint
  /// (`include_content: true`), so the thermal label and the A4 PDF cannot
  /// disagree. Nothing here writes stock.
  ///
  /// A failure (no printer, out of paper, lid open, ...) is reported as an
  /// error and NEVER as success; the PDF stays available as the fallback.
  Future<NiimbotPrintResult> printDirect({
    NiimbotLabelPrinter? printer,
  }) async {
    final layout = state.layout;
    if (!layout.isValid) {
      final result = NiimbotPrintResult.failure(layout.errors.join('\n'));
      state = state.copyWith(error: result.errorMessage, errorCode: 'LABEL_LAYOUT');
      return result;
    }
    if (state.submitting || state.printingDirect) {
      return NiimbotPrintResult.failure('已有标签任务正在提交，请稍候。');
    }

    state = state.copyWith(
      printingDirect: true,
      error: null,
      errorCode: null,
      notice: null,
    );
    try {
      final preview = await _api.previewLabels(state.spec, includeContent: true);
      if (!preview.hasContents) {
        const message = '服务器没有返回标签直打内容，请改用「系统打印」。';
        state = state.copyWith(printingDirect: false, error: message, errorCode: 'NO_CONTENT');
        return NiimbotPrintResult.failure(message);
      }

      final job = printer ?? NiimbotLabelPrinter();
      if (!job.available) {
        const message = '当前系统或安装目录没有精臣打印组件（仅 Windows x64 支持直打），请改用「系统打印」。';
        state = state.copyWith(printingDirect: false, error: message, errorCode: 'NO_PRINTER_SDK');
        return NiimbotPrintResult.failure(message);
      }

      final result = await job.print(
        widthMm: state.widthMm,
        heightMm: state.heightMm,
        contents: preview.contents,
      );

      if (!result.ok) {
        state = state.copyWith(
          printingDirect: false,
          error: result.summary,
          errorCode: result.errorCode == null
              ? 'NIIMBOT_FAILED'
              : 'NIIMBOT_${result.errorCode}',
        );
        return result;
      }

      state = state.copyWith(
        printingDirect: false,
        notice: '${result.summary}重新打印不会改变库存。',
        pdf: preview.bytes.isEmpty ? state.pdf : preview,
      );
      return result;
    } on LabApiException catch (error) {
      state = state.copyWith(
        printingDirect: false,
        error: error.message,
        errorCode: error.code,
      );
      return NiimbotPrintResult.failure(error.message);
    } catch (error) {
      final message = '精臣直打失败：$error';
      state = state.copyWith(
        printingDirect: false,
        error: message,
        errorCode: 'NIIMBOT_FAILED',
      );
      return NiimbotPrintResult.failure(message);
    }
  }

  /// Opens the REAL system print dialog.
  Future<PdfExportResult> print() async {
    final pdf = state.pdf;
    if (pdf == null || pdf.bytes.isEmpty) {
      return const PdfExportResult.failure('请先生成标签 PDF。');
    }
    final result = await _pdfOutput.print(pdf.bytes, pdf.filename);
    if (!result.ok) state = state.copyWith(error: result.message);
    return result;
  }

  /// Platform share sheet (mobile "save to Files").
  Future<PdfExportResult> share() async {
    final pdf = state.pdf;
    if (pdf == null || pdf.bytes.isEmpty) {
      return const PdfExportResult.failure('请先生成标签 PDF。');
    }
    return _pdfOutput.share(pdf.bytes, pdf.filename);
  }

  Future<PdfCapabilities> capabilities() => _pdfOutput.capabilities();

  void reset() => state = const LabelDesignerState();
}

final labelDesignerProvider =
    StateNotifierProvider<LabelDesignerNotifier, LabelDesignerState>((ref) {
  // The designer is rebuilt on a session change so a previously generated PDF
  // and the bag/location ids of the old session are not reused.
  ref.watch(effectiveSessionScopeProvider);
  return LabelDesignerNotifier(
    api: ref.watch(labApiProvider),
    pdfOutput: ref.watch(pdfOutputProvider),
  );
});
