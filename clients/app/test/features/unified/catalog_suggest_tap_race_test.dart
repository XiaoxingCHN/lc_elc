import 'dart:async';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/unified_item.dart';
import 'package:lab_inventory_client/features/unified/providers/unified_providers.dart';
import 'package:lab_inventory_client/features/unified/widgets/catalog_suggest_search.dart';

import 'support/fake_lab_api.dart';

void main() {
  testWidgets('a rebuild between pointer down and up must not lose the tap',
      (tester) async {
    final picks = <UnifiedItem>[];
    final second = Completer<Map<String, dynamic>>();
    var calls = 0;
    final api = FakeLabApi(
      onCall: (path, params) async {
        calls++;
        if (calls == 1) {
          return <String, dynamic>{
            'items': <Map<String, dynamic>>[
              itemJson(itemKey: 'catalog:C2054912', catalogCode: 'C2054912',
                  name: 'STM32F103C8T6'),
            ],
            'total': 1,
          };
        }
        return second.future;
      },
    );

    await tester.pumpWidget(ProviderScope(
      overrides: [labApiProvider.overrideWithValue(api.client)],
      child: MaterialApp(
        home: Scaffold(
          body: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(children: <Widget>[
              CatalogSuggestField(onSelected: picks.add),
            ]),
          ),
        ),
      ),
    ));

    await tester.enterText(find.byType(TextField), 'STM32F103C8');
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 260));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 10));

    final row = find.textContaining('STM32F103C8T6');
    expect(row, findsWidgets);

    final gesture = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await gesture.addPointer(location: Offset.zero);
    addTearDown(gesture.removePointer);
    await tester.pump();

    await gesture.down(tester.getCenter(row.first));
    await tester.pump();

    // A second search is in flight and its response lands mid-gesture, which
    // rebuilds the rows before the pointer goes up.
    await tester.enterText(find.byType(TextField), 'STM32F103C8T');
    await tester.pump(const Duration(milliseconds: 260));
    second.complete(<String, dynamic>{
      'items': <Map<String, dynamic>>[
        itemJson(itemKey: 'catalog:C2054912', catalogCode: 'C2054912',
            name: 'STM32F103C8T6'),
      ],
      'total': 1,
    });
    await tester.pump();

    await gesture.up();
    await tester.pump();
    await tester.pump();

    expect(picks, hasLength(1),
        reason: 'the tap started on a real row and must still commit');
  });
}
