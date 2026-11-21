import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/labels.dart';
import 'package:lab_inventory_client/features/unified/providers/label_providers.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';
import 'package:lab_inventory_client/services/niimbot_android_printer.dart';

import 'support/fake_lab_api.dart';

/// Android Bluetooth printer controller.
///
/// Pinned here: the area is hidden on non-Android hosts, a scan fills the
/// device list, connecting is required before printing, a print asks the server
/// for structured content with `include_content: true` (read-only), and a
/// failure NEVER produces a success notice.
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

  const spec = LabelSpec(
    kind: LabelKind.bag,
    ids: <int>[42],
    copies: 1,
    widthMm: 40,
    heightMm: 20,
    marginMm: 10,
    gapMm: 2,
    fields: <String>['trace_code', 'name'],
  );

  test('non-Android hosts hide the area and never call the channel', () async {
    NiimbotAndroidPrinter.platformOverride =
        const (android: false, windows: false, linux: false);
    final api = FakeLabApi();
    final controller = AndroidPrinterController(
      api: api.client,
      printer: NiimbotAndroidPrinter(),
      supported: false,
    );

    expect(controller.supported, isFalse);
    await controller.refresh();
    expect(controller.state.available, isFalse);
    expect(controller.state.error, isNull, reason: 'hidden, not an error');
    expect(calls, isEmpty);
  });

  test('refresh surfaces the native availability', () async {
    mockMethods((call) async => <String, Object?>{'available': true});
    final controller = AndroidPrinterController(
      api: FakeLabApi().client,
      printer: NiimbotAndroidPrinter(),
    );

    await controller.refresh();
    expect(controller.state.available, isTrue);
    expect(controller.state.unavailableReason, isNull);
    expect(controller.state.canScan, isTrue);
  });

  test('a refused permission is a specific error, not a silent no-op', () async {
    mockMethods((call) async => call.method == 'available'
        ? <String, Object?>{'available': true}
        : false);
    final controller = AndroidPrinterController(
      api: FakeLabApi().client,
      printer: NiimbotAndroidPrinter(),
    );
    await controller.refresh();

    expect(await controller.requestPermission(), isFalse);
    expect(controller.state.error, contains('蓝牙权限'));
    expect(controller.state.scanning, isFalse);
  });

  test('a scan fills the device list and stops on finished', () async {
    mockMethods((call) async => call.method == 'available'
        ? <String, Object?>{'available': true}
        : (call.method == 'requestPermissions' ? true : null));
    messenger.setMockStreamHandler(
      eventChannel,
      MockStreamHandler.inline(
        onListen: (arguments, sink) {
          sink.success(<String, Object?>{
            'type': 'device',
            'name': 'B1 Pro-1234',
            'address': 'AA:BB:CC:DD:EE:FF',
          });
          sink.success(<String, Object?>{'type': 'finished'});
        },
      ),
    );

    final controller = AndroidPrinterController(
      api: FakeLabApi().client,
      printer: NiimbotAndroidPrinter(),
    );
    await controller.refresh();
    await controller.startScan();

    // Give the mock stream a chance to deliver.
    for (var i = 0; i < 20 && controller.state.scanning; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 10));
    }

    expect(controller.state.devices, hasLength(1));
    expect(controller.state.devices.single.name, 'B1 Pro-1234');
    expect(controller.state.scanning, isFalse);
    await controller.stopScan();
  });

  test('printing without a connection is refused before the server call',
      () async {
    mockMethods((call) async => <String, Object?>{'available': true});
    final api = FakeLabApi();
    final controller = AndroidPrinterController(
      api: api.client,
      printer: NiimbotAndroidPrinter(),
    );
    await controller.refresh();

    final result = await controller.printSpec(spec);

    expect(result.ok, isFalse);
    expect(result.errorMessage, contains('尚未连接'));
    expect(api.calls, isEmpty, reason: 'no preview request without a printer');
    expect(controller.state.notice, isNull);
  });

  test('a successful connect is required before printing', () async {
    mockMethods((call) async {
      switch (call.method) {
        case 'available':
          return <String, Object?>{'available': true};
        case 'connect':
          return <String, Object?>{'code': 0, 'connected': true};
        default:
          return null;
      }
    });
    final controller = AndroidPrinterController(
      api: FakeLabApi().client,
      printer: NiimbotAndroidPrinter(),
    );
    await controller.refresh();

    final connected = await controller.connect(
      const NiimbotAndroidDevice(name: 'B1 Pro-1234', address: 'AA:BB'),
    );
    expect(connected, isTrue);
    expect(controller.state.connected, isNotNull);
    expect(controller.state.canPrint, isTrue);
  });

  test('a print asks for include_content and reports real success only', () async {
    mockMethods((call) async {
      switch (call.method) {
        case 'available':
          return <String, Object?>{'available': true};
        case 'connect':
          return <String, Object?>{'code': 0, 'connected': true};
        case 'print':
          return <String, Object?>{'ok': true, 'printed': 1, 'truncated': false};
        default:
          return null;
      }
    });
    final api = FakeLabApi();
    api.answerWith(<String, Map<String, dynamic>>{
      LabApiRoutes.labelsPreview: <String, dynamic>{
        'pdf_base64': base64Encode(<int>[0x25, 0x50, 0x44, 0x46]),
        'filename': 'labels.pdf',
        'labels': <Map<String, dynamic>>[
          <String, dynamic>{
            'kind': 'bag',
            'ref_id': 42,
            'payload': 'LABB:TRC-2026-0001',
            'trace_code': 'TRC-2026-0001',
            'title': 'SN-0001',
            'lines': <String>['名称：A'],
          },
        ],
      },
    });

    final controller = AndroidPrinterController(
      api: api.client,
      printer: NiimbotAndroidPrinter(),
    );
    await controller.refresh();
    await controller.connect(
      const NiimbotAndroidDevice(name: 'B1 Pro-1234', address: 'AA:BB'),
    );

    final result = await controller.printSpec(spec);

    expect(result.ok, isTrue);
    expect(result.printed, 1);
    expect(api.onlyParams(LabApiRoutes.labelsPreview)['include_content'], isTrue);
    expect(api.countFor(LabApiRoutes.inventoryReceipt), 0);
    expect(api.countFor(LabApiRoutes.inventoryIssue), 0);
    expect(controller.state.notice, contains('重新打印不会改变库存'));
    expect(controller.state.error, isNull);
  });

  test('a printer error keeps the failure and sets no success notice', () async {
    mockMethods((call) async {
      switch (call.method) {
        case 'available':
          return <String, Object?>{'available': true};
        case 'connect':
          return <String, Object?>{'code': 0, 'connected': true};
        case 'print':
          return <String, Object?>{
            'ok': false,
            'printed': 0,
            'error': 'PRINT_ERROR',
            'errorCode': 2,
          };
        default:
          return null;
      }
    });
    final api = FakeLabApi();
    api.answerWith(<String, Map<String, dynamic>>{
      LabApiRoutes.labelsPreview: <String, dynamic>{
        'pdf_base64': '',
        'labels': <Map<String, dynamic>>[
          <String, dynamic>{
            'kind': 'bag',
            'payload': 'LABB:TRC-2026-0001',
            'title': 'SN-0001',
            'lines': <String>['名称：A'],
          },
        ],
      },
    });

    final controller = AndroidPrinterController(
      api: api.client,
      printer: NiimbotAndroidPrinter(),
    );
    await controller.refresh();
    await controller.connect(
      const NiimbotAndroidDevice(name: 'B1 Pro-1234', address: 'AA:BB'),
    );

    final result = await controller.printSpec(spec);

    expect(result.ok, isFalse);
    expect(result.errorMessage, contains('缺纸'));
    expect(controller.state.notice, isNull);
    expect(controller.state.error, contains('缺纸'));
  });

  test('the server omitting structured content is a failure, not a print',
      () async {
    mockMethods((call) async {
      switch (call.method) {
        case 'available':
          return <String, Object?>{'available': true};
        case 'connect':
          return <String, Object?>{'code': 0, 'connected': true};
        default:
          return null;
      }
    });
    final api = FakeLabApi();
    api.answerWith(<String, Map<String, dynamic>>{
      LabApiRoutes.labelsPreview: <String, dynamic>{
        'pdf_base64': base64Encode(<int>[0x25, 0x50, 0x44, 0x46]),
      },
    });

    final controller = AndroidPrinterController(
      api: api.client,
      printer: NiimbotAndroidPrinter(),
    );
    await controller.refresh();
    await controller.connect(
      const NiimbotAndroidDevice(name: 'B1 Pro-1234', address: 'AA:BB'),
    );

    final result = await controller.printSpec(spec);

    expect(result.ok, isFalse);
    expect(result.errorMessage, contains('直打内容'));
    expect(calls.where((call) => call.method == 'print'), isEmpty);
    expect(controller.state.notice, isNull);
  });
}
