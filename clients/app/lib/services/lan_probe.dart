import 'dart:io';

import 'package:flutter/foundation.dart';

import '../config/odoo_config.dart';

/// Credential-free reachability check for the in-memory LAN address.
///
/// **Why this exists.** The LAN hint used to be driven only by the Wi-Fi SSID.
/// A desk that is plugged into an Ethernet drop has no SSID at all, so the
/// feature silently never fired on exactly the machines that are permanently on
/// the lab LAN. When the operator configures no Wi-Fi name, this probe answers
/// the question they actually care about: "does the fast address answer from
/// here?"
///
/// It deliberately sends no credentials and reads no business data - a single
/// GET of Odoo's public `/web/health` endpoint, which every supported
/// deployment serves without a session. Anything below HTTP 500 counts as
/// reachable: a 404 or a redirect still proves a server is listening, and the
/// real switch re-authenticates anyway.
class LanReachabilityProbe {
  const LanReachabilityProbe();

  /// Hard ceiling for connect + response. The hint runs in the background and
  /// must never delay anything, so a slow or absent LAN gives up quickly.
  static const Duration timeout = Duration(seconds: 3);

  /// True when [baseUrl]'s host answers an HTTP request right now.
  ///
  /// Only a private-network address is probed: a public host in this field
  /// would be a misconfiguration, and `setRuntimeLanBaseUrl` already refuses to
  /// whitelist one.
  Future<bool> reachable(String baseUrl) async {
    final normalized = OdooConfig.normalizeBaseUrl(baseUrl);
    if (normalized.isEmpty) return false;

    final parsed = Uri.tryParse(normalized);
    if (parsed == null || !OdooConfig.isPrivateNetworkHost(parsed.host)) {
      return false;
    }

    final healthUri = parsed.replace(path: '/web/health', query: null);
    final client = HttpClient()..connectionTimeout = timeout;
    try {
      final request = await client.getUrl(healthUri).timeout(timeout);
      request.headers.set(HttpHeaders.acceptHeader, '*/*');
      final response = await request.close().timeout(timeout);
      await response.drain<void>().timeout(timeout);
      return response.statusCode < 500;
    } catch (error) {
      // A refused connection, a timeout, an unresolvable name and a TLS
      // failure all mean the same thing to the caller: not usable from here.
      if (kDebugMode) debugPrint('LAN probe failed: ${error.runtimeType}');
      return false;
    } finally {
      client.close(force: true);
    }
  }
}
