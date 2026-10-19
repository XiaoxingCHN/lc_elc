import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/providers/unified_providers.dart';
import 'package:lab_inventory_client/features/unified/services/scan_sources.dart';
import 'package:lab_inventory_client/features/unified/widgets/scan_input.dart';

/// The ONE code-entry widget used by every stock flow.
///
/// Root/user requirement: Windows and Linux MUST have the same business through a
/// keyboard-wedge scanner or a paste, and must NOT render a control that only
/// exists to report "not supported"; Android additionally gets the camera.
void main() {
  Widget host(Widget child, ScannerCapabilities capabilities) {
    return ProviderScope(
      overrides: <Override>[
        scannerCapabilitiesProvider.overrideWithValue(capabilities),
      ],
      // The tests run with `--no-test-assets` (Flutter's shader bundle cannot be
      // compiled under a CJK checkout path), so the default Android ink-sparkle
      // shader is unavailable. The ripple splash needs no shader and is what the
      // desktop build uses anyway.
      child: MaterialApp(
        theme: ThemeData(splashFactory: InkRipple.splashFactory),
        home: Scaffold(body: child),
      ),
    );
  }

  const desktop = ScannerCapabilities(
    camera: false,
    keyboardWedge: true,
    clipboard: true,
  );
  const phone = ScannerCapabilities(
    camera: true,
    keyboardWedge: true,
    clipboard: true,
  );

  testWidgets('a scanner gun (keyboard + Enter) submits the cleaned payload',
      (tester) async {
    final captured = <String>[];
    await tester.pumpWidget(
      host(ScanInputField(onSubmit: captured.add), desktop),
    );

    // A hardware scanner types the code and appends CR/LF.
    await tester.enterText(find.byType(TextField), 'LABB:TRACE-1\n');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pump();

    expect(captured, <String>['LABB:TRACE-1']);
  });

  testWidgets('desktop shows no camera control, only the paste path',
      (tester) async {
    await tester.pumpWidget(
      host(ScanInputField(onSubmit: (_) {}), desktop),
    );

    expect(find.byIcon(Icons.photo_camera_outlined), findsNothing,
        reason: 'Windows/Linux have no camera implementation, so no control');
    expect(find.byIcon(Icons.content_paste), findsOneWidget);
    expect(find.textContaining('扫码枪'), findsOneWidget);
  });

  testWidgets('a phone additionally offers the camera', (tester) async {
    await tester.pumpWidget(
      host(ScanInputField(onSubmit: (_) {}), phone),
    );

    expect(find.byIcon(Icons.photo_camera_outlined), findsOneWidget);
    expect(find.textContaining('摄像头'), findsWidgets);
  });

  testWidgets('an empty submission is ignored', (tester) async {
    final captured = <String>[];
    await tester.pumpWidget(
      host(ScanInputField(onSubmit: captured.add), desktop),
    );

    await tester.enterText(find.byType(TextField), '   ');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pump();

    expect(captured, isEmpty);
  });

  testWidgets('the explicit button submits what was typed', (tester) async {
    final captured = <String>[];
    await tester.pumpWidget(
      host(ScanInputField(onSubmit: captured.add), desktop),
    );

    await tester.enterText(find.byType(TextField), 'C123456');
    await tester.tap(find.text('识别编码'));
    await tester.pump();

    expect(captured, <String>['C123456']);
  });

  group('scan text normalization', () {
    test('strips the scanner CR/LF and surrounding whitespace only', () {
      expect(normalizeScanInput('  LABB:T1\r\n'), 'LABB:T1');
      expect(normalizeScanInput('\tLABL:K000001\n'), 'LABL:K000001');
      expect(normalizeScanInput('C123456'), 'C123456');
      // The payload itself is passed through unchanged: only the server decides
      // what a code means.
      expect(normalizeScanInput('LABB:T 1'), 'LABB:T 1');
    });

    test('platform capability detection never claims a desktop camera', () {
      final desktopCapabilities = detectScannerCapabilities();
      if (desktopCapabilities.camera) {
        // Running on a phone: the keyboard path must still exist.
        expect(desktopCapabilities.keyboardWedge, isTrue);
        expect(desktopCapabilities.clipboard, isTrue);
      } else {
        expect(desktopCapabilities.keyboardWedge, isTrue);
        expect(desktopCapabilities.clipboard, isTrue);
        expect(desktopCapabilities.hint, contains('扫码枪'));
      }
    });
  });
}
