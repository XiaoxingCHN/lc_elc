import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/models/odoo_exception.dart';
// Also re-exports OdooConfig (the cleartext policy lives there).
import 'package:lab_inventory_client/services/lan_acceleration.dart';
import 'package:lab_inventory_client/services/lan_probe.dart';

/// The LAN hint and the cleartext whitelist are both pure policy: pin them
/// without any platform channel, socket or preference store.
void main() {
  group('ssidMatches', () {
    test('matches only non-empty, equal names (trimmed)', () {
      expect(ssidMatches('LabWiFi', 'LabWiFi'), isTrue);
      expect(ssidMatches('  LabWiFi  ', 'LabWiFi'), isTrue);
      expect(ssidMatches('LabWiFi', 'LabWifi'), isFalse,
          reason: 'SSIDs are case-sensitive');
      expect(ssidMatches('LabWiFi', 'Other'), isFalse);
    });

    test('unknown values never match', () {
      expect(ssidMatches(null, 'LabWiFi'), isFalse);
      expect(ssidMatches('LabWiFi', null), isFalse);
      expect(ssidMatches('', ''), isFalse);
      expect(ssidMatches('   ', 'LabWiFi'), isFalse);
      expect(ssidMatches('LabWiFi', '   '), isFalse);
    });
  });

  group('shouldOfferLanAcceleration', () {
    test('offers only for a configured LAN url, a matching SSID and a public '
        'session', () {
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: 'LabWiFi',
          currentSsid: 'LabWiFi',
          configuredLanUrl: 'http://192.168.31.105:8069',
          isPublicSession: true,
        ),
        isTrue,
      );
    });

    test('never offers without a configured LAN address', () {
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: 'LabWiFi',
          currentSsid: 'LabWiFi',
          configuredLanUrl: '   ',
          isPublicSession: true,
        ),
        isFalse,
      );
    });

    test('never offers while already on the LAN or when the SSID differs', () {
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: 'LabWiFi',
          currentSsid: 'LabWiFi',
          configuredLanUrl: 'http://192.168.31.105:8069',
          isPublicSession: false,
        ),
        isFalse,
      );
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: 'LabWiFi',
          currentSsid: 'Cafe',
          configuredLanUrl: 'http://192.168.31.105:8069',
          isPublicSession: true,
        ),
        isFalse,
      );
    });
  });

  group('wired desks (no SSID reported)', () {
    test('offers only when the LAN address actually answers', () {
      // The lab has Ethernet drops: requiring a Wi-Fi name would silently
      // disable the feature on every desk that is plugged in.
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: '',
          currentSsid: null,
          configuredLanUrl: 'http://192.168.31.105:8069',
          isPublicSession: true,
          lanReachable: true,
        ),
        isTrue,
      );
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: '',
          currentSsid: null,
          configuredLanUrl: 'http://192.168.31.105:8069',
          isPublicSession: true,
          lanReachable: false,
        ),
        isFalse,
      );
      // Not probed yet: never offer on a guess.
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: '',
          currentSsid: null,
          configuredLanUrl: 'http://192.168.31.105:8069',
          isPublicSession: true,
        ),
        isFalse,
      );
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: null,
          currentSsid: null,
          configuredLanUrl: 'http://192.168.31.105:8069',
          isPublicSession: true,
          lanReachable: true,
        ),
        isTrue,
      );
    });

    test('still refuses without a LAN address or on the LAN session', () {
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: '',
          currentSsid: null,
          configuredLanUrl: '',
          isPublicSession: true,
          lanReachable: true,
        ),
        isFalse,
      );
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: '',
          currentSsid: null,
          configuredLanUrl: 'http://192.168.31.105:8069',
          isPublicSession: false,
          lanReachable: true,
        ),
        isFalse,
      );
    });

    test('a reported SSID stays authoritative over reachability', () {
      // When the platform DOES report a network, the name decides: an address
      // that happens to answer from a café must not look like the lab LAN.
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: 'LabWiFi',
          currentSsid: 'Cafe',
          configuredLanUrl: 'http://192.168.31.105:8069',
          isPublicSession: true,
          lanReachable: true,
        ),
        isFalse,
      );
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: 'LabWiFi',
          currentSsid: 'LabWiFi',
          configuredLanUrl: 'http://192.168.31.105:8069',
          isPublicSession: true,
          lanReachable: false,
        ),
        isTrue,
        reason: 'a reachable name is enough even if the probe has not run',
      );
    });

    test('a named Wi-Fi on a cable still falls back to the probe', () {
      // The same desk may be plugged in today. With no SSID reported, the
      // configured name cannot match anything, so the address must answer.
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: 'LabWiFi',
          currentSsid: null,
          configuredLanUrl: 'http://192.168.31.105:8069',
          isPublicSession: true,
          lanReachable: true,
        ),
        isTrue,
      );
      expect(
        shouldOfferLanAcceleration(
          configuredSsid: 'LabWiFi',
          currentSsid: '',
          configuredLanUrl: 'http://192.168.31.105:8069',
          isPublicSession: true,
        ),
        isFalse,
        reason: 'never offer on a guess before the probe answers',
      );
    });

    test('the state carries the probe result and honours its dismissal', () {
      const state = LanAccelerationState(
        lanBaseUrl: 'http://192.168.31.105:8069',
      );
      expect(state.shouldOffer(currentSsid: null, isPublicSession: true),
          isFalse,
          reason: 'no probe yet');
      expect(
        state
            .copyWith(lanReachable: true)
            .shouldOffer(currentSsid: null, isPublicSession: true),
        isTrue,
      );
      expect(
        state
            .copyWith(lanReachable: true, dismissedWired: true)
            .shouldOffer(currentSsid: null, isPublicSession: true),
        isFalse,
      );
      // A named Wi-Fi that IS reported dismisses by name, not by the wired flag.
      const named = LanAccelerationState(
        lanBaseUrl: 'http://192.168.31.105:8069',
        ssid: 'LabWiFi',
        dismissedWired: true,
      );
      expect(
        named.shouldOffer(currentSsid: 'LabWiFi', isPublicSession: true),
        isTrue,
      );
      // An explicit argument still wins over the stored value.
      expect(
        state
            .copyWith(lanReachable: true)
            .shouldOffer(
              currentSsid: null,
              isPublicSession: true,
              lanReachable: false,
            ),
        isFalse,
      );
    });

    test('dismissHint with no SSID sets the wired flag, not a name', () {
      final notifier = LanAccelerationNotifier()
        ..configure(
          lanBaseUrl: 'http://192.168.31.105:8069',
          ssid: 'LabWiFi',
        );
      notifier.dismissHint(null);
      expect(notifier.state.dismissedWired, isTrue);
      expect(notifier.state.dismissedForSsid, isNull);
      notifier.dispose();

      final wired = LanAccelerationNotifier()
        ..configure(lanBaseUrl: 'http://192.168.31.105:8069', ssid: '');
      wired.dismissHint('  ');
      expect(wired.state.dismissedWired, isTrue);
      wired.dispose();
    });

    test('configure drops a stale probe result', () {
      final notifier = LanAccelerationNotifier()
        ..configure(lanBaseUrl: 'http://192.168.31.105:8069', ssid: '');
      notifier.noteReachability(true);
      expect(notifier.state.lanReachable, isTrue);
      // A new address invalidates the old answer.
      notifier.configure(lanBaseUrl: 'http://192.168.1.20:8069', ssid: '');
      expect(notifier.state.lanReachable, isNull);
      notifier.dispose();
    });
  });

  group('LanAccelerationState.shouldOffer honours dismissal', () {
    test('a dismissed SSID is not offered again', () {
      const state = LanAccelerationState(
        lanBaseUrl: 'http://192.168.31.105:8069',
        ssid: 'LabWiFi',
        lastDetectedSsid: 'LabWiFi',
      );
      expect(
        state.shouldOffer(currentSsid: 'LabWiFi', isPublicSession: true),
        isTrue,
      );
      expect(
        state
            .copyWith(dismissedForSsid: 'LabWiFi')
            .shouldOffer(currentSsid: 'LabWiFi', isPublicSession: true),
        isFalse,
      );
      // A different SSID can be offered again.
      expect(
        state
            .copyWith(dismissedForSsid: 'Other')
            .shouldOffer(currentSsid: 'LabWiFi', isPublicSession: true),
        isTrue,
      );
    });
  });

  group('LanReachabilityProbe refuses what it must not probe', () {
    // These paths return before any socket is opened, so the test stays
    // offline: a public host in the LAN field is a misconfiguration, not a
    // target to contact.
    test('public hosts and empty input are not probed', () async {
      const probe = LanReachabilityProbe();
      expect(await probe.reachable(''), isFalse);
      expect(await probe.reachable('https://team.l-creation.club'), isFalse);
      expect(await probe.reachable('http://8.8.8.8:8069'), isFalse);
    });
  });

  group('cleartext (HTTP) policy', () {
    tearDown(() => OdooConfig.setRuntimeLanBaseUrl(null));

    test('HTTPS is always allowed', () {
      expect(OdooConfig.isPermittedBaseUrl('https://team.l-creation.club'),
          isTrue);
      expect(OdooConfig.isPermittedBaseUrl('https://example.com:8443'), isTrue);
    });

    test('the legacy lab host and loopback are allowed over HTTP', () {
      expect(OdooConfig.isPermittedBaseUrl('http://192.168.31.105:8069'),
          isTrue);
      expect(OdooConfig.isPermittedBaseUrl('http://127.0.0.1:8069'), isTrue);
    });

    test('a private HTTP host entered in settings becomes allowed', () {
      expect(OdooConfig.isPermittedBaseUrl('http://192.168.1.20:8069'), isFalse);
      OdooConfig.setRuntimeLanBaseUrl('http://192.168.1.20:8069');
      expect(OdooConfig.isPermittedBaseUrl('http://192.168.1.20:8069'), isTrue);
      // A different private address is still refused.
      expect(OdooConfig.isPermittedBaseUrl('http://192.168.1.21:8069'), isFalse);
    });

    test('a public host over HTTP is always refused', () {
      OdooConfig.setRuntimeLanBaseUrl('http://team.l-creation.club');
      expect(OdooConfig.runtimeLanBaseUrl, isNull,
          reason: 'a public host may never widen the whitelist');
      expect(OdooConfig.isPermittedBaseUrl('http://team.l-creation.club'),
          isFalse);
      expect(OdooConfig.isPermittedBaseUrl('http://8.8.8.8:8069'), isFalse);
    });

    test('a public hostname with a private-looking name is still refused', () {
      expect(OdooConfig.isPermittedBaseUrl('http://lab.local:8069'), isFalse,
          reason: 'only the configured intranet hosts are whitelisted');
    });

    test('ensureCleartextAllowed explains the refusal', () {
      expect(
        () => OdooConfig.ensureCleartextAllowed('http://example.com:8069'),
        throwsA(isA<OdooValidationException>()),
      );
      expect(
        () => OdooConfig.ensureCleartextAllowed('https://example.com'),
        returnsNormally,
      );
    });

    test('private-network detection covers the RFC1918 ranges', () {
      for (final host in <String>[
        '10.0.0.1',
        '172.16.0.1',
        '172.31.255.254',
        '192.168.0.1',
        '127.0.0.1',
        'localhost',
        'lab.local',
      ]) {
        expect(OdooConfig.isPrivateNetworkHost(host), isTrue, reason: host);
      }
      for (final host in <String>[
        '172.32.0.1',
        '8.8.8.8',
        'team.l-creation.club',
        '',
        'not-an-ip',
      ]) {
        expect(OdooConfig.isPrivateNetworkHost(host), isFalse, reason: host);
      }
    });

    test('the fallback server is the public HTTPS deployment', () {
      expect(OdooConfig.publicBaseUrl, 'https://team.l-creation.club');
      expect(OdooConfig.publicDatabase, 'LcHardwareHouse');
      // A test/build may define LAB_ODOO_URL; whatever it is, it must be a
      // permitted address (an empty define falls back to the public server).
      expect(OdooConfig.isPermittedBaseUrl(OdooConfig.fallbackBaseUrl), isTrue);
    });
  });
}
