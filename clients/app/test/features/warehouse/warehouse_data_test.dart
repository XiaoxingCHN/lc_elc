import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/detail_models.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';

/// The data layer behind 库存速览 / 仓位速览.
///
/// Everything here is contract-shaped: the client must read the SERVER's field
/// names (`bag_count`, `bag_quantity`, `next_cursor`) and must never invent a
/// number the server did not report.
void main() {
  group('LabStockLocation statistics', () {
    test('parses the with_stats columns', () {
      final location = LabStockLocation.fromJson(<String, dynamic>{
        'id': 7,
        'code': 'K000003',
        'name': 'R03',
        'path': 'Lab/R03',
        'usage': 'internal',
        'bag_count': 4,
        'bag_quantity': 250.0,
        'quantity': 240.0,
      });

      expect(location.bagCount, 4);
      expect(location.bagQuantity, 250.0);
      // `quantity` is the stock.quant sum, which differs from the bags' own
      // figures whenever a native Odoo operation touched the stock.
      expect(location.quantity, 240.0);
      expect(location.usage, 'internal');
      expect(location.hasStats, isTrue);
    });

    test('a plain locations() row reports NO statistics, not zeros', () {
      final location = LabStockLocation.fromJson(<String, dynamic>{
        'id': 7,
        'code': 'K000003',
        'name': 'R03',
        'path': 'Lab/R03',
      });

      // Null, not 0: showing "0 袋" for a location the server never counted
      // would tell the operator the shelf is empty.
      expect(location.bagCount, isNull);
      expect(location.bagQuantity, isNull);
      expect(location.quantity, isNull);
      expect(location.hasStats, isFalse);
    });
  });

  group('LabBag from /inventory/bags', () {
    test('reads the live quant figures and the location path', () {
      final bag = LabBag.fromJson(<String, dynamic>{
        'id': 42,
        'trace_code': 'TRC00000042',
        'item_key': 'lcsc:C25804',
        'name': '10k 0603 resistor',
        'location_id': 7,
        'location_code': 'K000003',
        'location_path': 'Lab/R03',
        'quantity': 100.0,
        'available_quantity': 90.0,
        'outstanding_quantity': 10.0,
        'uom': '件',
      });

      expect(bag.traceCode, 'TRC00000042');
      expect(bag.quantity, 100.0);
      expect(bag.availableQuantity, 90.0);
      expect(bag.outstandingQuantity, 10.0);
      expect(bag.locationPath, 'Lab/R03');
      expect(bag.uom, '件');
      expect(bag.hasStock, isTrue);
    });

    test('an empty bag is not "in stock"', () {
      final bag = LabBag.fromJson(<String, dynamic>{
        'id': 43,
        'trace_code': 'TRC00000043',
        'quantity': 0.0,
      });
      expect(bag.hasStock, isFalse);
    });
  });

  group('BagPage', () {
    test('hasMore follows the server cursor', () {
      const withCursor = BagPage(bags: <LabBag>[], nextCursor: '41');
      const done = BagPage(bags: <LabBag>[], nextCursor: null);
      const emptyCursor = BagPage(bags: <LabBag>[], nextCursor: '');

      expect(withCursor.hasMore, isTrue);
      expect(done.hasMore, isFalse);
      expect(emptyCursor.hasMore, isFalse,
          reason: 'an empty cursor must not trigger another request');
    });
  });

  group('LabApiClient.bags', () {
    late List<Map<String, dynamic>> calls;

    LabApiClient client({Map<String, dynamic>? response}) {
      calls = <Map<String, dynamic>>[];
      return LabApiClient(
        call: (path, params) async {
          calls.add(<String, dynamic>{'path': path, 'params': params});
          return response ??
              <String, dynamic>{
                'bags': <dynamic>[
                  <String, dynamic>{'id': 1, 'trace_code': 'TRC1', 'quantity': 5.0},
                ],
                'next_cursor': '1',
              };
        },
      );
    }

    test('sends the location filter and parses the page', () async {
      final api = client();
      final page = await api.bags(locationId: 7);

      expect(calls.single['path'], '/lab/api/inventory/bags');
      final params = calls.single['params'] as Map<String, dynamic>;
      expect(params['location_id'], 7);
      expect(params['has_stock'], isTrue);
      expect(params['outstanding_only'], isFalse);
      expect(page.bags.single.traceCode, 'TRC1');
      expect(page.nextCursor, '1');
      expect(page.hasMore, isTrue);
    });

    test('clamps the page size to the server ceiling of 100', () async {
      final api = client();
      await api.bags(locationId: 7, limit: 500);
      expect(
        (calls.single['params'] as Map<String, dynamic>)['limit'],
        100,
        reason: 'the bags endpoint clamps at 100, lower than maxPageSize 200',
      );

      await api.bags(locationId: 7, limit: 0);
      expect((calls.last['params'] as Map<String, dynamic>)['limit'], 1);
    });

    test('omits blank filters instead of sending empty strings', () async {
      final api = client();
      await api.bags(query: '   ', itemKey: '', locationId: null);
      final params = calls.single['params'] as Map<String, dynamic>;
      expect(params.containsKey('query'), isFalse);
      expect(params.containsKey('item_key'), isFalse);
      expect(params.containsKey('location_id'), isFalse);
      expect(params.containsKey('cursor'), isFalse);
    });

    test('passes the cursor through for the next page', () async {
      final api = client();
      await api.bags(locationId: 7, cursor: '1');
      expect((calls.single['params'] as Map<String, dynamic>)['cursor'], '1');
    });

    test('an empty answer is an empty page, not a throw', () async {
      final api = client(response: <String, dynamic>{});
      final page = await api.bags(locationId: 7);
      expect(page.bags, isEmpty);
      expect(page.hasMore, isFalse);
    });
  });

  group('LabApiClient.locations with_stats', () {
    test('sends with_stats only when asked', () async {
      final sent = <Map<String, dynamic>>[];
      final api = LabApiClient(
        call: (path, params) async {
          sent.add(params);
          return <String, dynamic>{'locations': <dynamic>[]};
        },
      );

      await api.locations();
      expect(sent.last.containsKey('with_stats'), isFalse,
          reason: 'the pickers must not pay for the aggregate query');

      await api.locations(withStats: true);
      expect(sent.last['with_stats'], isTrue);
    });
  });
}
