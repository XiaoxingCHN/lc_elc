import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/widgets/status_banner.dart';

void main() {
  for (final brightness in Brightness.values) {
    for (final width in [320.0, 1280.0]) {
      testWidgets('status banner at $width $brightness with 200% text', (
        tester,
      ) async {
        tester.view.physicalSize = Size(width, 600);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        await tester.pumpWidget(
          MaterialApp(
            theme: ThemeData(brightness: brightness),
            home: MediaQuery(
              data: MediaQueryData(
                size: Size(width, 600),
                textScaler: const TextScaler.linear(2),
              ),
              child: Scaffold(
                body: ListView(
                  padding: const EdgeInsets.all(8),
                  children: <Widget>[
                    for (final tone in StatusTone.values)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: StatusBanner(
                          message: '上一页加载失败，请检查网络后重试：${tone.name}',
                          tone: tone,
                          dense: tone == StatusTone.info,
                          action: tone == StatusTone.error
                              ? TextButton(
                                  onPressed: () {},
                                  child: const Text('重试'),
                                )
                              : null,
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        );
        expect(tester.takeException(), isNull);
        // Every tone keeps a text label; colour alone never carries the state.
        for (final tone in StatusTone.values) {
          expect(find.text('上一页加载失败，请检查网络后重试：${tone.name}'), findsOneWidget);
        }
        // The error tone stays actionable at 200% text.
        expect(find.text('重试'), findsOneWidget);
      });
    }
  }
}
