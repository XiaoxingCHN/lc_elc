import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/labels.dart';
import 'package:lab_inventory_client/features/unified/providers/label_providers.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';

import 'support/fake_lab_api.dart';

/// Label design, A4 bounds and PDF handling.
///
/// Pinned here: millimetre inputs are validated against the physical A4 usable
/// area (an oversized label is REFUSED, never cropped), exactly one QR is printed
/// per label, the PDF comes from the server as base64 and is decoded into real
/// bytes, and generating/reprinting a label touches no stock endpoint.
void main() {
  /// Compact spec builder for the layout cases.
  LabelSpec spec({
    LabelKind kind = LabelKind.bag,
    List<int> ids = const <int>[1],
    int copies = 1,
    double width = 50,
    double height = 30,
    double margin = 10,
    double gap = 2,
    List<String> fields = const <String>['sn', 'catalog_code'],
  }) {
    return LabelSpec(
      kind: kind,
      ids: ids,
      copies: copies,
      widthMm: width,
      heightMm: height,
      marginMm: margin,
      gapMm: gap,
      fields: fields,
    );
  }

  group('A4 layout', () {
    test('computes columns, rows and pages for a normal 50x30mm label', () {
      final layout = planLabels(spec(ids: <int>[1, 2, 3]));

      expect(layout.isValid, isTrue);
      expect(layout.usableWidthMm, 190);
      expect(layout.usableHeightMm, 277);
      // (190+2) / (50+2) = 3.69 -> 3 columns; (277+2) / (30+2) = 8.7 -> 8 rows
      expect(layout.columns, 3);
      expect(layout.rows, 8);
      expect(layout.capacityPerPage, 24);
      expect(layout.labelCount, 3);
      expect(layout.pages, 1);
      expect(layout.summary, contains('每页 3 列 × 8 行'));
    });

    test('refuses a label wider than the usable A4 width', () {
      final layout = planLabels(
        spec(kind: LabelKind.location, width: 250),
      );

      expect(layout.isValid, isFalse);
      expect(layout.overflows, isTrue);
      expect(layout.errors.single, contains('超出 A4 可用宽度'));
      expect(layout.columns, 0);
    });

    test('refuses a label taller than the usable A4 height', () {
      final layout = planLabels(spec(height: 300, margin: 5));

      expect(layout.isValid, isFalse);
      expect(layout.errors.single, contains('超出 A4 可用高度'));
    });

    test('refuses margins that eat the whole sheet', () {
      final layout = planLabels(spec(margin: 120));

      expect(layout.isValid, isFalse);
      expect(layout.errors.single, contains('没有可用区域'));
    });

    test('refuses an empty selection, a zero copy count and a tiny label', () {
      final empty = planLabels(spec(ids: const <int>[]));
      expect(empty.isValid, isFalse);
      expect(empty.errors.single, contains('请先选择'));

      final noCopies = planLabels(spec(copies: 0));
      expect(noCopies.errors, contains('份数至少为 1。'));

      final tiny = planLabels(spec(width: 3));
      expect(tiny.errors.single, contains('不能小于'));
    });

    test('multiple pages are planned for a large copy count', () {
      final layout = planLabels(spec(copies: 50));

      expect(layout.labelCount, 50);
      expect(layout.pages, 3, reason: '24 per page -> 50 labels need 3 pages');
      expect(layout.warnings.any((warning) => warning.contains('多页')), isTrue);
    });

    test('a second QR field is refused with a warning, not silently printed', () {
      final layout = planLabels(
        spec(fields: <String>['sn', 'qr', 'catalog_code', 'barcode']),
      );

      expect(layout.isValid, isTrue);
      expect(layout.effectiveFields, <String>['sn', 'catalog_code']);
      expect(layout.warnings.single, contains('每个标签只印一个二维码'));
    });

    test('the wire payload carries millimetres and no QR field', () {
      final params = spec(
        kind: LabelKind.location,
        ids: <int>[4],
        copies: 2,
        width: 40,
        height: 20,
        margin: 8,
        gap: 1,
        fields: <String>['location', 'qr'],
      ).toParams();

      expect(params['kind'], 'location');
      expect(params['ids'], <int>[4]);
      expect(params['copies'], 2);
      expect(params['width_mm'], 40.0);
      expect(params['height_mm'], 20.0);
      expect(params['margin_mm'], 8.0);
      expect(params['gap_mm'], 1.0);
      expect(params['fields'], <String>['location']);
    });

    test('the two label kinds carry the agreed payload prefixes', () {
      expect(LabelKind.bag.payloadPrefix, 'LABB:');
      expect(LabelKind.location.payloadPrefix, 'LABL:');
      expect(LabelKind.bag.defaultFields, contains('sn'));
      expect(LabelKind.location.defaultFields, contains('location'));
    });
  });

  group('PDF decoding', () {
    test('decodes plain base64', () {
      final bytes = decodePdfBase64(base64Encode(<int>[0x25, 0x50, 0x44, 0x46]));
      expect(bytes, <int>[0x25, 0x50, 0x44, 0x46]);
    });

    test('decodes a data: URI and base64 wrapped over several lines', () {
      final payload = base64Encode(List<int>.generate(120, (index) => index));
      final wrapped = <String>[];
      for (var index = 0; index < payload.length; index += 40) {
        wrapped.add(payload.substring(index, (index + 40).clamp(0, payload.length)));
      }

      final fromDataUri = decodePdfBase64('data:application/pdf;base64,$payload');
      final fromWrapped = decodePdfBase64(wrapped.join('\n'));
      expect(fromDataUri.length, 120);
      expect(fromWrapped, fromDataUri);
    });

    test('invalid base64 and an empty value decode to empty bytes', () {
      expect(decodePdfBase64('not base64 !!!'), isEmpty);
      expect(decodePdfBase64(null), isEmpty);
    });

    test('the result recognises a real PDF header', () {
      final result = LabelPdfResult(
        bytes: Uint8List.fromList(<int>[0x25, 0x50, 0x44, 0x46, 0x2D]),
        filename: 'labels.pdf',
        pageCount: 1,
        labelCount: 3,
        mimeType: 'application/pdf',
      );
      expect(result.isPdf, isTrue);
      expect(result.summary, contains('3 张标签'));
    });
  });

  group('designer flow', () {
    late FakeLabApi api;

    setUp(() {
      api = FakeLabApi();
    });

    LabelDesignerNotifier build() => LabelDesignerNotifier(api: api.client);

    test('an invalid layout never reaches the server', () async {
      final notifier = build();
      notifier.setWidth(250);
      notifier.toggleSelection(1, 'TRACE-1');

      expect(await notifier.preview(), isFalse);
      expect(notifier.state.error, contains('超出 A4 可用宽度'));
      expect(api.calls, isEmpty);
    });

    test('a valid preview decodes the PDF and writes NO stock', () async {
      final pdf = <int>[0x25, 0x50, 0x44, 0x46, 0x2D, 0x31, 0x2E, 0x34];
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.labelsPreview: <String, dynamic>{
          'pdf_base64': base64Encode(pdf),
          'filename': 'bag-labels.pdf',
          'page_count': 1,
          'label_count': 2,
          'mime_type': 'application/pdf',
        },
      });

      final notifier = build();
      notifier.toggleSelection(11, 'TRACE-11');
      notifier.setCopies(2);

      expect(await notifier.preview(), isTrue);
      expect(notifier.state.hasPdf, isTrue);
      expect(notifier.state.pdf!.bytes, pdf);
      expect(notifier.state.notice, contains('重新打印不会改变库存'));

      // Reprinting is the same read-only call - and nothing else.
      expect(api.countFor(LabApiRoutes.labelsPreview), 1);
      expect(api.countFor(LabApiRoutes.inventoryReceipt), 0);
      expect(api.countFor(LabApiRoutes.inventoryIssue), 0);
      expect(api.countFor(LabApiRoutes.inventoryReturn), 0);

      final params = api.onlyParams(LabApiRoutes.labelsPreview);
      expect(params['kind'], 'bag');
      expect(params['ids'], <int>[11]);
      expect(params['copies'], 2);
    });

    test('an empty PDF body is treated as a failure, not as success', () async {
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.labelsPreview: <String, dynamic>{
          'pdf_base64': '',
          'filename': 'labels.pdf',
        },
      });

      final notifier = build();
      notifier.toggleSelection(1, 'TRACE-1');

      expect(await notifier.preview(), isFalse);
      expect(notifier.state.error, contains('空的 PDF'));
      expect(notifier.state.hasPdf, isFalse);
    });

    test('a server-side label failure keeps the design for a retry', () async {
      api.onCall = (path, params) async => throw businessFailure(
            'VALIDATION_ERROR',
            '标签尺寸超出可用纸张范围。',
          );

      final notifier = build();
      notifier.toggleSelection(1, 'TRACE-1');
      notifier.setWidth(60);
      notifier.setHeight(40);

      expect(await notifier.preview(), isFalse);
      expect(notifier.state.error, '标签尺寸超出可用纸张范围。');
      expect(notifier.state.widthMm, 60);
      expect(notifier.state.selection, isNotEmpty);
    });

    test('switching kind resets the selection and the field defaults', () {
      final notifier = build();
      notifier.toggleSelection(1, 'TRACE-1');
      expect(notifier.state.fields, contains('sn'));

      notifier.setKind(LabelKind.location);

      expect(notifier.state.selection, isEmpty);
      expect(notifier.state.fields, contains('location'));
      expect(notifier.state.fields, isNot(contains('sn')));
    });

    test('changing a size invalidates a previously generated PDF', () async {
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.labelsPreview: <String, dynamic>{
          'pdf_base64': base64Encode(<int>[0x25, 0x50, 0x44, 0x46]),
          'filename': 'labels.pdf',
        },
      });

      final notifier = build();
      notifier.toggleSelection(1, 'TRACE-1');
      await notifier.preview();
      expect(notifier.state.hasPdf, isTrue);

      notifier.setHeight(25);
      expect(notifier.state.hasPdf, isFalse,
          reason: 'an old PDF must not be printed for a new size');
    });
  });
}
