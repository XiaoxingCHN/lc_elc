import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/labels.dart';
import 'package:lab_inventory_client/services/niimbot_layout.dart';

/// NIIMBOT thermal label layout (40 × 20 mm stock).
///
/// Everything here is pure arithmetic: no DLL, no printer, no Windows. The FFI
/// call sequence itself is BLOCKED for unit tests (see the handoff note); these
/// tests pin the geometry, the font-size floor, the three-line cap and the
/// truncation reporting the operator is shown.
LabelContent content({
  String title = 'SN-0001',
  List<String> lines = const <String>[
    '追溯码：TRC-2026-0001',
    '名称：0.1uF 0402 50V X7R',
    '型号：CL05B104KO5NNNC',
    '封装：0402',
  ],
  String payload = 'LABB:TRC-2026-0001',
  String kind = 'bag',
}) {
  return LabelContent(
    kind: kind,
    refId: 42,
    payload: payload,
    traceCode: 'TRC-2026-0001',
    title: title,
    lines: lines,
  );
}

void main() {
  group('40x20 mm geometry', () {
    test('QR is 11 mm anchored at (1, 1) and text starts at x = 13.5 mm', () {
      final plan = planThermalLabel(content())!;

      expect(plan.widthMm, 40);
      expect(plan.heightMm, 20);
      expect(plan.qrX, closeTo(1.0, 1e-9), reason: 'flush to the left edge');
      expect(plan.qrY, closeTo(1.0, 1e-9), reason: 'flush to the top edge');
      expect(plan.qrSizeMm, closeTo(11, 1e-9));
      expect(plan.textX, closeTo(13.5, 1e-9), reason: '1 + 11 + 1.5 gap');
      expect(plan.textWidthMm, closeTo(24.5, 1e-9), reason: '40 - 13.5 - 2');
      // The corner anchor must stay inside the stock, quiet zone included.
      expect(plan.qrX + plan.qrSizeMm, lessThanOrEqualTo(40));
      expect(plan.qrY + plan.qrSizeMm, lessThanOrEqualTo(20));
    });

    test('the 11 mm QR still resolves for an 18-character payload', () {
      // 18 chars => QR version 2 (25 modules). 11 / 25 = 0.44 mm per module,
      // above the ~0.3 mm phones need and the ~0.25 mm scanners need.
      final plan = planThermalLabel(content())!;
      const modules = 25.0;
      expect(plan.qrSizeMm / modules, greaterThan(0.35),
          reason: 'shrinking the QR must not make it unscannable');
    });

    test('the payload travels with the plan (it is the only QR)', () {
      final plan = planThermalLabel(content(payload: 'LABL:K000001'))!;
      expect(plan.payload, 'LABL:K000001');
    });

    test('title is one line, body is capped at four lines', () {
      final plan = planThermalLabel(
        content(lines: <String>['追溯码：T', '名称：A', '型号：B', '封装：C', '参数：D']),
      )!;

      expect(plan.titleLine?.text, 'SN-0001');
      expect(plan.bodyLines.length, lessThanOrEqualTo(4));
      expect(plan.truncated, isTrue);
      // The 5th body line (参数：D) can never be drawn: only 4 slots exist.
      expect(plan.omittedLines, contains('D'));
    });

    test('lines are laid out top-down without overlapping', () {
      final plan = planThermalLabel(content())!;
      for (var index = 1; index < plan.lines.length; index++) {
        final previous = plan.lines[index - 1];
        final current = plan.lines[index];
        expect(current.yMm, greaterThanOrEqualTo(previous.yMm + previous.heightMm - 1e-9));
      }
      final last = plan.lines.last;
      expect(last.yMm + last.heightMm, lessThanOrEqualTo(20 - 1 + 1e-6),
          reason: 'must stay inside the 1 mm bottom margin');
    });

    test('a short bag label is never smaller than a full one', () {
      // NOTE: this is a BAG label with one field. A `kind: 'location'` label
      // takes the shelf geometry (QR + caption + big name) and has no body at
      // all, so it is asserted separately below.
      final short = planThermalLabel(
        content(title: 'SN-1', lines: const <String>['名称：A']),
      )!;
      final full = planThermalLabel(content())!;

      expect(short.bodyFontMm, greaterThanOrEqualTo(full.bodyFontMm));
      expect(short.bodyFontMm / mmPerPoint, lessThanOrEqualTo(7.5));
    });

    test('a long description shrinks the font instead of dropping a field', () {
      // Completeness beats size: at 7.4 pt this description needs three wrapped
      // lines and would be dropped by the two-line cap, taking 封装 with it.
      final long = planThermalLabel(
        content(lines: const <String>[
          '名称：0.1uF 0402 50V X7R 陶瓷电容 MLCC 高可靠',
          '型号：CL05B104KO5NNNC 0402 X7R 50V 10%',
        ]),
      )!;
      expect(long.omittedLines, isEmpty);
      expect(long.truncated, isFalse);
      expect(long.bodyFontMm, lessThan(kThermalMaxBodyFontMm),
          reason: 'a smaller size is what lets the full text fit');
      expect(long.bodyFontMm / mmPerPoint, greaterThanOrEqualTo(5.5 - 1e-6));
    });

    test('body never drops below the 5.5 pt floor', () {
      for (final sample in <LabelContent>[
        content(),
        content(lines: const <String>['追溯码：TRC-2026-0001', '名称：X', '型号：Y']),
        content(title: 'SN-0000000000000001', lines: const <String>['名称：很长很长很长的器件名称']),
      ]) {
        final plan = planThermalLabel(sample)!;
        expect(
          plan.bodyFontMm / mmPerPoint,
          greaterThanOrEqualTo(5.5 - 1e-6),
          reason: 'the server uses the same MIN_BODY_FONT_PT floor',
        );
      }
    });

    test('a too-small stock or a missing QR is refused (null)', () {
      expect(planThermalLabel(content(), widthMm: 10, heightMm: 20), isNull);
      expect(planThermalLabel(content(), widthMm: 40, heightMm: 5), isNull);
      expect(planThermalLabel(content(payload: '')), isNull);
    });

    test('a body line that repeats the title is not drawn twice', () {
      final plan = planThermalLabel(
        content(lines: const <String>['SN：SN-0001', '名称：A']),
      )!;
      // Prefixes are stripped on the thermal path: only the value is drawn.
      expect(plan.bodyLines.map((line) => line.text), <String>['A']);
    });
  });

  group('truncation reporting', () {
    test('a label that fits reports truncated = false', () {
      final plan = planThermalLabel(
        content(title: 'K000001', lines: const <String>['名称：货架A'], kind: 'location'),
      )!;
      expect(plan.truncated, isFalse);
      expect(plan.omittedLines, isEmpty);
    });

    test('an over-wide line shrinks the font rather than being dropped', () {
      // A name that needs three wrapped lines at the largest size fits two at a
      // smaller one, so the layout must give up a tenth of a millimetre of
      // glyph height - not the 型号 that follows it.
      final plan = planThermalLabel(
        content(
          title: 'SN-1',
          lines: const <String>[
            '名称：这是一个非常非常长的器件名称会超出文字区域',
            '型号：C2054912',
          ],
        ),
      )!;
      expect(plan.bodyLines.map((line) => line.text).join(), contains('非常非常长'));
      expect(plan.bodyLines.map((line) => line.text), contains('C2054912'));
      expect(plan.omittedLines, isEmpty);
      expect(plan.truncated, isFalse);
    });

    test('a lone over-wide line is wrapped instead of cut', () {
      final plan = planThermalLabel(
        content(
          title: 'SN-1',
          lines: const <String>['名称：这是一个非常非常长的器件名称会超出文字区域'],
        ),
      )!;
      // Wrapping carries the text over several lines; nothing is ellipsized and
      // nothing is dropped while it still fits the stock.
      expect(plan.bodyLines.length, greaterThan(1));
      expect(plan.bodyLines.every((line) => !line.ellipsized), isTrue);
      expect(plan.bodyLines.map((line) => line.text).join(), contains('非常非常长'));
    });

    test('every omitted line is reported in draw order', () {
      final plan = planThermalLabel(
        content(lines: const <String>['A：1', 'B：2', 'C：3', 'D：4', 'E：5']),
      )!;
      // Four slots exist, so the fifth value is the only one dropped; the
      // reported text is the stripped value because that is what would print.
      // Source lines are capped at four, so only the fifth is reported; the
      // value (prefix stripped) is what would have printed.
      expect(plan.omittedLines, <String>['5']);
    });
  });

  group('location (shelf) label', () {
    // Mirrors the SERVER's shape: `title` is the 库码 for a location label, and
    // the human name arrives as a body line ("名称：货架A").
    LabelContent location({
      String title = 'K000003',
      String code = 'K000003',
      List<String> lines = const <String>['库码：K000003', '名称：货架A'],
    }) =>
        LabelContent(
          kind: 'location',
          refId: 3,
          payload: 'LABL:$code',
          traceCode: code,
          title: title,
          lines: lines,
        );

    test('the 库码 sits UNDER the QR, in the QR column', () {
      final plan = planThermalLabel(location())!;

      expect(plan.caption, hasLength(1));
      final caption = plan.caption.single;
      expect(caption.text, 'K000003');
      // Directly below the code ...
      expect(caption.yMm, closeTo(plan.qrY + plan.qrSizeMm, 1e-9));
      // ... and inside the QR's own width, so it cannot drift under the name.
      expect(estimateTextWidthMm(caption.text, caption.fontMm),
          lessThanOrEqualTo(plan.qrSizeMm + 0.01));
      expect(caption.yMm + caption.heightMm, lessThanOrEqualTo(20 - 1 + 1e-6));
    });

    test('the caption comes from the payload, so it matches the QR exactly', () {
      // Even when the server's body line disagrees, the printed code is what the
      // code ENCODES - otherwise a scan would resolve something the label does
      // not say.
      final plan = planThermalLabel(
        location(code: 'K000009', lines: const <String>['库码：K000001']),
      )!;
      expect(plan.caption.single.text, 'K000009');
    });

    test('the name is the headline, beside the code, and much larger', () {
      final plan = planThermalLabel(
        location(lines: const <String>['库码：K000003', '名称：电阻货架']),
      )!;
      final name = plan.titleLine!;

      expect(name.text, '电阻货架');
      // Read while walking past the shelf, so it must dwarf the 库码 caption.
      expect(name.fontMm, greaterThan(kThermalCaptionFontMm * 2),
          reason: 'a shelf label must be readable from a metre away');
      expect(name.fontMm / mmPerPoint, greaterThanOrEqualTo(12),
          reason: 'the name is the headline of a shelf label');
      // It uses the wide column, not the QR column.
      expect(plan.textX, greaterThan(plan.qrX + plan.qrSizeMm));
      expect(plan.textWidthMm, greaterThan(plan.qrSizeMm));
    });

    test('a long name wraps instead of being cut', () {
      final plan = planThermalLabel(
        location(lines: const <String>['库码：K000003', '名称：第三排电阻电容货架A区']),
      )!;
      final names = plan.lines.where((line) => line.isTitle).toList();
      expect(names.length, greaterThanOrEqualTo(1));
      expect(names.every((line) => !line.ellipsized), isTrue);
      expect(names.map((line) => line.text).join(), contains('电阻'));
      // Nothing is reported missing: a shelf label has no fields to drop.
      expect(plan.omittedLines, isEmpty);
    });

    test('bag labels are unchanged by the location path', () {
      // The shelf geometry must not leak into component labels.
      final bag = planThermalLabel(content())!;
      expect(bag.caption, isEmpty);
      expect(bag.bodyLines.length, 4);
      expect(bag.titleLine?.text, 'SN-0001');
    });
  });

  group('text width estimate', () {
    test('CJK is square, ASCII is narrower', () {
      expect(estimateTextWidthMm('中文', 2.0), closeTo(4.0, 1e-9));
      expect(estimateTextWidthMm('WW', 2.0), closeTo(2.24, 1e-9));
      expect(estimateTextWidthMm(' ', 2.0), closeTo(0.6, 1e-9));
    });

    test('empty text has zero width', () {
      expect(estimateTextWidthMm('', 2.0), 0);
    });
  });

  group('LabelContent parsing', () {
    test('parses the documented server shape', () {
      final parsed = LabelContent.fromJson(<String, dynamic>{
        'kind': 'bag',
        'ref_id': 42,
        'payload': 'LABB:TRC-2026-0001',
        'trace_code': 'TRC-2026-0001',
        'title': 'SN-0001',
        'lines': <String>['追溯码：TRC-2026-0001', '名称：0.1uF 0402 50V X7R'],
      });

      expect(parsed.kind, 'bag');
      expect(parsed.refId, 42);
      expect(parsed.payload, 'LABB:TRC-2026-0001');
      expect(parsed.traceCode, 'TRC-2026-0001');
      expect(parsed.title, 'SN-0001');
      expect(parsed.lines, hasLength(2));
      expect(parsed.hasQr, isTrue);
      expect(parsed.allLines.first, 'SN-0001');
    });

    test('tolerates missing/odd fields without throwing', () {
      final parsed = LabelContent.fromJson(<String, dynamic>{
        'ref_id': '7',
        'lines': <Object?>['A', null, 5, <String>['nested']],
      });
      expect(parsed.refId, 7);
      expect(parsed.title, isEmpty);
      expect(parsed.lines, <String>['A', '5']);
      expect(parsed.hasQr, isFalse);
    });

    test('listFromJson skips non-map entries', () {
      final list = LabelContent.listFromJson(<Object?>[
        <String, dynamic>{'title': 'A', 'payload': 'LABB:A', 'lines': <String>[]},
        'junk',
        <String, dynamic>{'title': 'B', 'payload': 'LABB:B', 'lines': <String>[]},
      ]);
      expect(list.map((entry) => entry.title), <String>['A', 'B']);
    });

    test('the PDF result exposes contents only when the server sent them', () {
      final without = LabelPdfResult.fromJson(<String, dynamic>{
        'pdf_base64': 'JVBERi0xLjQK',
        'filename': 'labels.pdf',
      });
      expect(without.hasContents, isFalse);

      final withContents = LabelPdfResult.fromJson(<String, dynamic>{
        'pdf_base64': 'JVBERi0xLjQK',
        'filename': 'labels.pdf',
        'labels': <Map<String, dynamic>>[
          <String, dynamic>{
            'kind': 'bag',
            'payload': 'LABB:T',
            'title': 'SN-1',
            'lines': <String>['名称：A'],
          },
        ],
      });
      expect(withContents.hasContents, isTrue);
      expect(withContents.contents.single.payload, 'LABB:T');
    });
  });
}
