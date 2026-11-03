import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/services/odoo_client.dart';
import 'package:lab_inventory_client/updates/update_transport.dart';
import 'package:lab_inventory_client/updates/update_controller.dart';

void main() {
  late HttpServer server;
  late Directory temp;
  late OdooClient client;
  var status = 200, payloadSize = 4, notices = 0, assetCalls = 0;
  String? cookie;
  setUp(() async {
    status = 200;
    payloadSize = 4;
    notices = 0;
    assetCalls = 0;
    cookie = null;
    temp = await Directory.systemTemp.createTemp('update-http-');
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((request) async {
      await request.drain<void>();
      if (request.uri.path == '/web/session/authenticate') {
        request.response.headers.contentType = ContentType.json;
        request.response.headers.add(
          'set-cookie',
          'session_id=fixture; Path=/; HttpOnly',
        );
        request.response.write(
          jsonEncode({
            'jsonrpc': '2.0',
            'id': 1,
            'result': {'uid': 7},
          }),
        );
      } else if (request.uri.path == '/lab/client/updates/manifest') {
        cookie = request.headers.value('cookie');
        request.response.statusCode = status;
        request.response.headers.contentType = ContentType.json;
        if (status == 200)
          request.response.write(jsonEncode({'invalid': true}));
      } else {
        assetCalls++;
        cookie = request.headers.value('cookie');
        request.response.statusCode = status;
        if (status == 302)
          request.response.headers.set(
            'location',
            'https://example.invalid/foreign',
          );
        if (status == 200) {
          request.response.contentLength = payloadSize;
          request.response.add(List.filled(payloadSize, 1));
        }
      }
      await request.response.close();
    });
    client = OdooClient(
      baseUrl: 'http://127.0.0.1:${server.port}',
      database: 'fixture',
    );
    client.onSessionInvalid = () => notices++;
    await client.authenticate('fixture', 'test-only-placeholder');
  });
  tearDown(() async {
    await server.close(force: true);
    await temp.delete(recursive: true);
  });
  Future<void> download({String? serverUrl}) => client.downloadClientUpdate(
    server: serverUrl ?? client.baseUrl,
    path: '/lab/client/updates/assets/release/package.zip',
    target: File('${temp.path}/package'),
    expectedBytes: 4,
    token: CancelToken(),
    onProgress: (_) {},
  );
  test('public manifest 404 differs from unpublished and recovers without logging out', () async {
    final c = UpdateController(
      transport: ServerUpdateTransport(client, client.baseUrl),
      platform: 'android',
      arch: 'universal',
      build: 5,
      directory: () async => temp,
      facts: () async => {},
      unmetered: () async => false,
      authenticated: () => true,
      readSequence: () async => 0,
      saveSequence: (_) async {},
    );
    addTearDown(c.dispose);
    status = 404;
    await c.check();
    expect(c.phase, UpdatePhase.unavailable);
    expect(c.message, contains('更新接口未就绪'));
    expect(cookie, isNull);
    expect(notices, 0);
    status = 204;
    await c.check();
    expect(c.message, '服务器尚未发布更新');
    status = 200;
    await c.check();
    expect(c.phase, UpdatePhase.error); // malformed data never becomes current
    status = 503;
    await c.check();
    expect(c.phase, UpdatePhase.error);
    expect(client.isAuthenticated, isTrue);
    expect(notices, 0);
  });
  for (final response in [200, 401, 302, 403]) {
    test(
      'authenticated artifact response $response preserves boundary',
      () async {
        status = response;
        if (response == 200) {
          await download();
          expect(await File('${temp.path}/package').length(), 4);
        } else {
          await expectLater(download(), throwsA(isA<DioException>()));
        }
        expect(assetCalls, 1);
        expect(cookie, contains('session_id=fixture'));
        expect(notices, [401, 302].contains(response) ? 1 : 0);
        expect(client.hasActiveRequests, isFalse);
      },
    );
  }
  test('different origin is refused before a cookie-bearing request', () async {
    await expectLater(
      download(serverUrl: 'https://example.invalid'),
      throwsStateError,
    );
    expect(assetCalls, 0);
  });
  test('package size mismatch is refused before output is accepted', () async {
    payloadSize = 5;
    await expectLater(download(), throwsFormatException);
    expect(await File('${temp.path}/package').exists(), isFalse);
  });
  test('install gate blocks new authenticated server requests', () async {
    expect(client.beginClientInstall(), isTrue);
    await expectLater(download(), throwsA(isA<DioException>()));
    expect(assetCalls, 0);
    expect(client.hasActiveRequests, isFalse);
    client.endClientInstall();
    await download();
    expect(assetCalls, 1);
  });
}
