import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/labels.dart';
import 'package:lab_inventory_client/services/niimbot_printer.dart';

/// NIIMBOT printer: error-code translation, printer-list parsing and the
/// "unavailable ⇒ refuse, never pretend" contract.
///
/// The FFI call sequence (initSdk → selectPrinter → startJob_New → …) is NOT
/// exercised here: it needs `jcPrinterApi.dll` and a real USB printer. Those
/// are BLOCKED for automated tests; see the handoff note.
void main() {
  group('error-code translation', () {
    test('the documented codes map to Chinese messages', () {
      expect(niimbotErrorMessage(0), '无错误');
      expect(niimbotErrorMessage(1), contains('盒盖'));
      expect(niimbotErrorMessage(2), contains('缺纸'));
      expect(niimbotErrorMessage(3), contains('电量'));
      expect(niimbotErrorMessage(7), contains('温度过高'));
      expect(niimbotErrorMessage(22), contains('超时'));
      expect(niimbotErrorMessage(23), contains('断开'));
      expect(niimbotErrorMessage(31), contains('不支持'));
      expect(niimbotErrorMessage(63), contains('超限'));
    });

    test('startJob_New negative codes are translated too', () {
      expect(niimbotErrorMessage(-1), contains('开启打印任务失败'));
      expect(niimbotErrorMessage(-2), contains('忙碌'));
      expect(niimbotErrorMessage(-3), contains('不支持'));
    });

    test('an unknown code is still explicit, never blank', () {
      expect(niimbotErrorMessage(9999), contains('9999'));
      expect(niimbotErrorMessage(9999), contains('未知'));
    });

    test('every documented code has a non-empty Chinese message', () {
      for (final code in <int>[
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
        20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 34, 35, 50, 51, 52,
        53, 58, 59, 60, 61, 62, 63, 255,
      ]) {
        final message = kNiimbotErrorMessages[code];
        expect(message, isNotNull, reason: 'code $code must be documented');
        expect(message!.trim(), isNotEmpty);
      }
    });
  });

  group('getAllPrinters JSON', () {
    test('parses the documented {name: port} object', () {
      final printers = parsePrintersJson('{"S6_0011223344":"4"}');
      expect(printers, hasLength(1));
      expect(printers.single.name, 'S6_0011223344');
      expect(printers.single.port, 4);
      expect(printers.single.toString(), contains('端口 4'));
    });

    test('accepts an array shape and skips unusable rows', () {
      final printers = parsePrintersJson(
        '[{"name":"A","port":1},{"name":"","port":2},{"name":"B","port":"x"},{"printerName":"C","portName":3}]',
      );
      expect(printers.map((printer) => printer.name), <String>['A', 'C']);
      expect(printers.last.port, 3);
    });

    test('empty or invalid JSON yields an empty list, not a throw', () {
      expect(parsePrintersJson(''), isEmpty);
      expect(parsePrintersJson('not json'), isEmpty);
      expect(parsePrintersJson('{}'), isEmpty);
    });
  });

  group('platform availability', () {
    test('non-Windows is always unavailable', () {
      expect(
        isNiimbotPlatformSupported(
          isWindows: false,
          is64Bit: true,
          dllExists: true,
        ),
        isFalse,
      );
    });

    test('32-bit Windows is unavailable (the SDK ships x64 only)', () {
      expect(
        isNiimbotPlatformSupported(
          isWindows: true,
          is64Bit: false,
          dllExists: true,
        ),
        isFalse,
      );
    });

    test('Windows x64 without the DLL is unavailable', () {
      expect(
        isNiimbotPlatformSupported(
          isWindows: true,
          is64Bit: true,
          dllExists: false,
        ),
        isFalse,
      );
    });

    test('Windows x64 with the DLL is available', () {
      expect(
        isNiimbotPlatformSupported(
          isWindows: true,
          is64Bit: true,
          dllExists: true,
        ),
        isTrue,
      );
    });

    test('on this test host (non-Windows) resolve() is null and a job refuses', () async {
      if (Platform.isWindows) return; // covered by the explicit cases above
      expect(NiimbotRuntime.resolve(), isNull);

      final printer = NiimbotLabelPrinter();
      expect(printer.available, isFalse);

      final result = await printer.print(
        widthMm: 40,
        heightMm: 20,
        contents: const <LabelContent>[
          LabelContent(
            kind: 'bag',
            refId: 1,
            payload: 'LABB:T',
            traceCode: 'T',
            title: 'SN-1',
            lines: <String>['名称：A'],
          ),
        ],
      );

      expect(result.ok, isFalse, reason: 'must never report success without a printer');
      expect(result.printed, 0);
      expect(result.errorMessage, contains('Windows'));
      expect(result.summary, contains('失败'));
    });

    test('a label without a QR is refused before touching the SDK', () async {
      final printer = NiimbotLabelPrinter(
        runtime: const NiimbotRuntime(
          libraryPath: 'missing.dll',
          fontDir: 'missing-font',
        ),
      );
      final result = await printer.print(
        widthMm: 40,
        heightMm: 20,
        contents: const <LabelContent>[
          LabelContent(
            kind: 'bag',
            refId: 1,
            payload: '',
            traceCode: 'T',
            title: 'SN-1',
            lines: <String>[],
          ),
        ],
      );
      expect(result.ok, isFalse);
      expect(result.errorMessage, contains('二维码'));
    });

    test('a stock too small for a readable label is refused', () async {
      final printer = NiimbotLabelPrinter(
        runtime: const NiimbotRuntime(
          libraryPath: 'missing.dll',
          fontDir: 'missing-font',
        ),
      );
      final result = await printer.print(
        widthMm: 10,
        heightMm: 20,
        contents: const <LabelContent>[
          LabelContent(
            kind: 'bag',
            refId: 1,
            payload: 'LABB:T',
            traceCode: 'T',
            title: 'SN-1',
            lines: <String>['名称：A'],
          ),
        ],
      );
      expect(result.ok, isFalse);
      expect(result.errorMessage, contains('放不下'));
    });
  });

  group('result summary', () {
    test('success says how many labels were printed', () {
      const result = NiimbotPrintResult(
        ok: true,
        printed: 3,
        errorCode: 0,
        errorMessage: null,
        truncated: false,
        printerName: 'S6_1',
      );
      expect(result.summary, contains('已直打 3 张'));
      expect(result.summary, contains('S6_1'));
      expect(result.summary, isNot(contains('失败')));
    });

    test('failure never claims success and shows the error code', () {
      final result = NiimbotPrintResult.failure('缺纸（请装入标签纸）', errorCode: 2);
      expect(result.summary, contains('失败'));
      expect(result.summary, contains('缺纸'));
      expect(result.summary, contains('错误码 2'));
      expect(result.summary, isNot(contains('已直打')));
    });

    test('truncation is disclosed on an otherwise successful job', () {
      const result = NiimbotPrintResult(
        ok: true,
        printed: 1,
        errorCode: 0,
        errorMessage: null,
        truncated: true,
      );
      expect(result.summary, contains('省略'));
    });
  });
}
