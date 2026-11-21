import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../config/odoo_config.dart';

export '../config/odoo_config.dart' show OdooConfig;

/// Pure matching rule for the LAN hint.
///
/// Returns true only when BOTH the operator's configured Wi-Fi name and the
/// SSID the platform reports are non-empty and equal (trimmed, case-sensitive:
/// SSIDs are case-sensitive by definition). Anything unknown matches nothing -
/// the hint must never appear on a guess.
bool ssidMatches(String? configuredSsid, String? currentSsid) {
  final expected = configuredSsid?.trim() ?? '';
  final actual = currentSsid?.trim() ?? '';
  if (expected.isEmpty || actual.isEmpty) return false;
  return expected == actual;
}

/// True when the hint may be shown: the operator configured the LAN feature,
/// the current session is the public one, and the machine looks like it is on
/// that LAN.
///
/// [isPublicSession] must be false when the client is already on the LAN, so
/// the hint never nags someone who is already accelerated.
///
/// **Wired networks have no SSID.** The lab has Ethernet drops, so requiring a
/// Wi-Fi name would silently disable the feature on every desk that is plugged
/// in - including a machine whose operator DID name the Wi-Fi earlier and is
/// today on a cable. Whenever the platform reports no SSID, [lanReachable]
/// decides: a successful TCP/HTTP probe of the configured LAN address is the
/// strongest signal available without a name, and it is what the operator
/// actually cares about ("can I reach the fast address from here?").
///
/// While a real SSID is reported, the name stays authoritative: an address that
/// happens to answer from a café must not look like the lab LAN.
bool shouldOfferLanAcceleration({
  required String? configuredSsid,
  required String? currentSsid,
  required String? configuredLanUrl,
  required bool isPublicSession,
  bool? lanReachable,
}) {
  if (!isPublicSession) return false;
  if ((configuredLanUrl ?? '').trim().isEmpty) return false;
  final actual = currentSsid?.trim() ?? '';
  if (actual.isEmpty) {
    // No Wi-Fi (wired, or the platform cannot report it): the address itself
    // has to answer before the hint may appear.
    return lanReachable == true;
  }
  return ssidMatches(configuredSsid, actual);
}

/// The "服务器与内网加速" settings, kept in MEMORY ONLY.
///
/// Nothing here is written to SharedPreferences: the LAN address and Wi-Fi name
/// exist for this run of the app and disappear on exit, sign-out or a
/// successful switch (see [AuthStateNotifier.logout] / `switchServer`).
class LanAccelerationState {
  const LanAccelerationState({
    this.lanBaseUrl = '',
    this.ssid = '',
    this.lastDetectedSsid,
    this.dismissedForSsid,
    this.dismissedWired = false,
    this.lanReachable,
    this.testing = false,
    this.switching = false,
    this.message,
    this.isError = false,
  });

  /// In-memory LAN address (empty = not configured).
  final String lanBaseUrl;

  /// Wi-Fi name the operator entered (optional).
  final String ssid;

  /// Last SSID the platform reported (diagnostics / hint).
  final String? lastDetectedSsid;

  /// The hint was dismissed for this SSID during this run; do not nag again.
  final String? dismissedForSsid;

  /// The hint was dismissed on a wired desk (no SSID to key the dismissal on)
  /// during this run.
  final bool dismissedWired;

  /// Result of the last reachability probe of [lanBaseUrl], or null when it
  /// has not run yet. Only consulted when no Wi-Fi name is configured (a wired
  /// desk has no SSID to match on).
  final bool? lanReachable;

  final bool testing;
  final bool switching;

  /// Last operator-facing outcome of test/switch (never contains a password).
  final String? message;
  final bool isError;

