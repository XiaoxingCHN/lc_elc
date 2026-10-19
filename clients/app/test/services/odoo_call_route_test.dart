import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/models/lab_api_exception.dart';
import 'package:lab_inventory_client/services/odoo_client.dart';

/// [OdooClient.callRoute] against a real socket.
///
/// A tiny HTTP server on 127.0.0.1 stands in for Odoo, so this exercises the
/// actual Dio stack, the actual cookie jar and the actual interceptor - the
/// three places where "did the business call really reuse the login session?"
/// can go wrong. No real server and no real credential is involved.
class _Captured {
  _Captured(this.path, this.body, this.cookie);

  final String path;
  final String body;
  final String? cookie;
}

void main() {
  late HttpServer server;
  late String baseUrl;
  final captured = <_Captured>[];

  /// Per-test behaviour for everything that is not `/web/session/authenticate`.
  late Future<void> Function(HttpRequest request) routeHandler;

  Future<void> sendJson(
    HttpRequest request,
    Map<String, dynamic> body, {
    int status = 200,
    String? setCookie,
  }) async {
    request.response.statusCode = status;
    request.response.headers.contentType = ContentType.json;
    if (setCookie != null) {
      request.response.headers.add(HttpHeaders.setCookieHeader, setCookie);
    }
    request.response.write(jsonEncode(body));
    await request.response.close();
  }

  Future<void> sendSuccessEnvelope(
    HttpRequest request,
    Map<String, dynamic> data,
  ) {
    return sendJson(request, <String, dynamic>{
      'jsonrpc': '2.0',
      'id': 'srv-1',
      'result': <String, dynamic>{'ok': true, 'data': data, 'error': null},
    });
  }

  Future<void> authenticateOk(HttpRequest request) {
    return sendJson(
      request,
      <String, dynamic>{
        'jsonrpc': '2.0',
        'id': 'srv-0',
        'result': <String, dynamic>{'uid': 7},
      },
      setCookie: 'session_id=abc123; Path=/; HttpOnly',
    );
  }

  setUp(() async {
    captured.clear();
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    baseUrl = 'http://127.0.0.1:${server.port}';
    routeHandler = (request) => sendSuccessEnvelope(request, <String, dynamic>{});

    server.listen((request) async {
      final body = await utf8.decoder.bind(request).join();
      captured.add(_Captured(
        request.uri.path,
        body,
        request.headers.value(HttpHeaders.cookieHeader),
      ));

      if (request.uri.path == '/web/session/authenticate') {
        await authenticateOk(request);
        return;
      }
      await routeHandler(request);
    });
  });

  tearDown(() async {
    await server.close(force: true);
  });

  Future<OdooClient> signedInClient() async {
    final client = OdooClient(baseUrl: baseUrl, database: 'LcHardwareHouse');
    await client.authenticate('lab_operator', 'pw-A-secret');
    return client;
  }

  group('happy path', () {
    test('unwraps {ok,data} and reuses the session cookie from authenticate',
        () async {
      routeHandler = (request) => sendSuccessEnvelope(request, <String, dynamic>{
            'items': <dynamic>[],
            'total': 0,
            'next_cursor': null,
            'inventory_revision': 'rev-1',
          });

      final client = await signedInClient();
      final data = await client.callRoute(
        '/lab/api/catalog/search',
        <String, dynamic>{'query': '', 'limit': 50},
      );

      expect(data['total'], 0);
      expect(data['items'], isEmpty);
      expect(data['inventory_revision'], 'rev-1');

      final call = captured.last;
      expect(call.path, '/lab/api/catalog/search');
      // The SAME jar as authenticate: no second cookie jar, no anonymous call.
      expect(call.cookie, contains('session_id=abc123'));

      final sent = jsonDecode(call.body) as Map<String, dynamic>;
      expect(sent['jsonrpc'], '2.0');
      expect(sent['method'], 'call');
      expect(sent['id'], isA<String>());
      expect(sent['params'], <String, dynamic>{'query': '', 'limit': 50});
    });

    test('an ok envelope without data yields an empty map, not a failure',
        () async {
      routeHandler = (request) => sendJson(request, <String, dynamic>{
            'jsonrpc': '2.0',
            'id': 'srv-2',
            'result': <String, dynamic>{'ok': true, 'data': null, 'error': null},
          });

      final client = await signedInClient();
      expect(await client.callRoute('/lab/api/inventory/bootstrap', const {}),
          isEmpty);
    });
  });

  group('business failures are never returned as data', () {
    test('ok=false throws the server code and its Chinese message', () async {
      routeHandler = (request) => sendJson(request, <String, dynamic>{
            'jsonrpc': '2.0',
            'id': 'srv-3',
            'result': <String, dynamic>{
              'ok': false,
              'data': null,
              'error': <String, dynamic>{
                'code': 'VALIDATION_ERROR',
                'message': '数量必须是正数。',
                'fields': <String, dynamic>{'quantity': '必须大于 0'},
              },
            },
          });

      final client = await signedInClient();

      await expectLater(
        client.callRoute('/lab/api/inventory/issue', <String, dynamic>{
          'request_key': 'uuid-1',
          'lines': <dynamic>[],
        }),
        throwsA(
          isA<LabApiException>()
              .having((e) => e.code, 'code', 'VALIDATION_ERROR')
              .having((e) => e.message, 'message', '数量必须是正数。')
              .having((e) => e.fields['quantity'], 'fields.quantity', '必须大于 0')
              .having((e) => e.isSessionExpired, 'isSessionExpired', isFalse),
        ),
      );
    });

    test('ok=false with data present still throws', () async {
      routeHandler = (request) => sendJson(request, <String, dynamic>{
            'jsonrpc': '2.0',
            'id': 'srv-4',
            'result': <String, dynamic>{
              'ok': false,
              // A server bug: data alongside a failure must not be trusted.
              'data': <String, dynamic>{'lab_quantity': 999},
              'error': <String, dynamic>{
                'code': 'CONFLICT',
                'message': '库存已被其他人更新，请刷新后重试。',
              },
            },
          });

      final client = await signedInClient();

      await expectLater(
        client.callRoute('/lab/api/inventory/receipt', const {}),
        throwsA(isA<LabApiException>()
            .having((e) => e.code, 'code', 'CONFLICT')),
      );
    });

    test('a JSON-RPC error (no result) is a failure, not success', () async {
      routeHandler = (request) => sendJson(request, <String, dynamic>{
            'jsonrpc': '2.0',
            'id': 'srv-5',
            'error': <String, dynamic>{
              'code': 200,
              'message': 'Odoo Server Error',
              'data': <String, dynamic>{
                'name': 'odoo.exceptions.AccessError',
                'message': '无权访问该记录。',
              },
            },
          });

      final client = await signedInClient();

      await expectLater(
        client.callRoute('/lab/api/catalog/bind', const {}),
        throwsA(isA<LabApiException>()
            .having((e) => e.message, 'message', contains('无权访问'))
            .having((e) => e.isSessionExpired, 'isSessionExpired', isFalse)),
      );
    });

    test('an unparseable body is a failure', () async {
      routeHandler = (request) async {
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write('"just a string"');
        await request.response.close();
      };

      final client = await signedInClient();
      await expectLater(
        client.callRoute('/lab/api/catalog/categories', const {}),
        throwsA(isA<LabApiException>()),
      );
    });
  });

  group('dead session', () {
    test('HTTP 401 goes back to login, keeps the credential and does not loop',
        () async {
      routeHandler = (request) async {
        request.response.statusCode = 401;
        await request.response.close();
      };

      final client = await signedInClient();
      var notified = 0;
      client.onSessionInvalid = () => notified++;

      await expectLater(
        client.callRoute('/lab/api/catalog/search', const {}),
        throwsA(isA<LabSessionExpiredException>()),
      );

      expect(notified, 1);
      expect(client.isAuthenticated, isFalse);

      // Already signed out: the next call fails locally, with no request at
      // all - no retry, no loop.
      final requestsBefore = captured.length;
      await expectLater(
        client.callRoute('/lab/api/catalog/search', const {}),
        throwsA(isA<LabSessionExpiredException>()),
      );
      expect(captured.length, requestsBefore);
      expect(notified, 2);
    });

    test('Odoo session-expired JSON-RPC code 100 is treated as a dead session',
        () async {
      routeHandler = (request) => sendJson(request, <String, dynamic>{
            'jsonrpc': '2.0',
            'id': 'srv-6',
            'error': <String, dynamic>{
              'code': 100,
              'message': 'Odoo Session Expired',
              'data': <String, dynamic>{
                'name': 'odoo.http.SessionExpiredException',
                'message': 'Session expired',
              },
            },
          });

      final client = await signedInClient();
      var notified = 0;
      client.onSessionInvalid = () => notified++;

      await expectLater(
        client.callRoute('/lab/api/catalog/search', const {}),
        throwsA(isA<LabSessionExpiredException>()),
      );
      expect(notified, 1);
    });

    test('a business call without a session never leaves the client', () async {
      final client = OdooClient(baseUrl: baseUrl, database: 'LcHardwareHouse');
      var notified = 0;
      client.onSessionInvalid = () => notified++;

      await expectLater(
        client.callRoute('/lab/api/inventory/receipt', const {}),
        throwsA(isA<LabSessionExpiredException>()),
      );

      expect(captured.where((c) => c.path.startsWith('/lab/api')), isEmpty);
      expect(notified, 1);
    });
  });
}
