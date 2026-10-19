import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/catalog_query.dart';
import 'package:lab_inventory_client/features/unified/models/labels.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';
import 'package:lab_inventory_client/models/lab_api_exception.dart';

import 'support/fake_lab_api.dart';

/// Payload + parsing tests for `lib/services/lab_api_client.dart`.
///
/// Every assertion here is about what this client SENDS and how it reads what
/// comes back - the two places where a mismatch with the server contract would
/// silently corrupt business data.
void main() {
  group('catalog search payload', () {
    test('sends the contract parameter names, not client-side filters', () async {
      final api = FakeLabApi();
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.catalogSearch: <String, dynamic>{
          'items': <Map<String, dynamic>>[],
          'next_cursor': null,
          'total': 0,
          'inventory_revision': 'r1',
          'catalog_revision': 'c1',
        },
      });

      final query = CatalogQuery(
        text: 'C123',
        categoryId: 312,
        brands: <String>{'VISHAY', 'TI'},
        packages: <String>{'0805'},
        parameters: <String, Set<String>>{
          'param_11032_n': <String>{'10uF'},
          'param_2_v': <String>{'10V', '16V'},
        },
        stockOnly: true,
      );

      await api.client.search(query, cursor: 'CURSOR-1', limit: 25);

      final params = api.onlyParams(LabApiRoutes.catalogSearch);
      expect(params['query'], 'C123');
      expect(params['category_id'], 312);
      expect(params['stock_only'], true);
      expect(params['cursor'], 'CURSOR-1');
      expect(params['limit'], 25);
      expect((params['brands'] as List<dynamic>).toSet(), <String>{'VISHAY', 'TI'});
      expect(params['packages'], <String>['0805']);
      // One selected value is a string, several are a list.
      expect(params['parameters'], <String, dynamic>{
        'param_11032_n': '10uF',
        'param_2_v': <String>['10V', '16V'],
      });
    });

    test('clamps the page size to the contract maximum and drops nulls', () async {
      final api = FakeLabApi();
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.catalogSearch: <String, dynamic>{'items': <dynamic>[]},
      });

      await api.client.search(const CatalogQuery(), limit: 5000);
      final params = api.onlyParams(LabApiRoutes.catalogSearch);
      expect(params['limit'], LabApiClient.maxPageSize);
      expect(params.containsKey('cursor'), isFalse,
          reason: 'a null cursor must not be serialized');
      expect(params.containsKey('category_id'), isFalse);
    });

    test('reads the unified row, keeping mall stock separate from lab stock', () async {
      final api = FakeLabApi();
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.catalogSearch: <String, dynamic>{
          'items': <Map<String, dynamic>>[
            itemJson(
              itemKey: 'lcsc:C123',
              catalogCode: 'C123',
              labQuantity: 120,
              catalogStock: 999999,
              labTemplateIds: <int>[42],
              snCodes: <String>['LAB-000001'],
              parameters: <Map<String, dynamic>>[
                <String, dynamic>{'code': 'param_1', 'name': '容值', 'value': '10uF'},
              ],
            ),
          ],
          'next_cursor': 'NEXT',
          'total': 662768,
          'inventory_revision': 'rev-9',
        },
      });

      final page = await api.client.search(const CatalogQuery());
      final item = page.items.single;
      expect(item.itemKey, 'lcsc:C123');
      expect(item.labQuantity, 120);
      expect(item.catalogStock, 999999);
      expect(item.hasStock, isTrue);
      expect(item.labTemplateIds, <int>[42]);
      expect(item.snCodes, <String>['LAB-000001']);
      expect(item.parameters.single.value, '10uF');
      expect(page.nextCursor, 'NEXT');
      expect(page.total, 662768);
      expect(page.hasMore, isTrue);
      expect(page.inventoryRevision, 'rev-9');
      // Mall stock never leaks into the lab quantity.
      expect(item.labQuantity == item.catalogStock, isFalse);
    });
  });

  group('categories use the POSTGRES tree id', () {
    test('id/category_id are preferred; the mall catalog_id is reference only', () async {
      final api = FakeLabApi();
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.catalogCategories: <String, dynamic>{
          'categories': <Map<String, dynamic>>[
            <String, dynamic>{
              'id': 312,
              'catalog_id': 998877,
              'name': '电容',
              'parent_id': 1,
            },
            <String, dynamic>{
              'category_id': 313,
              'catalog_id': 55,
              'name': '钽电容',
              'parent_id': 312,
            },
          ],
        },
      });

      final categories = await api.client.categories();
      expect(categories.length, 1);
      expect(categories.single.id, 312);
      expect(categories.single.catalogId, 998877);
      expect(categories.single.children.single.id, 313);
      expect(categories.single.children.single.catalogId, 55);
    });
  });

  group('issues accept the flat workflow payload', () {
    test('flattens line-level rows and groups them by issue_id', () async {
      final api = FakeLabApi();
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.inventoryIssues: <String, dynamic>{
          'issues': <Map<String, dynamic>>[
            <String, dynamic>{
              'issue_line_id': 5,
              'bag_id': 11,
              'outstanding_quantity': 4,
              'borrower_id': 42,
              'project': '项目A',
              'trace_code': 'TRACE-11',
              'returned_quantity': 6,
              'quantity': 10,
            },
            <String, dynamic>{
              'issue_line_id': 7,
              'issue_id': 9,
              'bag_id': 12,
              'outstanding_quantity': 3,
              'borrower_id': 42,
              'project': '项目A',
              'trace_code': 'TRACE-12',
            },
          ],
        },
      });

      final page = await api.client.issues();
      // Row 1 stands alone; rows 2+3 would be grouped if they shared issue_id.
      expect(page.issues.length, 2);

      final standalone = page.issues.first;
      expect(standalone.lines.single.id, 5, reason: 'must use issue_line_id');
      expect(standalone.lines.single.bagId, 11);
      expect(standalone.lines.single.outstanding, 4);
      expect(standalone.borrowerId, 42);
      expect(standalone.outstanding, 4);

      // The return endpoint needs issue_line_id, so it must never be replaced by
      // a generic `id`.
      expect(page.issues[1].lines.single.id, 7);
    });

    test('still understands a nested {issue, lines:[...]} payload', () async {
      final api = FakeLabApi();
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.inventoryIssues: <String, dynamic>{
          'issues': <Map<String, dynamic>>[
            <String, dynamic>{
              'issue_id': 3,
              'project': '项目B',
              'borrower': <dynamic>[42, '张三'],
              'outstanding_quantity': 9,
              'lines': <Map<String, dynamic>>[
                <String, dynamic>{'issue_line_id': 21, 'bag_id': 31, 'outstanding_quantity': 9},
              ],
            },
          ],
        },
      });

      final page = await api.client.issues();
      final issue = page.issues.single;
      expect(issue.id, 3);
      expect(issue.project, '项目B');
      expect(issue.borrowerId, 42);
      expect(issue.borrowerName, '张三');
      expect(issue.lines.single.id, 21);
    });
  });

  group('write payloads', () {
    test('receipt / issue / return carry exactly the contract keys', () async {
      final api = FakeLabApi();
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.inventoryReceipt: <String, dynamic>{
          'item_key': 'lcsc:C1',
          'lab_quantity': 100,
          'inventory_revision': 'r2',
        },
        LabApiRoutes.inventoryIssue: <String, dynamic>{'inventory_revision': 'r3'},
        LabApiRoutes.inventoryReturn: <String, dynamic>{
          'outstanding_quantity': 5,
          'inventory_revision': 'r4',
        },
      });

      await api.client.receipt(
        requestKey: 'KEY-1',
        itemKey: 'lcsc:C1',
        locationId: 7,
        quantity: 100,
        supplierQr: 'LABB:T1',
        note: 'n',
      );
      expect(api.onlyParams(LabApiRoutes.inventoryReceipt), <String, dynamic>{
        'request_key': 'KEY-1',
        'item_key': 'lcsc:C1',
        'location_id': 7,
        'quantity': 100.0,
        'supplier_qr': 'LABB:T1',
        'note': 'n',
      });

      await api.client.issue(
        requestKey: 'KEY-2',
        borrowerId: 42,
        project: '项目A',
        lines: <({int bagId, double quantity})>[
          (bagId: 11, quantity: 5),
          (bagId: 12, quantity: 2.5),
        ],
        note: '',
      );
      expect(api.onlyParams(LabApiRoutes.inventoryIssue), <String, dynamic>{
        'request_key': 'KEY-2',
        'borrower_id': 42,
        'project': '项目A',
        'lines': <Map<String, dynamic>>[
          <String, dynamic>{'bag_id': 11, 'quantity': 5.0},
          <String, dynamic>{'bag_id': 12, 'quantity': 2.5},
        ],
        'note': '',
      });
      // The ACTOR is never sent: the server records it from the session.
      expect(
        api.onlyParams(LabApiRoutes.inventoryIssue).containsKey('actor'),
        isFalse,
      );

      await api.client.returnQuantity(
        requestKey: 'KEY-3',
        issueLineId: 21,
        quantity: 4,
      );
      expect(api.onlyParams(LabApiRoutes.inventoryReturn), <String, dynamic>{
        'request_key': 'KEY-3',
        'issue_line_id': 21,
        'quantity': 4.0,
        'note': '',
      });
    });

    test('labels preview payload uses millimetres and never adds a QR field', () async {
      final api = FakeLabApi();
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.labelsPreview: <String, dynamic>{
          'pdf_base64': 'JVBERi0xLjQK',
          'filename': 'labels.pdf',
          'page_count': 1,
          'label_count': 2,
        },
      });

      await api.client.previewLabels(
        const LabelSpec(
          kind: LabelKind.bag,
          ids: <int>[1, 2],
          copies: 1,
          widthMm: 50,
          heightMm: 30,
          marginMm: 10,
          gapMm: 2,
          fields: <String>['sn', 'qr', 'catalog_code'],
        ),
      );

      final params = api.onlyParams(LabApiRoutes.labelsPreview);
      expect(params['kind'], 'bag');
      expect(params['ids'], <int>[1, 2]);
      expect(params['width_mm'], 50.0);
      expect(params['height_mm'], 30.0);
      expect(params['margin_mm'], 10.0);
      expect(params['gap_mm'], 2.0);
      // 'qr' is stripped on the wire as well as in validation: exactly one code.
      expect(params['fields'], <String>['sn', 'catalog_code']);
    });

    test('resolve_code sends the raw scanned payload', () async {
      final api = FakeLabApi();
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.inventoryResolveCode: <String, dynamic>{
          'kind': 'bag',
          'item_key': 'lcsc:C9',
          'bag': <String, dynamic>{'id': 3, 'trace_code': 'T3', 'quantity': 5},
          'location': <String, dynamic>{'id': 4, 'code': 'K000001', 'name': 'R01'},
        },
      });

      final resolved = await api.client.resolveCode('  LABB:T3 \n');
      expect(api.onlyParams(LabApiRoutes.inventoryResolveCode)['raw'], 'LABB:T3');
      expect(resolved.isBag, isTrue);
      expect(resolved.itemKey, 'lcsc:C9');
      expect(resolved.impliedLocationId, 4);
      expect(resolved.supplierQr, 'LABB:T3');
    });

    test('an empty code is refused before any request leaves the client', () async {
      final api = FakeLabApi();
      await expectLater(
        api.client.resolveCode('   '),
        throwsA(isA<LabApiException>()),
      );
      expect(api.calls, isEmpty);
    });
  });

  group('errors', () {
    test('a business failure propagates with the server message and code', () async {
      final api = FakeLabApi();
      api.onCall = (path, params) async {
        throw businessFailure('VALIDATION_ERROR', '数量必须大于 0。');
      };

      await expectLater(
        api.client.receipt(
          requestKey: 'K',
          itemKey: 'lcsc:C1',
          locationId: 1,
          quantity: 0,
        ),
        throwsA(
          isA<LabApiException>()
              .having((error) => error.code, 'code', 'VALIDATION_ERROR')
              .having((error) => error.message, 'message', '数量必须大于 0。'),
        ),
      );
    });

    test('a session failure stays a session failure', () async {
      final api = FakeLabApi();
      api.onCall = (path, params) async =>
          throw const LabSessionExpiredException();

      await expectLater(
        api.client.search(const CatalogQuery()),
        throwsA(isA<LabSessionExpiredException>()),
      );
    });
  });
}
