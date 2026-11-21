import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/models/lab_api_exception.dart';
import 'package:lab_inventory_client/models/odoo_exception.dart';
import 'package:lab_inventory_client/services/odoo_client.dart';

/// Atomic server switch and the stale-401 guard, against two local sockets.
///
/// These are the two failure modes the LAN acceleration switch must never
/// have: a failed switch that logs the operator out, and a late 401 from the
/// old server that tears down the new session.
void main() {
  late HttpServer publicServer;
  late HttpServer lanServer;
  late String publicUrl;
  late String lanUrl;
  late bool lanRejects;
  late Duration searchDelay;

  Future<void> serve(HttpServer server, {required bool isLan}) {
    return server.forEach((request) async {
      await utf8.decoder.bind(request).join();
      if (request.uri.path == '/web/session/authenticate') {
        final rejected = isLan && lanRejects;
        if (rejected) {
          request.response.statusCode = 200;
          request.response.headers.contentType = ContentType.json;
          request.response.write(jsonEncode(<String, dynamic>{
            'jsonrpc': '2.0',
            'id': 1,
            'result': <String, dynamic>{'uid': false},
          }));
          await request.response.close();
          return;
        }
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.headers.add(
          HttpHeaders.setCookieHeader,
          'session_id=${isLan ? 'lan-cookie' : 'public-cookie'}; Path=/; HttpOnly',
        );
        request.response.write(jsonEncode(<String, dynamic>{
          'jsonrpc': '2.0',
          'id': 1,
          'result': <String, dynamic>{'uid': isLan ? 9 : 7},
        }));
        await request.response.close();
        return;
      }

      // A business call: answers 401 after a delay, so it lands AFTER the
      // switch to the other server.
      await Future<void>.delayed(searchDelay);
      request.response.statusCode = 401;
      await request.response.close();
    });
  }

  setUp(() async {
    lanRejects = false;
    searchDelay = const Duration(milliseconds: 80);

    publicServer = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    lanServer = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    publicUrl = 'http://127.0.0.1:${publicServer.port}';
    lanUrl = 'http://127.0.0.1:${lanServer.port}';
    serve(publicServer, isLan: false);
    serve(lanServer, isLan: true);
  });

  tearDown(() async {
    await publicServer.close(force: true);
    await lanServer.close(force: true);
  });

  test('a rejected switch keeps the old server, uid and cookie', () async {
    final client = OdooClient(baseUrl: publicUrl, database: 'fixture');
    await client.authenticate('operator', 'pw-public');
    expect(client.baseUrl, publicUrl);
    expect(client.uid, 7);

    lanRejects = true;
    await expectLater(
      client.authenticateAt(
        baseUrl: lanUrl,
        database: 'fixture',
        login: 'operator',
        password: 'pw-wrong',
      ),
      throwsA(isA<OdooAuthException>()),
    );

    expect(client.baseUrl, publicUrl, reason: 'nothing was committed');
    expect(client.database, 'fixture');
    expect(client.uid, 7, reason: 'the old session is still live');
    expect(client.isAuthenticated, isTrue);
  });

  test('a successful switch commits the new server and its cookie', () async {
    final client = OdooClient(baseUrl: publicUrl, database: 'fixture');
    await client.authenticate('operator', 'pw-public');

    final uid = await client.authenticateAt(
      baseUrl: lanUrl,
      database: 'fixture',
      login: 'operator',
      password: 'pw-lan',
    );

    expect(uid, 9);
    expect(client.baseUrl, lanUrl);
    expect(client.uid, 9);
    expect(client.isAuthenticated, isTrue);

    // The new cookie is the LAN one: a 401 is answered by the LAN server.
    await expectLater(
      client.callRoute('/lab/api/catalog/search', const <String, dynamic>{}),
      throwsA(isA<LabSessionExpiredException>()),
    );
  });

  test('a late 401 from the PREVIOUS session does not fire onSessionInvalid',
      () async {
    final client = OdooClient(baseUrl: publicUrl, database: 'fixture');
    await client.authenticate('operator', 'pw-public');

    var notified = 0;
    client.onSessionInvalid = () => notified++;

    // Request issued while on the public server; its 401 arrives in ~80 ms.
    final stale = client.callRoute(
      '/lab/api/catalog/search',
      const <String, dynamic>{},
    );

    // Switch immediately.
    await client.authenticateAt(
      baseUrl: lanUrl,
      database: 'fixture',
      login: 'operator',
      password: 'pw-lan',
    );
    expect(client.baseUrl, lanUrl);

    await expectLater(stale, throwsA(isA<LabSessionExpiredException>()));
    expect(notified, 0,
        reason: 'a 401 from the session that just ended must be ignored');
    expect(client.isAuthenticated, isTrue,
        reason: 'the new LAN session survives');
    expect(client.uid, 9);
  });

  test('probe() leaves the live session untouched even on success', () async {
    final client = OdooClient(baseUrl: publicUrl, database: 'fixture');
    await client.authenticate('operator', 'pw-public');
    final generation = client.sessionGeneration;

    final uid = await client.probe(
      baseUrl: lanUrl,
      database: 'fixture',
      login: 'operator',
      password: 'pw-lan',
    );

    expect(uid, 9);
    expect(client.baseUrl, publicUrl);
    expect(client.uid, 7);
    expect(client.sessionGeneration, generation);
  });
}
