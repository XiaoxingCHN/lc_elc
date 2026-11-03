import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/session_scope.dart';
import 'package:lab_inventory_client/features/unified/models/unified_item.dart';
import 'package:lab_inventory_client/features/unified/providers/unified_providers.dart';
import 'package:lab_inventory_client/features/unified/screens/pending_receipt_screen.dart';
import 'package:lab_inventory_client/features/unified/widgets/catalog_suggest_search.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';

import 'support/fake_lab_api.dart';

/// Inline catalog suggestions for the receipt / pending-receipt forms.
///
/// Every rule pinned here was verified on the web first; these tests keep the
/// Flutter field from regressing into a modal picker, a cached guess, or an
/// auto-commit. All transport is the repo's [FakeLabApi]: no test reaches a
/// server, and no test can be mistaken for real-stock acceptance.
void main() {
  group('catalogSuggestTerm', () {
    test('unwraps a C code, an lcsc: prefix and full-width input', () {
      expect(catalogSuggestTerm('C12345'), 'C12345');
      expect(catalogSuggestTerm('lcsc:C12345'), 'C12345');
      expect(catalogSuggestTerm(' LCSC : c12345 '), 'C12345');
      expect(catalogSuggestTerm('Ｃ１２３４５'), 'C12345');
    });

    test('keeps keywords, and never sends a bag/location payload as text', () {
      expect(catalogSuggestTerm('10uF 0805'), '10uF 0805');
      expect(catalogSuggestTerm('AP7361'), 'AP7361');
      expect(catalogSuggestTerm('LABB:TRACE-3'), '');
      expect(catalogSuggestTerm('LABL:K000001'), '');
    });
  });

  group('groupCatalogSuggestions', () {
    UnifiedItem catalog({String code = 'C100001', double stock = 0}) =>
        UnifiedItem.fromJson(
          itemJson(
            itemKey: 'catalog:$code',
            catalogCode: code,
            catalogStock: stock,
          ),
        );

    UnifiedItem local({
      String key = 'lab:42',
      String code = 'C100001',
      double quantity = 30,
      List<int> templates = const <int>[9],
    }) => UnifiedItem.fromJson(
      itemJson(
        itemKey: key,
        catalogCode: code,
        labQuantity: quantity,
        labTemplateIds: templates,
        catalogStock: 500,
      ),
    );

    test('one C number yields one group, local variant first', () {
      final groups = groupCatalogSuggestions(<UnifiedItem>[catalog(), local()]);
      expect(groups, hasLength(1));
      final group = groups.single;
      expect(group.primary.itemKey, 'lab:42');
      expect(group.code, 'C100001');
      expect(group.templateIds, <int>{9});
      expect(group.archiveCount, 1);
      expect(group.hasLocalArchives, isTrue);
      expect(group.labQuantity, 30);
    });

    test('local stock is never reported as supplier stock', () {
      final groups = groupCatalogSuggestions(<UnifiedItem>[local()]);
      final group = groups.single;
      expect(group.labQuantity, 30);
      expect(group.catalogStock, 500);
      expect(
        group.badges,
        containsAll(<String>['本地库存 30', '已有档案 1 个', '供货 500（非本地库存）']),
      );
      expect(group.badges.join(' '), isNot(contains('本地库存 500')));
    });

    test('groups without archives rank below archived ones', () {
      final groups = groupCatalogSuggestions(<UnifiedItem>[
        catalog(code: 'C2'),
        local(code: 'C1'),
      ]);
      expect(groups.map((g) => g.code), <String>['C1', 'C2']);
      expect(groups.last.hasLocalArchives, isFalse);
      expect(groups.last.archiveCount, 0);
    });

    test('displayed text never carries an internal prefix', () {
      final groups = groupCatalogSuggestions(<UnifiedItem>[
        UnifiedItem.fromJson(
          itemJson(
            itemKey: 'lab:7',
            name: '',
            mpn: '',
            labTemplateIds: <int>[3],
          ),
        ),
      ]);
      expect(groups.single.displayLabel.toLowerCase(), isNot(contains('lab:')));
      expect(groups.single.semanticsLabel, isNot(contains('lab:')));
    });
  });

  group('CatalogSuggestField', () {
    late FakeLabApi api;
    late List<UnifiedItem> picks;
    late List<String> queries;

    setUp(() {
      api = FakeLabApi();
      picks = <UnifiedItem>[];
      queries = <String>[];
    });

    Widget harness({
      bool enabled = true,
      Duration debounce = const Duration(milliseconds: 250),
    }) {
      return ProviderScope(
        overrides: [labApiProvider.overrideWithValue(api.client)],
        child: MaterialApp(
          theme: ThemeData(useMaterial3: true),
          home: Scaffold(
            body: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                children: <Widget>[
                  CatalogSuggestField(
                    enabled: enabled,
                    debounce: debounce,
                    onSelected: picks.add,
                    onQueryChanged: queries.add,
                  ),
                  const SizedBox(height: 12),
                  const TextButton(onPressed: null, child: Text('其他控件')),
                ],
              ),
            ),
          ),
        ),
      );
    }

    Future<void> type(WidgetTester tester, String text) async {
      await tester.enterText(find.byType(TextField), text);
      await tester.pump();
    }

    Future<void> answer(WidgetTester tester) async {
      await tester.pump(const Duration(milliseconds: 260));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 10));
    }

    testWidgets(
      'typing shows loading immediately, then one debounced request',
      (tester) async {
        api.onCall = (path, params) async => <String, dynamic>{
          'items': <Map<String, dynamic>>[
            itemJson(itemKey: 'catalog:C100001', catalogCode: 'C100001'),
          ],
          'total': 1,
        };
        await tester.pumpWidget(harness());

        await type(tester, 'C1');
        expect(find.text('正在检索器件资料…'), findsOneWidget);
        await tester.pump(const Duration(milliseconds: 100));
        expect(
          api.calls,
          isEmpty,
          reason: 'no request before the debounce fires',
        );

        await tester.pump(const Duration(milliseconds: 160));
        await tester.pump();
        expect(api.countFor(LabApiRoutes.catalogSearch), 1);
        expect(api.calls.last.params['query'], 'C1');
        expect(find.text('C100001'), findsOneWidget);
        expect(queries, <String>[
          'C1',
        ], reason: 'the screen is told to drop a stale pick');
      },
    );

    testWidgets('a newer keystroke replaces the pending request', (
      tester,
    ) async {
      api.onCall = (path, params) async => <String, dynamic>{
        'items': <Map<String, dynamic>>[
          itemJson(
            itemKey: 'catalog:${params['query']}',
            catalogCode: params['query'] as String,
          ),
        ],
        'total': 1,
      };
      await tester.pumpWidget(harness());

      await type(tester, 'C1');
      await tester.pump(const Duration(milliseconds: 100));
      await type(tester, 'C12');
      await tester.pump(const Duration(milliseconds: 260));
      await tester.pump();

      expect(
        api.countFor(LabApiRoutes.catalogSearch),
        1,
        reason: 'the superseded keystroke never reaches the server',
      );
      expect(api.calls.single.params['query'], 'C12');
      expect(find.text('C12'), findsWidgets);
      expect(find.text('C1'), findsNothing);
    });

    testWidgets('too short a term never searches and closes the panel', (
      tester,
    ) async {
      await tester.pumpWidget(harness());
      await type(tester, 'C');
      expect(find.text('正在检索器件资料…'), findsNothing);
      await tester.pump(const Duration(milliseconds: 500));
      expect(api.calls, isEmpty);
    });

    testWidgets('empty result keeps a manual-create hint', (tester) async {
      api.onCall = (path, params) async => <String, dynamic>{
        'items': <Map<String, dynamic>>[],
        'total': 0,
      };
      await tester.pumpWidget(harness());

      await type(tester, 'C999999');
      await answer(tester);
      expect(find.text('没有匹配的器件'), findsOneWidget);
      expect(find.textContaining('新建器件'), findsOneWidget);
    });

    testWidgets('error shows a real retry that searches again', (tester) async {
      var fail = true;
      api.onCall = (path, params) async {
        if (fail) throw businessFailure('NETWORK_ERROR', '资料读取失败');
        return <String, dynamic>{
          'items': <Map<String, dynamic>>[
            itemJson(itemKey: 'catalog:C100001', catalogCode: 'C100001'),
          ],
          'total': 1,
        };
      };
      await tester.pumpWidget(harness());

      await type(tester, 'C100001');
      await answer(tester);
      expect(find.text('检索失败：NETWORK_ERROR'), findsOneWidget);
      expect(find.text('资料读取失败'), findsOneWidget);

      fail = false;
      await tester.tap(find.text('重试检索'));
      await tester.pump();
      await tester.pump();
      expect(api.countFor(LabApiRoutes.catalogSearch), 2);
      expect(find.text('C100001'), findsWidgets);
    });

    testWidgets('an out-of-order response never overwrites newer results', (
      tester,
    ) async {
      final first = Completer<Map<String, dynamic>>();
      var calls = 0;
      api.onCall = (path, params) async {
        calls++;
        if (calls == 1) return first.future;
        return <String, dynamic>{
          'items': <Map<String, dynamic>>[
            itemJson(itemKey: 'catalog:C22', catalogCode: 'C22', name: '新结果'),
          ],
          'total': 1,
        };
      };
      await tester.pumpWidget(harness());

      await type(tester, 'C1');
      await tester.pump(const Duration(milliseconds: 260));
      await type(tester, 'C22');
      await tester.pump(const Duration(milliseconds: 260));
      await tester.pump();
      expect(find.text('新结果'), findsOneWidget);

      first.complete(<String, dynamic>{
        'items': <Map<String, dynamic>>[
          itemJson(itemKey: 'catalog:C1', catalogCode: 'C1', name: '旧结果'),
        ],
        'total': 1,
      });
      await tester.pump();
      await tester.pump();

      expect(find.text('旧结果'), findsNothing);
      expect(find.text('新结果'), findsOneWidget);
      await tester.tap(find.text('新结果'));
      await tester.pump();
      // A supplier card normalizes to its 'lcsc:' identity, which is still the
      // key the server returned for that row.
      expect(picks.single.itemKey, 'lcsc:C22');
    });

    testWidgets(
      'clearing closes the panel and a late response cannot reopen it',
      (tester) async {
        final first = Completer<Map<String, dynamic>>();
        api.onCall = (path, params) async => first.future;
        await tester.pumpWidget(harness());

        await type(tester, 'C1');
        await tester.pump(const Duration(milliseconds: 260));
        expect(find.text('正在检索器件资料…'), findsOneWidget);

        await tester.tap(find.byTooltip('清空搜索'));
        await tester.pump();
        expect(find.text('正在检索器件资料…'), findsNothing);
        expect(queries, <String>['C1', '']);

        first.complete(<String, dynamic>{
          'items': <Map<String, dynamic>>[
            itemJson(itemKey: 'catalog:C1', catalogCode: 'C1', name: '迟到的结果'),
          ],
          'total': 1,
        });
        await tester.pump();
        await tester.pump();
        expect(find.text('迟到的结果'), findsNothing);
        expect(picks, isEmpty);
      },
    );

    testWidgets('an outside tap closes the panel without committing', (
      tester,
    ) async {
      api.onCall = (path, params) async => <String, dynamic>{
        'items': <Map<String, dynamic>>[
          itemJson(itemKey: 'catalog:C100001', catalogCode: 'C100001'),
        ],
        'total': 1,
      };
      await tester.pumpWidget(harness());

      await type(tester, 'C100001');
      await answer(tester);
      expect(find.text('C100001'), findsWidgets);

      // The panel now sits above the button, so tap real empty body space that
      // is outside both the field and the panel.
      await tester.tapAt(const Offset(400, 400));
      await tester.pump();
      expect(
        find.text('C100001'),
        findsOneWidget,
        reason: 'only the field text remains; the suggestion panel is gone',
      );
      expect(picks, isEmpty);
    });

    testWidgets('arrow keys highlight, Enter commits, Escape and Tab close', (
      tester,
    ) async {
      api.onCall = (path, params) async => <String, dynamic>{
        'items': <Map<String, dynamic>>[
          itemJson(
            itemKey: 'lab:42',
            catalogCode: 'C100001',
            name: '本地器件',
            labTemplateIds: <int>[9],
          ),
          itemJson(
            itemKey: 'catalog:C200002',
            catalogCode: 'C200002',
            name: '另一个器件',
          ),
        ],
        'total': 2,
      };
      await tester.pumpWidget(harness());

      await tester.enterText(find.byType(TextField), 'C1');
      await answer(tester);

      await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
      await tester.pump();
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(picks.single.itemKey, 'lab:42');
      expect(
        tester.widget<TextField>(find.byType(TextField)).controller!.text,
        'C100001',
        reason: 'the field keeps an operator-facing label, not the item_key',
      );

      await tester.enterText(find.byType(TextField), 'C1');
      await tester.pump();
      await answer(tester);
      await tester.showKeyboard(find.byType(TextField));
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.pump();
      expect(find.text('本地器件'), findsNothing);

      await tester.enterText(find.byType(TextField), 'C1');
      await tester.pump();
      await answer(tester);
      await tester.showKeyboard(find.byType(TextField));
      await tester.sendKeyEvent(LogicalKeyboardKey.tab);
      await tester.pump();
      expect(find.text('本地器件'), findsNothing);
    });

    testWidgets('does not search while an IME composition is in flight', (
      tester,
    ) async {
      api.onCall = (path, params) async => <String, dynamic>{
        'items': <Map<String, dynamic>>[
          itemJson(itemKey: 'catalog:C100001', catalogCode: 'C100001'),
        ],
        'total': 1,
      };
      await tester.pumpWidget(harness());
      await tester.showKeyboard(find.byType(TextField));

      tester.testTextInput.updateEditingValue(
        const TextEditingValue(
          text: 'C1',
          selection: TextSelection.collapsed(offset: 2),
          composing: TextRange(start: 0, end: 2),
        ),
      );
      await tester.pump(const Duration(milliseconds: 500));
      expect(api.calls, isEmpty);

      tester.testTextInput.updateEditingValue(
        const TextEditingValue(
          text: 'C12',
          selection: TextSelection.collapsed(offset: 3),
        ),
      );
      await tester.pump(const Duration(milliseconds: 260));
      await tester.pump();
      expect(api.countFor(LabApiRoutes.catalogSearch), 1);
      expect(api.calls.single.params['query'], 'C12');
    });

    testWidgets('read-only mode blocks typing and closes any open panel', (
      tester,
    ) async {
      api.onCall = (path, params) async => <String, dynamic>{
        'items': <Map<String, dynamic>>[
          itemJson(itemKey: 'catalog:C100001', catalogCode: 'C100001'),
        ],
        'total': 1,
      };
      await tester.pumpWidget(harness());
      await type(tester, 'C100001');
      await answer(tester);
      expect(find.text('C100001'), findsWidgets);

      await tester.pumpWidget(harness(enabled: false));
      await tester.pump();
      expect(
        find.text('C100001'),
        findsOneWidget,
        reason: 'the submission lock closes the suggestion panel',
      );
      final field = tester.widget<TextField>(find.byType(TextField));
      expect(field.readOnly, isTrue);
      expect(field.enabled, isFalse);
    });
  });

  group('PendingReceiptScreen inline selection', () {
    late FakeLabApi api;

    Map<String, dynamic> detailWith(List<Map<String, dynamic>> materials) =>
        <String, dynamic>{
          'item': itemJson(
            itemKey: 'lab:42',
            catalogCode: 'C100001',
            name: '本地器件',
            labTemplateIds: <int>[9],
          ),
          'materials': materials,
        };

    Widget screen() => ProviderScope(
      overrides: [
        labApiProvider.overrideWithValue(api.client),
        sessionScopeSourceProvider.overrideWithValue(
          const LabSessionScope(uid: 7),
        ),
      ],
      child: const MaterialApp(home: PendingReceiptScreen()),
    );

    Finder labeled(String label) =>
        find.ancestor(of: find.text(label), matching: find.byType(TextField));

    /// A phone-sized default surface clips the create button; these screens are
    /// long forms, so give the tests room instead of tapping off-screen.
    Future<void> tallView(WidgetTester tester) async {
      tester.view.physicalSize = const Size(900, 1600);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
    }

    Future<void> searchAndPick(WidgetTester tester) async {
      await tester.enterText(find.byType(TextField).first, 'C100001');
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 260));
      await tester.pump();
      await tester.tap(find.text('本地器件').last);
      await tester.pump();
      await tester.pump();
    }

    testWidgets('a pick commits the server item_key and archive id on create', (
      tester,
    ) async {
      api = FakeLabApi(
        onCall: (path, params) async {
          switch (path) {
            case LabApiRoutes.pendingList:
              return <String, dynamic>{'records': <Map<String, dynamic>>[]};
            case LabApiRoutes.catalogSearch:
              return <String, dynamic>{
                'items': <Map<String, dynamic>>[
                  itemJson(
                    itemKey: 'lab:42',
                    catalogCode: 'C100001',
                    name: '本地器件',
                    labTemplateIds: <int>[9],
                  ),
                ],
                'total': 1,
              };
            case LabApiRoutes.catalogDetail:
              return detailWith(<Map<String, dynamic>>[
                <String, dynamic>{
                  'product_template_id': 9,
                  'name': '本地器件',
                  'sn': 'SN-A',
                },
              ]);
            case LabApiRoutes.pendingCreate:
              return <String, dynamic>{
                'records': <Map<String, dynamic>>[
                  <String, dynamic>{'id': 1, 'trace_code': 'T1'},
                ],
              };
            default:
              return <String, dynamic>{'locations': <Map<String, dynamic>>[]};
          }
        },
      );
      await tallView(tester);
      await tester.pumpWidget(screen());
      await tester.pumpAndSettle();

      await searchAndPick(tester);
      expect(find.textContaining('已选：本地器件'), findsOneWidget);
      expect(
        api.countFor(LabApiRoutes.pendingCreate),
        0,
        reason: 'selecting a suggestion never writes inventory or bags',
      );
      expect(api.countFor(LabApiRoutes.inventoryReceipt), 0);

      await tester.enterText(labeled('每袋初始数量'), '20');
      await tester.enterText(labeled('实物袋数'), '2');
      await tester.ensureVisible(find.text('生成袋码并加入待打印'));
      await tester.tap(find.text('生成袋码并加入待打印'));
      await tester.pumpAndSettle();

      final params = api.onlyParams(LabApiRoutes.pendingCreate);
      expect(params['item_key'], 'lab:42');
      expect(params['product_template_id'], 9);
      expect(params['quantity'], 20.0);
      expect(params['count'], 2);
      expect(api.countFor(LabApiRoutes.inventoryReceipt), 0);
      expect(tester.takeException(), isNull);
    });

    testWidgets(
      'several local archives require an explicit choice before create',
      (tester) async {
        api = FakeLabApi(
          onCall: (path, params) async {
            switch (path) {
              case LabApiRoutes.pendingList:
                return <String, dynamic>{'records': <Map<String, dynamic>>[]};
              case LabApiRoutes.catalogSearch:
                return <String, dynamic>{
                  'items': <Map<String, dynamic>>[
                    itemJson(
                      itemKey: 'lab:42',
                      catalogCode: 'C100001',
                      name: '本地器件',
                      labTemplateIds: <int>[9, 11],
                    ),
                  ],
                  'total': 1,
                };
              case LabApiRoutes.catalogDetail:
                return detailWith(<Map<String, dynamic>>[
                  <String, dynamic>{
                    'product_template_id': 9,
                    'name': '档案 A',
                    'sn': 'SN-A',
                  },
                  <String, dynamic>{
                    'product_template_id': 11,
                    'name': '档案 B',
                    'sn': 'SN-B',
                  },
                ]);
              default:
                return <String, dynamic>{'locations': <Map<String, dynamic>>[]};
            }
          },
        );
        await tallView(tester);
        await tester.pumpWidget(screen());
        await tester.pumpAndSettle();

        await searchAndPick(tester);
        expect(find.text('此编号对应多个本地档案，请先选择本次制袋的档案。'), findsOneWidget);
        expect(api.countFor(LabApiRoutes.pendingCreate), 0);

        final create = find.widgetWithText(FilledButton, '生成袋码并加入待打印');
        expect(
          tester.widget<FilledButton>(create).onPressed,
          isNull,
          reason: 'create stays blocked until the operator picks an archive',
        );

        await tester.tap(find.text('内部档案 / SN'));
        await tester.pumpAndSettle();
        await tester.tap(find.textContaining('SN-B').last);
        await tester.pumpAndSettle();
        expect(tester.widget<FilledButton>(create).onPressed, isNotNull);
        expect(find.text('此编号对应多个本地档案，请先选择本次制袋的档案。'), findsNothing);
      },
    );

    testWidgets(
      'an in-flight submission locks the search field and resubmission',
      (tester) async {
        final create = Completer<Map<String, dynamic>>();
        api = FakeLabApi(
          onCall: (path, params) async {
            switch (path) {
              case LabApiRoutes.pendingList:
                return <String, dynamic>{'records': <Map<String, dynamic>>[]};
              case LabApiRoutes.catalogSearch:
                return <String, dynamic>{
                  'items': <Map<String, dynamic>>[
                    itemJson(
                      itemKey: 'lab:42',
                      catalogCode: 'C100001',
                      name: '本地器件',
                      labTemplateIds: <int>[9],
                    ),
                  ],
                  'total': 1,
                };
              case LabApiRoutes.catalogDetail:
                return detailWith(<Map<String, dynamic>>[
                  <String, dynamic>{
                    'product_template_id': 9,
                    'name': '本地器件',
                    'sn': 'SN-A',
                  },
                ]);
              case LabApiRoutes.pendingCreate:
                return create.future;
              default:
                return <String, dynamic>{'locations': <Map<String, dynamic>>[]};
            }
          },
        );
        await tallView(tester);
        await tester.pumpWidget(screen());
        await tester.pumpAndSettle();

        await searchAndPick(tester);
        await tester.enterText(labeled('每袋初始数量'), '5');
        await tester.enterText(labeled('实物袋数'), '1');
        await tester.ensureVisible(find.text('生成袋码并加入待打印'));
        await tester.tap(find.text('生成袋码并加入待打印'));
        await tester.pump();

        final field = tester.widget<TextField>(find.byType(TextField).first);
        expect(
          field.enabled,
          isFalse,
          reason:
              'the search field is read-only while the request is in flight',
        );
        expect(field.readOnly, isTrue);
        expect(api.countFor(LabApiRoutes.pendingCreate), 1);
        // Once a create attempt exists the label flips to the retry wording; the
        // button itself must stay disabled while the first request is in flight.
        expect(find.text('重试生成袋码'), findsOneWidget);
        final createButton = find.widgetWithText(FilledButton, '重试生成袋码');
        expect(createButton, findsOneWidget);
        expect(
          tester.widget<FilledButton>(createButton).onPressed,
          isNull,
          reason: 'a second submission is blocked while the first is in flight',
        );

        create.complete(<String, dynamic>{
          'records': <Map<String, dynamic>>[
            <String, dynamic>{'id': 1, 'trace_code': 'T1'},
          ],
        });
        await tester.pumpAndSettle();
        expect(api.countFor(LabApiRoutes.pendingCreate), 1);
        expect(tester.takeException(), isNull);
      },
    );
  });
}
