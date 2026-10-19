import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/lab_api_exception.dart';
import '../../../services/lab_api_client.dart';
import '../models/labels.dart';
import '../services/pdf_output.dart';
import 'unified_providers.dart';

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

  bool get canPreview => !submitting && layout.isValid;

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
