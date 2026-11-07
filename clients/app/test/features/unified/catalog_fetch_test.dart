import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/catalog_query.dart';
import 'package:lab_inventory_client/features/unified/models/unified_item.dart';
import 'package:lab_inventory_client/features/unified/providers/catalog_providers.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';

import 'support/fake_lab_api.dart';

/// On-demand fetch: the client never invents a suggestion, never polls a
/// terminal state, and always shows the server's Chinese outcome.
void main() {
  Map<String, dynamic> page(
    List<Map<String, dynamic>> items, {
    Map<String, dynamic>? suggestion,
  }) {
    return <String, dynamic>{
      'items': items,
      'next_cursor': null,
      'total': items.length,
      'inventory_revision': 'rev-1',
      if (suggestion != null) 'fetch_suggestion': suggestion,
    };
  }

  Map<String, dynamic> suggestionJson({
    String query = 'TLV77733PDBVR',
    bool canFetch = true,
  }) {
    return <String, dynamic>{
      'kind': 'mpn',
      'query': query,
      'can_fetch': canFetch,
      'message': '本地库暂无该型号，可立即从立创商城抓取。',
    };
  }

  Map<String, dynamic> statusJson(
    String state, {
    int? requestId = 7,
    String query = 'TLV77733PDBVR',
    String message = '',
    List<Map<String, dynamic>> candidates = const <Map<String, dynamic>>[],
  }) {
    return <String, dynamic>{
      'request_id': requestId,
      'state': state,
      'query': query,
      'query_kind': 'mpn',
      'catalog_code': '',
      'item_key': '',
      'message': message,
      'candidates': candidates,
    };
  }

  Future<void> waitUntil(bool Function() condition, {String? reason}) async {
    final deadline = DateTime.now().add(const Duration(seconds: 3));
    while (!condition()) {
      if (DateTime.now().isAfter(deadline)) {
        fail('timed out waiting for ${reason ?? 'condition'}');
      }
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }
  }

  test('an exact-MPN suggestion is exposed only when the server offers it',
      () async {
    final api = FakeLabApi();
    api.onCall = (path, params) async {
      expect(path, LabApiRoutes.catalogSearch);
      return page(const <Map<String, dynamic>>[],
          suggestion: suggestionJson());
    };

    final notifier = CatalogNotifier(api: api.client);
    await notifier.refresh();

    expect(notifier.state.isEmpty, isTrue);
    final suggestion = notifier.state.fetchSuggestion;
    expect(suggestion, isNotNull);
    expect(suggestion!.canFetch, isTrue);
    expect(suggestion.query, 'TLV77733PDBVR');
    expect(notifier.state.fetchStatus, isNull);
  });

  test('queued fetch is polled until done, then the list is refreshed',
      () async {
    final api = FakeLabApi();
    var searches = 0;
    var polls = 0;
    api.onCall = (path, params) async {
      switch (path) {
        case LabApiRoutes.catalogSearch:
          searches++;
          return searches == 1
              ? page(const <Map<String, dynamic>>[],
                  suggestion: suggestionJson())
              : page(<Map<String, dynamic>>[
                  itemJson(
                    itemKey: 'lcsc:C54110218',
                    catalogCode: 'C54110218',
                    name: 'TLV77733PDBVR 稳压器',
                    mpn: 'TLV77733PDBVR',
                  ),
                ]);
        case LabApiRoutes.catalogFetch:
          expect(params['query'], 'TLV77733PDBVR');
          expect(params.containsKey('catalog_code'), isFalse);
          return statusJson('queued');
        case LabApiRoutes.catalogFetchStatus:
          polls++;
          expect(params['request_id'], 7);
          return polls == 1
              ? statusJson('fetching')
              : statusJson('done',
                  message: '已抓取并入库（中文详情）。');
        default:
          throw StateError('unexpected path $path');
      }
    };

    final notifier = CatalogNotifier(
      api: api.client,
      fetchPollInterval: const Duration(milliseconds: 5),
      maxFetchPolls: 20,
    );
    await notifier.refresh();
    await notifier.startFetch();

    expect(notifier.state.fetchBusy, isFalse);
    expect(notifier.state.fetchStatus?.state, 'queued');

    await waitUntil(
      () =>
          notifier.state.fetchStatus?.isDone == true &&
          notifier.state.items.isNotEmpty,
      reason: 'done status and refreshed list',
    );

    expect(polls, greaterThanOrEqualTo(2));
    expect(notifier.state.items.single.catalogCode, 'C54110218');
    expect(searches, 2);
  });

  test('a candidate choice re-submits the same MPN with that C code',
      () async {
    final api = FakeLabApi();
    var searches = 0;
    final fetchQueries = <Map<String, dynamic>>[];
    api.onCall = (path, params) async {
      switch (path) {
        case LabApiRoutes.catalogSearch:
          searches++;
          return searches == 1
              ? page(const <Map<String, dynamic>>[],
                  suggestion: suggestionJson())
              : page(<Map<String, dynamic>>[
                  itemJson(itemKey: 'lcsc:C2', catalogCode: 'C2', mpn: 'SAME'),
                ]);
        case LabApiRoutes.catalogFetch:
          fetchQueries.add(params);
          return fetchQueries.length == 1
              ? statusJson('candidates', candidates: <Map<String, dynamic>>[
                  <String, dynamic>{
                    'catalog_code': 'C1',
                    'mpn': 'SAME',
                    'package': 'SOT-23-5',
                  },
                  <String, dynamic>{
                    'catalog_code': 'C2',
                    'mpn': 'SAME',
                    'package': 'WSON-8',
                  },
                ])
              : statusJson('done');
        case LabApiRoutes.catalogFetchStatus:
          fail('a terminal candidates status must not be polled');
        default:
          throw StateError('unexpected path $path');
      }
    };

    final notifier = CatalogNotifier(
      api: api.client,
      fetchPollInterval: const Duration(milliseconds: 5),
    );
    await notifier.refresh();
    await notifier.startFetch();

    final status = notifier.state.fetchStatus!;
    expect(status.isCandidates, isTrue);
    expect(status.candidates.map((c) => c.catalogCode), <String>['C1', 'C2']);
    expect(status.candidates.first.label, 'SAME · SOT-23-5 (C1)');

    await notifier.chooseFetchCandidate(status.candidates.last);
    await waitUntil(() => notifier.state.items.isNotEmpty,
        reason: 'list refreshed after the chosen candidate');

    expect(fetchQueries.length, 2);
    expect(fetchQueries.last['query'], 'TLV77733PDBVR');
    expect(fetchQueries.last['catalog_code'], 'C2');
  });

  test('a refused fetch shows the server message and stops polling', () async {
    final api = FakeLabApi();
    api.onCall = (path, params) async {
      switch (path) {
        case LabApiRoutes.catalogSearch:
          return page(const <Map<String, dynamic>>[],
              suggestion: suggestionJson());
        case LabApiRoutes.catalogFetch:
          throw businessFailure('RATE_LIMITED', '抓取请求过于频繁，请稍后再试。');
        case LabApiRoutes.catalogFetchStatus:
          fail('a refused request must not be polled');
        default:
          throw StateError('unexpected path $path');
      }
    };

    final notifier = CatalogNotifier(api: api.client);
    await notifier.refresh();
    await notifier.startFetch();

    final status = notifier.state.fetchStatus!;
    expect(status.state, 'failed');
    expect(status.message, contains('过于频繁'));
    expect(notifier.state.fetchBusy, isFalse);
  });

  test('without a server suggestion nothing is requested', () async {
    final api = FakeLabApi();
    api.onCall = (path, params) async {
      expect(path, LabApiRoutes.catalogSearch);
      return page(const <Map<String, dynamic>>[]);
    };

    final notifier = CatalogNotifier(api: api.client);
    await notifier.refresh();
    expect(notifier.state.fetchSuggestion, isNull);

    await notifier.startFetch();
    expect(api.countFor(LabApiRoutes.catalogFetch), 0);
    expect(notifier.state.fetchStatus, isNull);
  });

  test('changing the query clears the fetch state', () async {
    final api = FakeLabApi();
    var searches = 0;
    api.onCall = (path, params) async {
      switch (path) {
        case LabApiRoutes.catalogSearch:
          searches++;
          return page(
            const <Map<String, dynamic>>[],
            suggestion: searches == 1 ? suggestionJson() : null,
          );
        case LabApiRoutes.catalogFetch:
          return statusJson('candidates', candidates: <Map<String, dynamic>>[
            <String, dynamic>{
              'catalog_code': 'C1',
              'mpn': 'SAME',
              'package': 'SOT-23-5',
            },
          ]);
        default:
          throw StateError('unexpected path $path');
      }
    };

    final notifier = CatalogNotifier(api: api.client);
    await notifier.refresh();
    await notifier.startFetch();
    expect(notifier.state.fetchStatus, isNotNull);

    await notifier.updateQuery(const CatalogQuery(text: 'C1'));
    expect(notifier.state.fetchStatus, isNull);
    expect(notifier.state.fetchSuggestion, isNull);
  });

  test('the status JSON keeps every terminal state terminal', () {
    for (final state in CatalogFetchStatus.terminalStates) {
      final status = CatalogFetchStatus.fromJson(statusJson(state));
      expect(status.isTerminal, isTrue, reason: state);
      expect(status.isDone, state == 'done', reason: state);
    }
    for (final state in <String>['queued', 'resolving', 'fetching']) {
      expect(CatalogFetchStatus.fromJson(statusJson(state)).isTerminal, isFalse);
    }
  });
}