  LanAccelerationState copyWith({
    String? lanBaseUrl,
    String? ssid,
    Object? lastDetectedSsid = _unset,
    Object? dismissedForSsid = _unset,
    bool? dismissedWired,
    Object? lanReachable = _unset,
    bool? testing,
    bool? switching,
    Object? message = _unset,
    bool? isError,
  }) {
    return LanAccelerationState(
      lanBaseUrl: lanBaseUrl ?? this.lanBaseUrl,
      ssid: ssid ?? this.ssid,
      lastDetectedSsid: identical(lastDetectedSsid, _unset)
          ? this.lastDetectedSsid
          : lastDetectedSsid as String?,
      dismissedForSsid: identical(dismissedForSsid, _unset)
          ? this.dismissedForSsid
          : dismissedForSsid as String?,
      lanReachable: identical(lanReachable, _unset)
          ? this.lanReachable
          : lanReachable as bool?,
      dismissedWired: dismissedWired ?? this.dismissedWired,
      testing: testing ?? this.testing,
      switching: switching ?? this.switching,
      message: identical(message, _unset) ? this.message : message as String?,
      isError: isError ?? this.isError,
    );
  }

  /// True when the hint should be shown for [currentSsid] right now.
  ///
  /// [lanReachable] overrides this state's own probe result; callers normally
  /// omit it. It decides only when the platform reports no SSID (a wired desk,
  /// including one whose operator named the Wi-Fi); see
  /// [shouldOfferLanAcceleration].
  bool shouldOffer({
    required String? currentSsid,
    required bool isPublicSession,
    bool? lanReachable,
  }) {
    final actual = currentSsid?.trim() ?? '';
    if (actual.isEmpty) {
      // A wired desk has no SSID to key the dismissal on; "忽略" there
      // silences the hint for this run.
      if (dismissedWired) return false;
    } else if (ssidMatches(dismissedForSsid, actual)) {
      return false;
    }
    return shouldOfferLanAcceleration(
      configuredSsid: ssid,
      currentSsid: currentSsid,
      configuredLanUrl: lanBaseUrl,
      isPublicSession: isPublicSession,
      lanReachable: lanReachable ?? this.lanReachable,
    );
  }

  static const Object _unset = Object();
}

/// Holds the LAN settings for this process.
///
/// It also mirrors the address into [OdooConfig.setRuntimeLanBaseUrl] so the
/// cleartext whitelist in `OdooClient.configure` accepts exactly the address
/// the operator entered here.
class LanAccelerationNotifier extends StateNotifier<LanAccelerationState> {
  LanAccelerationNotifier() : super(const LanAccelerationState());

  /// Records the address/SSID the operator typed. Memory only.
  ///
  /// Any probe result belongs to the PREVIOUS address, so it is dropped here:
  /// the hint must never offer a switch on the strength of an answer from a
  /// server the operator has just replaced.
  void configure({required String lanBaseUrl, required String ssid}) {
    final normalized = OdooConfig.normalizeBaseUrl(lanBaseUrl);
    OdooConfig.setRuntimeLanBaseUrl(normalized);
    state = state.copyWith(
      lanBaseUrl: normalized,
      ssid: ssid.trim(),
      lanReachable: null,
      message: null,
      isError: false,
    );
  }

  /// Records the SSID read from the platform (or null when unknown).
  void noteDetectedSsid(String? ssid) {
    if (state.lastDetectedSsid == ssid) return;
    state = state.copyWith(lastDetectedSsid: ssid);
  }

  /// Records the result of the reachability probe of the configured address.
  void noteReachability(bool reachable) {
    if (state.lanReachable == reachable) return;
    state = state.copyWith(lanReachable: reachable);
  }

  /// The operator closed the hint for this SSID; do not show it again this run.
  ///
  /// With no SSID (a wired desk) the dismissal is recorded as a single flag
  /// instead, because there is no name to key it on.
  void dismissHint(String? ssid) {
    final name = ssid?.trim() ?? '';
    if (name.isEmpty) {
      state = state.copyWith(dismissedWired: true);
      return;
    }
    state = state.copyWith(dismissedForSsid: name);
  }

  void beginTest() =>
      state = state.copyWith(testing: true, message: null, isError: false);

  void beginSwitch() =>
      state = state.copyWith(switching: true, message: null, isError: false);

  void finish({required String? message, required bool isError}) {
    state = state.copyWith(
      testing: false,
      switching: false,
      message: message,
      isError: isError,
    );
  }

  /// Clears everything held for the LAN path (logout / app exit).
  ///
  /// Also drops the in-memory cleartext whitelist entry.
  void clear() {
    OdooConfig.setRuntimeLanBaseUrl(null);
    state = const LanAccelerationState();
  }

}
