import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/catalog_query.dart';
import 'package:lab_inventory_client/features/unified/providers/catalog_providers.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';

import 'support/fake_lab_api.dart';

/// Unified-list paging and merge behaviour.
///
/// Acceptance points covered: server-side paging through the opaque cursor, ONE
/// card per canonical identity even when a page boundary repeats a row, no
/// accidental merge of unidentified rows, a stale response never landing in a
/// newer result set, and a failure staying a FAILURE instead of an empty list.
void main() {
  Map<String, dynamic> page(
    List<Map<String, dynamic>> items, {
    String? next,
    int? total,
  }) {
    return <String, dynamic>{
      'items': items,
      'next_cursor': next,
      'total': total ?? items.length,
      'inventory_revision': 'rev-1',
    };
  }

  test('pages through the cursor and appends in server order', () async {
    final api = FakeLabApi();
    api.onCall = (path, params) async {
      final cursor = params['cursor'];
      if (cursor == null) {
        return page(
          <Map<String, dynamic>>[
            itemJson(itemKey: 'lcsc:C1', labQuantity: 5),
            itemJson(itemKey: 'lcsc:C2'),
          ],
          next: 'PAGE-2',
          total: 3,
        );
      }
      expect(cursor, 'PAGE-2');
      return page(
        <Map<String, dynamic>>[itemJson(itemKey: 'lcsc:C3')],
        next: null,
        total: 3,
      );
    };

    final notifier = CatalogNotifier(api: api.client);
    await notifier.refresh();
    expect(notifier.state.items.map((item) => item.itemKey), <String>['lcsc:C1', 'lcsc:C2']);
    expect(notifier.state.total, 3);
    expect(notifier.state.hasMore, isTrue);

    await notifier.loadMore();
    expect(
      notifier.state.items.map((item) => item.itemKey),
      <String>['lcsc:C1', 'lcsc:C2', 'lcsc:C3'],
    );
    expect(notifier.state.hasMore, isFalse);

    // The server received exactly two requests, the second with the cursor.
    expect(api.countFor(LabApiRoutes.catalogSearch), 2);
    final second = api.callsFor(LabApiRoutes.catalogSearch)[1].params;
    expect(second['cursor'], 'PAGE-2');
    // No client-side full-library fetch.
    expect(second['limit'], lessThanOrEqualTo(LabApiClient.maxPageSize));
  });

  test('the same C code never becomes two cards (page boundary repeat)', () async {
    final api = FakeLabApi();
    api.onCall = (path, params) async {
      if (params['cursor'] == null) {
        return page(
          <Map<String, dynamic>>[
            itemJson(itemKey: 'lcsc:C1'),
            itemJson(itemKey: 'lcsc:C2'),
          ],
          next: 'PAGE-2',
        );
      }
      // The server repeats C1 across the boundary (a row updated between pages).
      return page(<Map<String, dynamic>>[
        itemJson(itemKey: 'lcsc:C2'),
        itemJson(itemKey: 'lcsc:C3'),
      ]);
    };

    final notifier = CatalogNotifier(api: api.client);
    await notifier.refresh();
    await notifier.loadMore();

    expect(
      notifier.state.items.map((item) => item.itemKey),
      <String>['lcsc:C1', 'lcsc:C2', 'lcsc:C3'],
    );
  });

  test('two different C codes bound locally stay two cards', () async {
    final api = FakeLabApi();
    api.answerWith(<String, Map<String, dynamic>>{
      LabApiRoutes.catalogSearch: page(<Map<String, dynamic>>[
        itemJson(itemKey: 'lcsc:C1', labTemplateIds: <int>[42]),
        itemJson(itemKey: 'lcsc:C2', labTemplateIds: <int>[43]),
      ]),
    });

    final notifier = CatalogNotifier(api: api.client);
    await notifier.refresh();
    expect(notifier.state.items.length, 2);
  });

  test('rows without a usable identity are never merged together', () async {
    final api = FakeLabApi();
    api.answerWith(<String, Map<String, dynamic>>{
      LabApiRoutes.catalogSearch: page(<Map<String, dynamic>>[
        <String, dynamic>{'name': '无编号 A', 'lab_quantity': 0},
        <String, dynamic>{'name': '无编号 B', 'lab_quantity': 0},
      ]),
    });

    final notifier = CatalogNotifier(api: api.client);
    await notifier.refresh();
    expect(notifier.state.items.length, 2,
        reason: 'two unidentified rows must remain two rows');
  });

  test('changing the query discards a response that is still in flight', () async {
    final api = FakeLabApi();
    var slowStarted = false;

    api.onCall = (path, params) async {
      final query = params['query'];
      if (query == 'SLOW') {
        slowStarted = true;
        // Answer the stale request only after the new one has been applied.
        await Future<void>.delayed(const Duration(milliseconds: 60));
        return page(<Map<String, dynamic>>[itemJson(itemKey: 'lcsc:C900')]);
      }
      return page(<Map<String, dynamic>>[itemJson(itemKey: 'lcsc:C111')]);
    };

    final notifier = CatalogNotifier(api: api.client);
    final slow = notifier.updateQuery(const CatalogQuery(text: 'SLOW'));
    await Future<void>.delayed(const Duration(milliseconds: 10));
    expect(slowStarted, isTrue);
    await notifier.updateQuery(const CatalogQuery(text: 'FAST'));
    await slow;

    expect(
      notifier.state.items.map((item) => item.itemKey),
      <String>['lcsc:C111'],
      reason: 'the stale SLOW page must not be appended to the FAST result',
    );
  });

  test('an error becomes an error state, never "no results"', () async {
    final api = FakeLabApi();
    api.onCall = (path, params) async =>
        throw businessFailure('NETWORK_ERROR', '无法连接服务器，请检查网络后重试。');

    final notifier = CatalogNotifier(api: api.client);
    await notifier.refresh();

    expect(notifier.state.items, isEmpty);
    expect(notifier.state.isEmpty, isFalse,
        reason: 'a failed request must not look like an empty library');
    expect(notifier.state.hasError, isTrue);
    expect(notifier.state.error, '无法连接服务器，请检查网络后重试。');
    expect(notifier.state.errorCode, 'NETWORK_ERROR');
  });

  test('a load-more failure keeps the rows already shown', () async {
    final api = FakeLabApi();
    var calls = 0;
    api.onCall = (path, params) async {
      calls++;
      if (calls == 1) {
        return page(
          <Map<String, dynamic>>[itemJson(itemKey: 'lcsc:C1')],
          next: 'PAGE-2',
        );
      }
      throw businessFailure('CONFLICT', '服务端检测到重复数据，请刷新后重试。');
    };

    final notifier = CatalogNotifier(api: api.client);
    await notifier.refresh();
    await notifier.loadMore();

    expect(notifier.state.items.length, 1);
    expect(notifier.state.error, isNotNull);
    expect(notifier.state.loadingMore, isFalse);
  });

  test('refresh resets to the first page of the CURRENT query', () async {
    final api = FakeLabApi();
    api.onCall = (path, params) async {
      expect(params['cursor'] == null, isTrue,
          reason: 'refresh must not reuse the previous cursor');
      return page(<Map<String, dynamic>>[itemJson(itemKey: 'lcsc:C1')], total: 99);
    };

    final notifier = CatalogNotifier(api: api.client);
    await notifier.updateQuery(const CatalogQuery(text: 'C1', stockOnly: true));
    await notifier.refresh();

    final params = api.callsFor(LabApiRoutes.catalogSearch).last.params;
    expect(params['query'], 'C1');
    expect(params['stock_only'], true);
    expect(notifier.state.total, 99);
  });

  test('the query is serialized without any client-side filtering of rows', () async {
    final api = FakeLabApi();
    api.answerWith(<String, Map<String, dynamic>>{
      LabApiRoutes.catalogSearch: page(<Map<String, dynamic>>[
        itemJson(itemKey: 'lcsc:C1', name: '不相关名称'),
      ]),
    });

    final notifier = CatalogNotifier(api: api.client);
    await notifier.updateQuery(const CatalogQuery(text: 'abc', categoryId: 7));

    expect(notifier.state.items.length, 1,
        reason: 'rows the server returned are shown; the client does not drop them');
    final params = api.onlyParams(LabApiRoutes.catalogSearch);
    expect(params['query'], 'abc');
    expect(params['category_id'], 7);
  });
}
