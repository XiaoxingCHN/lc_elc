import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';

import '../services/odoo_client.dart';
import 'update_manifest.dart';
import 'update_integrity.dart';
export 'update_integrity.dart';

/// Only use for an absent endpoint; a malformed signed manifest must still fail.
class UpdateEndpointUnavailable implements Exception {
  const UpdateEndpointUnavailable();
}

abstract class UpdateTransport {
  Future<Map<String, dynamic>?> check(
    String platform,
    String arch,
    CancelToken token,
  );
  Future<void> download(
    UpdateManifest release,
    File target,
    CancelToken token,
    void Function(int) onProgress,
  );
}

class ServerUpdateTransport implements UpdateTransport {
  ServerUpdateTransport(this.client, this.server);
  final OdooClient client;
  final String server;

  @override
  Future<Map<String, dynamic>?> check(
    String platform,
    String arch,
    CancelToken token,
  ) async {
    // A separate public probe cannot invalidate the user's login session.
    final dio = Dio(
      BaseOptions(
        baseUrl: server,
        connectTimeout: const Duration(seconds: 5),
        receiveTimeout: const Duration(seconds: 5),
        followRedirects: false,
      ),
    );
    try {
      final response = await dio.get<ResponseBody>(
        '/lab/client/updates/manifest',
        queryParameters: {
          'platform': platform,
          'arch': arch,
          'channel': 'stable',
        },
        options: Options(responseType: ResponseType.stream),
        cancelToken: token,
      );
      if (response.statusCode == 204) return null;
      final bytes = <int>[];
      await for (final chunk in response.data!.stream) {
        if (token.isCancelled) throw token.cancelError!;
        if (bytes.length + chunk.length > 65536)
          throw const FormatException('更新清单过大');
        bytes.addAll(chunk);
      }
      return jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
    } on DioException catch (error) {
      if (error.response?.statusCode == 404) {
        throw const UpdateEndpointUnavailable();
      }
      rethrow;
    } finally {
      dio.close(force: true);
    }
  }

  @override
  Future<void> download(
    UpdateManifest release,
    File target,
    CancelToken token,
    void Function(int) onProgress,
  ) async {
    await client.downloadClientUpdate(
      server: server,
      path: release.assetPath,
      target: target,
      expectedBytes: release.size,
      token: token,
      onProgress: onProgress,
    );
    await verifyUpdateFile(target, release);
  }
}
