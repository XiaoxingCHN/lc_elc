import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../services/lan_acceleration.dart';
import 'auth_provider.dart';

export '../services/lan_acceleration.dart'
    show
        LanAccelerationNotifier,
        LanAccelerationState,
        OdooConfig,
        shouldOfferLanAcceleration,
        ssidMatches;

/// The LAN settings for this process, tied to the auth session.
///
/// Signing out clears the in-memory LAN address and Wi-Fi name: the next
/// operator must not inherit another person's server, and nothing about the
/// LAN path is ever persisted (see `AGENTS.md` / the design task).
final lanSettingsProvider =
    StateNotifierProvider<LanAccelerationNotifier, LanAccelerationState>((ref) {
  final notifier = LanAccelerationNotifier();
  ref.listen<AuthState>(authProvider, (previous, next) {
    if (!next.isAuthenticated) notifier.clear();
  });
  return notifier;
});
