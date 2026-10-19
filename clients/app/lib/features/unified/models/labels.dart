import 'dart:convert';
import 'dart:math' as math;
import 'dart:typed_data';

import 'json_read.dart';

/// Physical A4 sheet the labels are laid out on.
const double a4WidthMm = 210.0;
const double a4HeightMm = 297.0;

/// Smallest label the designer accepts (below this the QR cannot be scanned).
const double minLabelMm = 5.0;

/// Field ids the label designer may print as TEXT.
///
/// Exactly one QR is printed per label and it is NOT part of this list: the
/// server draws the bag trace (`LABB:`) or the location code (`LABL:`) itself.
/// Any QR-ish id is ignored here and reported as a validation warning, so no
/// configuration can produce a second code on one label.
const List<({String id, String label})> kLabelFields = <({String id, String label})>[
  (id: 'sn', label: '内部 SN'),
  (id: 'location', label: '库位码'),
  (id: 'trace_code', label: '追溯码'),
  (id: 'mpn', label: '型号 MPN'),
  (id: 'catalog_code', label: '立创编号'),
  (id: 'name', label: '名称/规格'),
  (id: 'brand', label: '品牌'),
  (id: 'package', label: '封装'),
  (id: 'parameters', label: '参数'),
];

/// Field ids that would mean "print another code": always refused.
const Set<String> kForbiddenLabelFields = <String>{
  'qr',
  'qrcode',
  'qr_code',
  'barcode',
  'trace_qr',
  'code128',
};

/// What a label identifies. The user's rule: a material label identifies the
/// bag/batch (with its trace code); a location label identifies the location.
enum LabelKind {
  bag,
  location;

  /// Value sent to `/lab/api/labels/preview`.
  String get wire => name;

  String get displayName => this == LabelKind.bag ? '器件追溯标签' : '库位标签';

  /// Payload prefix the label's single QR carries.
  String get payloadPrefix => this == LabelKind.bag ? 'LABB:' : 'LABL:';

  /// Sensible default text fields for this kind.
  List<String> get defaultFields => this == LabelKind.bag
      ? const <String>['sn', 'catalog_code', 'mpn', 'parameters', 'location']
      : const <String>['location', 'name'];
}

/// Everything the operator configured in millimetres.
class LabelSpec {
  const LabelSpec({
    required this.kind,
    required this.ids,
    required this.copies,
    required this.widthMm,
    required this.heightMm,
    required this.marginMm,
    required this.gapMm,
    required this.fields,
  });

  /// Bags (`bag.id`) or locations (`location.id`) to print.
  final LabelKind kind;
  final List<int> ids;

  /// Copies per selected object (re-printing never touches stock).
  final int copies;

  final double widthMm;
  final double heightMm;

  /// Page margin on every side of the A4 sheet.
  final double marginMm;

  /// Gap between two neighbouring labels.
  final double gapMm;

  /// Text fields to print (see [kLabelFields]).
  final List<String> fields;

  /// Total labels this job produces.
  int get labelCount => ids.length * math.max(copies, 0);

  LabelSpec copyWith({
    LabelKind? kind,
    List<int>? ids,
    int? copies,
    double? widthMm,
    double? heightMm,
    double? marginMm,
    double? gapMm,
    List<String>? fields,
  }) {
    return LabelSpec(
      kind: kind ?? this.kind,
      ids: ids ?? this.ids,
      copies: copies ?? this.copies,
      widthMm: widthMm ?? this.widthMm,
      heightMm: heightMm ?? this.heightMm,
      marginMm: marginMm ?? this.marginMm,
      gapMm: gapMm ?? this.gapMm,
      fields: fields ?? this.fields,
    );
  }

  /// Request body for `/lab/api/labels/preview`.
  ///
  /// QR-ish fields are filtered out here as well as in validation: the wire
  /// payload can never ask for a second code.
  Map<String, dynamic> toParams() {
    return <String, dynamic>{
      'kind': kind.wire,
      'ids': ids,
      'copies': copies,
      'width_mm': widthMm,
      'height_mm': heightMm,
      'margin_mm': marginMm,
      'gap_mm': gapMm,
      'fields': fields
          .where((field) => !kForbiddenLabelFields.contains(field.toLowerCase()))
          .toList(),
    };
  }
}

/// The A4 layout plan: what fits, how many per page, how many pages.
class LabelLayout {
  const LabelLayout({
    required this.usableWidthMm,
    required this.usableHeightMm,
    required this.columns,
    required this.rows,
    required this.capacityPerPage,
    required this.pages,
    required this.labelCount,
    required this.errors,
    required this.warnings,
    required this.effectiveFields,
  });

  final double usableWidthMm;
  final double usableHeightMm;
  final int columns;
  final int rows;
  final int capacityPerPage;
  final int pages;
  final int labelCount;

  /// Blocking problems: the request must not be sent while this is non-empty.
  final List<String> errors;

  /// Non-blocking notes (e.g. no text field selected).
  final List<String> warnings;

  /// Fields actually sent (QR-ish ids removed).
  final List<String> effectiveFields;

  bool get isValid => errors.isEmpty;

  bool get overflows => errors.any((error) => error.contains('超出'));

  String get summary =>
      '每页 $columns 列 × $rows 行 = $capacityPerPage 张，共 $pages 页，$labelCount 张';
}

