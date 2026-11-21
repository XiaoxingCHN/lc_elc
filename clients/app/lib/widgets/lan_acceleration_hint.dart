import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/auth_provider.dart';
import '../providers/lan_acceleration_provider.dart';
import '../screens/lan_acceleration_sheet.dart';
import '../services/lan_probe.dart';
import '../services/wifi_ssid.dart';

/// Low-frequency Wi-Fi / LAN check that drives the LAN hint.
///
/// Reads the SSID on the first signed-in frame and on every foreground resume,
/// but never more often than [interval]. It NEVER switches servers and never
/// signs in: it only offers the settings sheet when the configured Wi-Fi name
/// matches - or, when the platform reports no SSID at all (a wired Ethernet
/// drop, including a desk whose operator named the Wi-Fi), when the configured
/// LAN address actually answers from here.
///
/// The SSID and the probe result stay in memory.
class LanAccelerationHint extends ConsumerStatefulWidget {
  const LanAccelerationHint({
    super.key,
    this.probe = const LanReachabilityProbe(),
  });

  /// Reachability probe used when the platform reports no SSID.
  final LanReachabilityProbe probe;

  /// Minimum time between two SSID reads (the task requires >= 60 s).
  static const Duration interval = Duration(seconds: 60);

  @override
  ConsumerState<LanAccelerationHint> createState() =>
      _LanAccelerationHintState();
}

class _LanAccelerationHintState extends ConsumerState<LanAccelerationHint>
    with WidgetsBindingObserver {
  DateTime? _lastCheck;
  bool _permissionAsked = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) => _maybeCheck());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _maybeCheck();
    } else if (state == AppLifecycleState.detached && mounted) {
      // Application exit: nothing about the LAN path may outlive the process.
      ref.read(lanSettingsProvider.notifier).clear();
    }
  }

  Future<void> _maybeCheck() async {
    if (!mounted) return;
    final auth = ref.read(authProvider);
    if (!auth.isAuthenticated) return;

    final lan = ref.read(lanSettingsProvider);
    // Nothing configured: no reason to touch the platform at all.
    if (lan.lanBaseUrl.isEmpty) return;

    final now = DateTime.now();
    final last = _lastCheck;
    if (last != null && now.difference(last) < LanAccelerationHint.interval) {
      return;
    }
    _lastCheck = now;

    // The operator named no Wi-Fi: a location prompt would buy nothing, and
    // the address itself is the test. Probe only.
    if (lan.ssid.isEmpty) {
      await _probe();
      return;
    }

    String? ssid;
    try {
      ssid = await WifiSsidService.current();
    } on WifiPermissionException {
      if (!_permissionAsked) {
        _permissionAsked = true;
        final granted = await WifiSsidService.requestPermission();
        if (granted) {
          try {
            ssid = await WifiSsidService.current();
          } on WifiPermissionException {
            ssid = null;
          }
        }
      }
    }

    if (!mounted) return;
    ref.read(lanSettingsProvider.notifier).noteDetectedSsid(ssid);

    // A machine plugged into an Ethernet drop reports no SSID even though the
    // operator named the lab Wi-Fi (they may use both on the same desk). Fall
    // back to the address probe rather than going silent on a cable.
    if ((ssid ?? '').trim().isEmpty) {
      await _probe();
    }
  }

  Future<void> _probe() async {
    final lan = ref.read(lanSettingsProvider);
    if (lan.lanBaseUrl.isEmpty) return;
    final reachable = await widget.probe.reachable(lan.lanBaseUrl);
    if (!mounted) return;
    ref.read(lanSettingsProvider.notifier).noteReachability(reachable);
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final lan = ref.watch(lanSettingsProvider);

    if (!auth.isAuthenticated) return const SizedBox.shrink();

    // "Public session" = the current server is not a plain-HTTP intranet one.
    final base = auth.baseUrl ?? '';
    final isPublicSession = !(base.startsWith('http://') &&
        OdooConfig.isPrivateNetworkHost(Uri.tryParse(base)?.host ?? ''));

    if (!lan.shouldOffer(
      currentSsid: lan.lastDetectedSsid,
      isPublicSession: isPublicSession,
    )) {
      return const SizedBox.shrink();
    }

    final scheme = Theme.of(context).colorScheme;
    // Two honest sentences: when a Wi-Fi name is known it is what was matched;
    // otherwise it is the address answering the probe - never claim the other.
    final onWifi = (lan.lastDetectedSsid ?? '').trim().isNotEmpty;
    final label = onWifi
        ? '已连接 ${lan.lastDetectedSsid}，可切换内网加速'
        : '内网服务器可直连，可切换内网加速';
    return Material(
      color: scheme.primaryContainer,
      child: SafeArea(
        top: false,
        bottom: false,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
          child: Row(
            children: [
              Icon(
                onWifi ? Icons.wifi : Icons.lan,
                size: 20,
                color: scheme.onPrimaryContainer,
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  label,
                  style: TextStyle(
                    fontSize: 13,
                    color: scheme.onPrimaryContainer,
                  ),
                ),
              ),
              TextButton(
                onPressed: () {
                  ref.read(lanSettingsProvider.notifier).dismissHint(
                        lan.lastDetectedSsid,
                      );
                },
                child: const Text('忽略'),
              ),
              FilledButton(
                onPressed: () => showLanAcceleration(context),
                child: const Text('切换'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
