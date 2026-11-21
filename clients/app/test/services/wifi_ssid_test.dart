import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/services/wifi_ssid.dart';

/// MethodChannel contract of `lab/wifi_ssid`.
///
/// The channel is mocked with [TestDefaultBinaryMessenger], so these tests pin
/// the Dart half of the native contract (method names, success/failure codes)
/// without needing an Android or Windows device.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  const channel = MethodChannel('lab/wifi_ssid');
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  void handle(Future<Object?> Function(MethodCall call) handler) {
    messenger.setMockMethodCallHandler(channel, (call) async => handler(call));
  }

  setUp(() {
    // Force the Android branch so the channel contract is exercised on every
    // host (the test host is Windows, where current() would also use it, but
    // requestPermission() would short-circuit).
    WifiSsidService.platformOverride =
        const (android: true, windows: false, linux: false);
  });

  tearDown(() {
    messenger.setMockMethodCallHandler(channel, null);
    WifiSsidService.platformOverride =
        const (android: false, windows: false, linux: false);
  });

  group('currentSsid', () {
    test('returns the SSID reported by the platform', () async {
      handle((call) async {
        expect(call.method, 'currentSsid');
        return 'LabWiFi';
      });

      expect(await WifiSsidService.current(), 'LabWiFi');
    });

    test('trims the value and treats the Android placeholders as unknown',
        () async {
      var value = '  LabWiFi  ';
      handle((_) async => value);
      expect(await WifiSsidService.current(), 'LabWiFi');

      for (final placeholder in <String>['<unknown ssid>', '0x', '   ']) {
        value = placeholder;
        expect(await WifiSsidService.current(), isNull,
            reason: 'placeholder "$placeholder" means unknown');
      }
    });

    test('PERMISSION_DENIED becomes WifiPermissionException', () async {
      handle((_) async {
        throw PlatformException(code: 'PERMISSION_DENIED');
      });

      await expectLater(
        WifiSsidService.current(),
        throwsA(isA<WifiPermissionException>()
            .having((e) => e.code, 'code', 'PERMISSION_DENIED')),
      );
    });

    test('LOCATION_OFF becomes WifiPermissionException', () async {
      handle((_) async {
        throw PlatformException(code: 'LOCATION_OFF');
      });

      await expectLater(
        WifiSsidService.current(),
        throwsA(isA<WifiPermissionException>()
            .having((e) => e.code, 'code', 'LOCATION_OFF')),
      );
    });

    test('an unknown platform error is treated as unknown, not fatal',
        () async {
      handle((_) async {
        throw PlatformException(code: 'SOMETHING_ELSE');
      });
      expect(await WifiSsidService.current(), isNull);
    });

    test('a missing plugin (desktop without the channel) is unknown', () async {
      // No handler installed => MissingPluginException.
      expect(await WifiSsidService.current(), isNull);
    });
  });

  group('requestPermission', () {
    test('returns true when the platform granted it', () async {
      handle((call) async {
        expect(call.method, 'requestPermission');
        return true;
      });
      expect(await WifiSsidService.requestPermission(), isTrue);
    });

    test('returns false when the operator refused', () async {
      handle((_) async => false);
      expect(await WifiSsidService.requestPermission(), isFalse);
    });

    test('returns false on a platform error or a missing plugin', () async {
      handle((_) async {
        throw PlatformException(code: 'DENIED');
      });
      expect(await WifiSsidService.requestPermission(), isFalse);

      messenger.setMockMethodCallHandler(channel, null);
      expect(await WifiSsidService.requestPermission(), isFalse);
    });
  });
}