/// Validates a spec against the real A4 sheet and plans the pages.
///
/// A label that cannot physically fit is an ERROR, never a silent crop: the
/// user's requirement is an explicit refusal.
LabelLayout planLabels(LabelSpec spec) {
  final errors = <String>[];
  final warnings = <String>[];

  final margin = spec.marginMm;
  final usableWidth = a4WidthMm - 2 * margin;
  final usableHeight = a4HeightMm - 2 * margin;

  if (spec.ids.isEmpty) {
    errors.add('请先选择要打印的${spec.kind == LabelKind.bag ? '器件或追溯袋' : '库位'}。');
  }
  if (spec.copies < 1) {
    errors.add('份数至少为 1。');
  }
  if (margin < 0) {
    errors.add('页边距不能为负数。');
  }
  if (spec.gapMm < 0) {
    errors.add('标签间距不能为负数。');
  }
  if (spec.widthMm < minLabelMm || spec.heightMm < minLabelMm) {
    errors.add('标签宽高不能小于 $minLabelMm mm（再小二维码无法扫描）。');
  }
  if (usableWidth <= 0 || usableHeight <= 0) {
    errors.add(
      '页边距 ${_mm(margin)} mm 过大：A4（${_mm(a4WidthMm)}×${_mm(a4HeightMm)} mm）没有可用区域。',
    );
  }

  var columns = 0;
  var rows = 0;
  if (errors.isEmpty) {
    if (spec.widthMm > usableWidth + 0.01) {
      errors.add(
        '标签宽度 ${_mm(spec.widthMm)} mm 超出 A4 可用宽度 ${_mm(usableWidth)} mm'
        '（页边距 ${_mm(margin)} mm）。请缩小宽度或页边距。',
      );
    }
    if (spec.heightMm > usableHeight + 0.01) {
      errors.add(
        '标签高度 ${_mm(spec.heightMm)} mm 超出 A4 可用高度 ${_mm(usableHeight)} mm'
        '（页边距 ${_mm(margin)} mm）。请缩小高度或页边距。',
      );
    }
    if (errors.isEmpty) {
      columns = math.max(1, ((usableWidth + spec.gapMm) / (spec.widthMm + spec.gapMm)).floor());
      rows = math.max(1, ((usableHeight + spec.gapMm) / (spec.heightMm + spec.gapMm)).floor());
    }
  }

  final capacity = columns * rows;
  final labelCount = spec.labelCount;
  final pages = capacity > 0 ? (labelCount / capacity).ceil() : 0;

  final effectiveFields = spec.fields
      .where((field) => !kForbiddenLabelFields.contains(field.toLowerCase()))
      .toList();
  final refused = spec.fields
      .where((field) => kForbiddenLabelFields.contains(field.toLowerCase()))
      .toList();
  if (refused.isNotEmpty) {
    warnings.add('已忽略试图额外打印二维码的字段：${refused.join('、')}（每个标签只印一个二维码）。');
  }
  if (effectiveFields.isEmpty) {
    warnings.add('未选择文字字段，标签上只有二维码。');
  }
  if (capacity > 0 && labelCount > 0 && pages > 1) {
    warnings.add('$labelCount 张标签需要 $pages 页 A4，将生成多页 PDF。');
  }

  return LabelLayout(
    usableWidthMm: usableWidth < 0 ? 0 : usableWidth,
    usableHeightMm: usableHeight < 0 ? 0 : usableHeight,
    columns: columns,
    rows: rows,
    capacityPerPage: capacity,
    pages: pages,
    labelCount: labelCount,
    errors: errors,
    warnings: warnings,
    effectiveFields: effectiveFields,
  );
}

/// `/lab/api/labels/preview` result: a REAL PDF, decoded from base64.
class LabelPdfResult {
  const LabelPdfResult({
    required this.bytes,
    required this.filename,
    required this.pageCount,
    required this.labelCount,
    required this.mimeType,
  });

  final Uint8List bytes;
  final String filename;
  final int pageCount;
  final int labelCount;
  final String mimeType;

  bool get isPdf => bytes.length > 3 &&
      bytes[0] == 0x25 &&
      bytes[1] == 0x50 &&
      bytes[2] == 0x44 &&
      bytes[3] == 0x46; // "%PDF"

  double get sizeKb => bytes.length / 1024;

  String get summary => '$labelCount 张标签 · $pageCount 页 · ${sizeKb.toStringAsFixed(1)} KB';

  factory LabelPdfResult.fromJson(Map<String, dynamic> json) {
    return LabelPdfResult(
      bytes: decodePdfBase64(json['pdf_base64'] ?? json['pdf'] ?? json['base64']),
      filename: firstString(json, const ['filename', 'file_name', 'name']) ?? 'labels.pdf',
      pageCount: firstInt(json, const ['page_count', 'pages']) ?? 0,
      labelCount: firstInt(json, const ['label_count', 'labels']) ?? 0,
      mimeType: firstString(json, const ['mime_type', 'mimetype']) ?? 'application/pdf',
    );
  }
}

/// Decodes the base64 PDF the server returns.
///
/// Tolerates the three shapes seen in the wild: a bare base64 string, a
/// `data:application/pdf;base64,` URI, and base64 with embedded newlines
/// (Odoo's `ir.attachment.datas` arrives wrapped).
Uint8List decodePdfBase64(Object? value) {
  final text = asString(value);
  if (text == null) return Uint8List(0);
  var payload = text;
  final comma = payload.indexOf(',');
  if (payload.startsWith('data:') && comma > 0) {
    payload = payload.substring(comma + 1);
  }
  // Odoo's ir.attachment datas and most JSON transports wrap long base64 in
  // newlines/spaces; strip them explicitly (base64.normalize alone is not
  // guaranteed to drop every whitespace character).
  payload = payload.replaceAll(RegExp(r'\s+'), '');
  if (payload.isEmpty) return Uint8List(0);
  try {
    return base64.decode(base64.normalize(payload));
  } on FormatException {
    return Uint8List(0);
  }
}

String _mm(double value) {
  if (value == value.roundToDouble()) return value.toInt().toString();
  return value.toStringAsFixed(1);
}
