import 'dart:async';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/labels.dart';
import 'package:lab_inventory_client/services/niimbot_android_printer.dart';

/// Dart half of the Android Bluetooth printer contract.
///
/// The native side (`NiimbotPrinterBridge.kt`) needs the vendor AAR and a real
/// B1 Pro; it is BLOCKED for automated tests. Everything reachable without a
/// device is pinned here: the MethodChannel/EventChannel protocol, the 40 × 20
/// mm geometry handed to the SDK, the Chinese error mapping and the
/// "unavailable ⇒ refuse, never pretend" rule.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const methodChannel = MethodChannel('lab/printer');
  const eventChannel = EventChannel('lab/printer/scan');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  late List<MethodCall> calls;

  void mockMethods(Future<Object?> Function(MethodCall call) handler) {
    messenger.setMockMethodCallHandler(methodChannel, (call) async {
      calls.add(call);
      return handler(call);
    });
  }

  void mockScanStream(MockStreamHandler handler) {
    messenger.setMockStreamHandler(eventChannel, handler);
  }

  LabelContent content({
    String payload = 'LABB:TRC-2026-0001',
    String title = 'SN-0001',
    List<String> lines = const <String>[
      '追溯码：TRC-2026-0001',
      '名称：0.1uF 0402 50V X7R',
      '型号：CL05B104KO5NNNC',
      '封装：0402',
    ],
  }) {
    return LabelContent(
      kind: 'bag',
      refId: 42,
      payload: payload,
      traceCode: 'TRC-2026-0001',
      title: title,
      lines: lines,
    );
  }

  setUp(() {
    calls = <MethodCall>[];
    NiimbotAndroidPrinter.platformOverride =
        const (android: true, windows: false, linux: false);
  });

  tearDown(() {
    messenger.setMockMethodCallHandler(methodChannel, null);
    messenger.setMockStreamHandler(eventChannel, null);
    NiimbotAndroidPrinter.platformOverride = null;
  });

  group('platform gating', () {
    test('non-Android hosts report unavailable and never touch the channel',
        () async {
      NiimbotAndroidPrinter.platformOverride =
          const (android: false, windows: false, linux: false);
      mockMethods((call) async => fail('channel must not be called: ${call.method}'));

      final printer = NiimbotAndroidPrinter();
      expect(NiimbotAndroidPrinter.supported, isFalse);
      final availability = await printer.available();
      expect(availability.available, isFalse);
      expect(availability.reason, contains('不支持'));

      final result = await printer.print(
        widthMm: 40,
        heightMm: 20,
        contents: <LabelContent>[content()],
      );
      expect(result.ok, isFalse);
      expect(calls, isEmpty);
    });

    test('a missing native plugin is reported as unavailable, not an error',
        () async {
      // No mock installed: the channel is unknown on this host.
      final printer = NiimbotAndroidPrinter();
      final availability = await printer.available();
      expect(availability.available, isFalse);
      expect(availability.reason, isNotNull);
    });

    test('the SDK availability reason is surfaced verbatim', () async {
      mockMethods((call) async => <String, Object?>{
            'available': false,
            'reason': '精臣打印组件初始化失败（字体资源不可用）',
          });

      final availability = await NiimbotAndroidPrinter().available();
      expect(availability.available, isFalse);
      expect(availability.reason, contains('字体资源不可用'));
    });
  });

  group('printMultiple', () {
    test('B1 Pro is a 300 dpi model', () {
      expect(NiimbotAndroidPrinter.printMultipleForModel('B1 Pro'), 11.81);
      expect(NiimbotAndroidPrinter.printMultipleForModel('B1 Pro-1234'), 11.81);
      expect(NiimbotAndroidPrinter.printMultipleForModel('B32'), 11.81);
    });

    test('other and missing names fall back to the 200 dpi factor', () {
      expect(NiimbotAndroidPrinter.printMultipleForModel('B21'), 8.0);
      expect(NiimbotAndroidPrinter.printMultipleForModel(null), 8.0);
      expect(NiimbotAndroidPrinter.printMultipleForModel(''), 8.0);
    });
  });

  group('scan', () {
    test('emits discovered devices then finished', () async {
      mockMethods((call) async => call.method == 'scan' ? true : null);
      mockScanStream(
        MockStreamHandler.inline(
          onListen: (arguments, sink) {
            sink.success(<String, Object?>{
              'type': 'device',
              'name': 'B1 Pro-1234',
              'address': 'AA:BB:CC:DD:EE:FF',
            });
            sink.success(<String, Object?>{
              'type': 'device',
              'name': '',
              'address': '11:22:33:44:55:66',
            });
            sink.success(<String, Object?>{'type': 'finished'});
          },
        ),
      );

      final events = <NiimbotAndroidScanEvent>[];
      final done = Completer<void>();
      final subscription = NiimbotAndroidPrinter().scan().listen((event) {
        events.add(event);
        if (event.isFinished && !done.isCompleted) done.complete();
      });
      await done.future.timeout(const Duration(seconds: 5));
      await subscription.cancel();

      expect(events, hasLength(3));
      expect(events[0].isDevice, isTrue);
      expect(events[0].device!.name, 'B1 Pro-1234');
      expect(events[0].device!.address, 'AA:BB:CC:DD:EE:FF');
      expect(events[1].device!.display, '11:22:33:44:55:66');
      expect(events[2].isFinished, isTrue);
      expect(calls.map((call) => call.method), contains('scan'));
    });

    test('a platform failure becomes a specific Chinese error event', () async {
      mockMethods((call) async {
        throw PlatformException(code: 'BLUETOOTH_OFF', message: '请先打开手机蓝牙，再搜索打印机。');
      });
      mockScanStream(MockStreamHandler.inline(onListen: (arguments, sink) {}));

      final events = <NiimbotAndroidScanEvent>[];
      final done = Completer<void>();
      final subscription = NiimbotAndroidPrinter().scan().listen((event) {
        events.add(event);
        if (event.isError && !done.isCompleted) done.complete();
      });
      await done.future.timeout(const Duration(seconds: 5));
      await subscription.cancel();

      expect(events, hasLength(1));
      expect(events.single.isError, isTrue);
      expect(events.single.errorCode, 'BLUETOOTH_OFF');
      expect(events.single.errorMessage, contains('蓝牙'));
    });

    test('stopScan calls the native stopScan', () async {
      mockMethods((call) async => null);
      await NiimbotAndroidPrinter().stopScan();
      expect(calls.single.method, 'stopScan');
    });
  });

  group('connect', () {
    test('a successful connect reports connected', () async {
      mockMethods((call) async => <String, Object?>{
            'code': 0,
            'connected': true,
            'message': null,
          });

      final result = await NiimbotAndroidPrinter().connect('AA:BB:CC:DD:EE:FF');
      expect(result.connected, isTrue);
      expect(result.code, 0);
      expect(result.message, isNull);
      expect(calls.single.method, 'connect');
      expect((calls.single.arguments as Map)['address'], 'AA:BB:CC:DD:EE:FF');
    });

    test('each SDK failure code has its own Chinese reason', () async {
      final cases = <int, String>{
        -1: '连接失败',
        -2: '忙',
        -3: '不支持',
      };
      for (final entry in cases.entries) {
        mockMethods((call) async => <String, Object?>{
              'code': entry.key,
              'connected': false,
              'message': '原生说明 ${entry.key}',
            });
        final result =
            await NiimbotAndroidPrinter().connect('AA:BB:CC:DD:EE:FF');
        expect(result.connected, isFalse);
        expect(result.message, contains('${entry.key}'));
      }
    });

    test('a missing permission surfaces the platform message', () async {
      mockMethods((call) async {
        throw PlatformException(code: 'PERMISSION_DENIED', message: '缺少蓝牙连接权限，请允许后重试。');
      });

      final result = await NiimbotAndroidPrinter().connect('AA:BB:CC:DD:EE:FF');
      expect(result.connected, isFalse);
      expect(result.message, contains('权限'));
    });
  });

  group('print', () {
    test('refuses labels without a QR before touching the channel', () async {
      mockMethods((call) async => fail('channel must not be called'));

      final result = await NiimbotAndroidPrinter().print(
        widthMm: 40,
        heightMm: 20,
        contents: <LabelContent>[content(payload: '')],
      );
      expect(result.ok, isFalse);
      expect(result.errorMessage, contains('缺少二维码'));
      expect(calls, isEmpty);
    });

    test('a label too small for a readable QR is refused locally', () async {
      mockMethods((call) async => fail('channel must not be called'));

      final result = await NiimbotAndroidPrinter().print(
        widthMm: 15,
        heightMm: 8,
        contents: <LabelContent>[content()],
      );
      expect(result.ok, isFalse);
      expect(result.errorMessage, contains('放不下'));
      expect(calls, isEmpty);
    });

    test('the 40x20 mm plan is sent exactly as the Windows path computes it',
        () async {
      Map<String, Object?>? sent;
      mockMethods((call) async {
        sent = (call.arguments as Map).cast<String, Object?>();
        return <String, Object?>{
          'ok': true,
          'printed': 1,
          'truncated': false,
        };
      });

      final result = await NiimbotAndroidPrinter().print(
        widthMm: 40,
        heightMm: 20,
        contents: <LabelContent>[content()],
        modelName: 'B1 Pro-1234',
      );

      expect(result.ok, isTrue);
      expect(result.printed, 1);
      final spec = (sent!['spec'] as Map).cast<String, Object?>();
      expect(spec['widthMm'], 40.0);
      expect(spec['heightMm'], 20.0);
      expect(spec['qrX'], closeTo(1.0, 1e-9));
      expect(spec['qrY'], closeTo(1.0, 1e-9));
      expect(spec['qrSize'], closeTo(11, 1e-9));
      expect(spec['printMultiple'], 11.81);
      expect(spec['paperType'], 1, reason: '间隙纸');
      expect(spec['printMode'], 1, reason: '热敏');
      expect(spec['density'], 3);

      final labels = (sent!['labels'] as List).cast<Map>();
      final label = labels.single.cast<String, Object?>();
      expect(label['payload'], 'LABB:TRC-2026-0001');
      final lines = (label['lines'] as List).cast<Map>();
      expect(lines, hasLength(5), reason: 'title + 4 body lines');
      expect(lines.first['text'], 'SN-0001');
      expect(lines.first['bold'], isTrue);
      expect(lines.first['x'], closeTo(13.5, 1e-9));
      expect(lines.first['width'], closeTo(24.5, 1e-9));
      expect((lines.first['fontSize'] as num).toDouble(), greaterThan(2));
    });

    test('the three-line cap is applied and reported as truncated', () async {
      mockMethods((call) async => <String, Object?>{
            'ok': true,
            'printed': 1,
            'truncated': false,
          });

      final result = await NiimbotAndroidPrinter().print(
        widthMm: 40,
        heightMm: 20,
        contents: <LabelContent>[
          content(lines: const <String>['A：1', 'B：2', 'C：3', 'D：4', 'E：5']),
        ],
      );

      expect(result.ok, isTrue);
      expect(result.truncated, isTrue);
      expect(result.summary, contains('省略'));
    });

    test('an SDK error code is translated to Chinese and never says 成功',
        () async {
      mockMethods((call) async => <String, Object?>{
            'ok': false,
            'printed': 0,
            'error': 'PRINT_ERROR',
            'errorCode': 2,
            'errorMessage': '打印机报告错误（代码 2）。',
          });

      final result = await NiimbotAndroidPrinter().print(
        widthMm: 40,
        heightMm: 20,
        contents: <LabelContent>[content()],
      );

      expect(result.ok, isFalse);
      expect(result.errorMessage, contains('缺纸'));
      expect(result.errorMessage, contains('2'));
      expect(result.summary, isNot(contains('已直打')));
    });

    test('a timeout and a lost connection keep their own reasons', () async {
      final cases = <String, String>{
        'TIMEOUT': '超时',
        'NO_CONNECTION': '尚未连接',
        'CANCELLED': '已取消',
      };
      for (final entry in cases.entries) {
        mockMethods((call) async => <String, Object?>{
              'ok': false,
              'printed': 0,
              'error': entry.key,
              'errorMessage': '原生：${entry.key}',
            });
        final result = await NiimbotAndroidPrinter().print(
          widthMm: 40,
          heightMm: 20,
          contents: <LabelContent>[content()],
        );
        expect(result.ok, isFalse);
        expect(result.errorMessage, contains(entry.value));
      }
    });
  });

  group('LabelContent wire shape', () {
    test('parses the server labels array and round-trips toJson', () {
      final parsed = LabelContent.listFromJson(<Object?>[
        <String, dynamic>{
          'kind': 'bag',
          'ref_id': 42,
          'payload': 'LABB:TRC-2026-0001',
          'trace_code': 'TRC-2026-0001',
          'title': 'SN-0001',
          'lines': <String>['追溯码：TRC-2026-0001', '名称：0.1uF'],
        },
      ]);

      expect(parsed, hasLength(1));
      final label = parsed.single;
      expect(label.kind, 'bag');
      expect(label.refId, 42);
      expect(label.payload, 'LABB:TRC-2026-0001');
      expect(label.traceCode, 'TRC-2026-0001');
      expect(label.title, 'SN-0001');
      expect(label.lines, hasLength(2));
      expect(label.hasQr, isTrue);
      expect(label.allLines.first, 'SN-0001');
      expect(label.toJson()['payload'], 'LABB:TRC-2026-0001');
    });

    test('a malformed entry is skipped, not fatal', () {
      final parsed = LabelContent.listFromJson(<Object?>[
        'not-a-map',
        <String, dynamic>{'payload': 'LABB:X'},
      ]);
      expect(parsed, hasLength(1));
      expect(parsed.single.payload, 'LABB:X');
      expect(parsed.single.hasQr, isTrue);
      expect(parsed.single.lines, isEmpty);
    });
  });
}
