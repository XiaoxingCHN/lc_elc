import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/detail_models.dart';
import 'package:lab_inventory_client/features/unified/models/inventory.dart';
import 'package:lab_inventory_client/features/unified/providers/inventory_providers.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';
import 'package:lab_inventory_client/models/lab_api_exception.dart';

import 'support/fake_lab_api.dart';

/// 领料 / 归还 (issue / return) rules.
///
/// The user's final decision is enforced here: the borrower is a SYSTEM ACCOUNT
/// chosen from `bootstrap.borrowers`, an ordinary operator may only issue to
/// their own account, the actor is never sent by the client, an issue cannot
/// exceed a bag, and a return cannot exceed the original line's outstanding
/// quantity.
void main() {
  late FakeLabApi api;
  late List<String> revisions;
  late List<String> keys;

  setUp(() {
    api = FakeLabApi();
    revisions = <String>[];
    keys = <String>['key-1', 'key-2', 'key-3'];
  });

  String nextKey() => keys.removeAt(0);

  group('borrower selection', () {
    InventoryBootstrap bootstrapWith({
      required bool canIssueForOthers,
      List<Map<String, dynamic>> borrowers = const <Map<String, dynamic>>[],
    }) {
      return InventoryBootstrap.fromJson(<String, dynamic>{
        'borrowers': borrowers,
        'permissions': <String, dynamic>{
          if (canIssueForOthers) 'can_issue_for_others': true,
          'uid': 7,
        },
      });
    }

    test('an ordinary operator may only issue to their own account', () {
      final bootstrap = bootstrapWith(
        canIssueForOthers: false,
        borrowers: <Map<String, dynamic>>[
          <String, dynamic>{'id': 7, 'name': '小王', 'login': 'wang'},
          <String, dynamic>{'id': 8, 'name': '小李', 'login': 'li'},
        ],
      );

      final selectable = bootstrap.selectableBorrowers(currentUid: 7);
      expect(selectable.map((borrower) => borrower.id), <int>[7]);
      expect(bootstrap.selfBorrower(currentUid: 7)?.id, 7);
    });

    test('an inventory manager may issue for others, from the server list', () {
      final bootstrap = bootstrapWith(
        canIssueForOthers: true,
        borrowers: <Map<String, dynamic>>[
          <String, dynamic>{'id': 7, 'name': '小王'},
          <String, dynamic>{'id': 8, 'name': '小李'},
        ],
      );

      expect(bootstrap.selectableBorrowers(currentUid: 7).length, 2);
    });

    test('a missing permission flag is treated as "no proxy issue" (safe default)', () {
      final bootstrap = InventoryBootstrap.fromJson(<String, dynamic>{
        'borrowers': <Map<String, dynamic>>[
          <String, dynamic>{'id': 7, 'name': '小王'},
          <String, dynamic>{'id': 8, 'name': '小李'},
        ],
        'permissions': <String, dynamic>{},
      });

      expect(bootstrap.permissions.known, isFalse);
      expect(bootstrap.canIssueForOthers, isFalse);
      expect(bootstrap.selectableBorrowers(currentUid: 7).map((b) => b.id), <int>[7]);
    });

    test('no self account and no proxy right means no selectable borrower', () {
      final bootstrap = bootstrapWith(
        canIssueForOthers: false,
        borrowers: <Map<String, dynamic>>[
          <String, dynamic>{'id': 8, 'name': '小李'},
        ],
      );

      expect(bootstrap.selfBorrower(currentUid: 7), isNull);
      expect(bootstrap.selectableBorrowers(currentUid: 7), isEmpty);
    });
  });

  group('issue', () {
    IssueController buildIssueController() => IssueController(
          api: api.client,
          newRequestKey: nextKey,
          onInventoryChanged: revisions.add,
        );

    LabBag bag({int id = 11, double quantity = 10}) => LabBag.fromJson(
          <String, dynamic>{
            'id': id,
            'trace_code': 'TRACE-$id',
            'quantity': quantity,
            'location_code': 'K000001',
          },
        );

    test('a borrower is required: no borrower means no server call', () async {
      final controller = buildIssueController();
      controller.setItem(itemKey: 'lcsc:C1');
      controller.addBag(bag());
      controller.updateQuantity(11, '5');
      controller.setProject('项目A');

      expect(await controller.submit(), isFalse);
      expect(controller.state.error, contains('领用人'));
      expect(api.calls, isEmpty);
    });

    test('a project is required', () async {
      final controller = buildIssueController();
      controller.addBag(bag());
      controller.updateQuantity(11, '5');
      controller.setBorrower(7);

      expect(await controller.submit(), isFalse);
      expect(controller.state.error, contains('项目'));
      expect(api.calls, isEmpty);
    });

    test('a quantity above the bag content is refused before the request', () async {
      final controller = buildIssueController();
      controller.addBag(bag(quantity: 4));
      controller.updateQuantity(11, '5');
      controller.setBorrower(7);
      controller.setProject('项目A');

      expect(await controller.submit(), isFalse);
      expect(controller.state.error, contains('只有'));
      expect(api.calls, isEmpty);
    });

    test('a valid issue sends borrower, project and one line per bag', () async {
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.inventoryIssue: <String, dynamic>{'inventory_revision': 'rev-5'},
      });

      final controller = buildIssueController();
      controller.setItem(itemKey: 'lcsc:C1', itemName: '10uF');
      controller.addBag(bag(id: 11, quantity: 10));
      controller.addBag(bag(id: 12, quantity: 2));
      controller.updateQuantity(11, '4');
      controller.updateQuantity(12, '2');
      controller.setBorrower(7);
      controller.setProject('项目A');

      expect(await controller.submit(), isTrue);
      expect(controller.state.succeeded, isTrue);
      expect(revisions, <String>['rev-5']);

      final params = api.onlyParams(LabApiRoutes.inventoryIssue);
      expect(params['borrower_id'], 7);
      expect(params['project'], '项目A');
      expect(params['request_key'], 'key-1');
      expect(params['lines'], <Map<String, dynamic>>[
        <String, dynamic>{'bag_id': 11, 'quantity': 4.0},
        <String, dynamic>{'bag_id': 12, 'quantity': 2.0},
      ]);
      // The client never claims to BE the borrower or the actor.
      expect(params.containsKey('actor'), isFalse);
      expect(params.containsKey('actor_id'), isFalse);
    });

    test('a failed issue keeps the same key and the chosen lines', () async {
      var failFirst = true;
      api.onCall = (path, params) async {
        if (failFirst) {
          failFirst = false;
          throw businessFailure('NETWORK_ERROR', '无法连接服务器，请检查网络后重试。');
        }
        return <String, dynamic>{'inventory_revision': 'rev-6'};
      };

      final controller = buildIssueController();
      controller.addBag(bag());
      controller.updateQuantity(11, '3');
      controller.setBorrower(7);
      controller.setProject('项目A');

      expect(await controller.submit(), isFalse);
      expect(controller.state.requestKey, 'key-1');
      expect(controller.state.lines.single.quantityText, '3');
      expect(controller.state.borrowerId, 7);
      expect(controller.state.project, '项目A');

      expect(await controller.submit(), isTrue);
      final calls = api.callsFor(LabApiRoutes.inventoryIssue);
      expect(calls[0].params['request_key'], calls[1].params['request_key']);
    });

    test('the same bag cannot be added twice', () {
      final controller = buildIssueController();
      controller.addBag(bag());
      controller.addBag(bag());
      expect(controller.state.lines.length, 1);
    });
  });

  group('return', () {
    ReturnController buildReturnController() => ReturnController(
          api: api.client,
          newRequestKey: nextKey,
          onInventoryChanged: revisions.add,
        );

    test('loads the flat issue payload and exposes the outstanding quantity',
        () async {
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.inventoryIssues: <String, dynamic>{
          'issues': <Map<String, dynamic>>[
            <String, dynamic>{
              'issue_line_id': 21,
              'bag_id': 11,
              'trace_code': 'TRACE-11',
              'outstanding_quantity': 4,
              'quantity': 10,
              'returned_quantity': 6,
              'borrower_id': 7,
              'project': '项目A',
            },
          ],
        },
      });

      final controller = buildReturnController();
      await controller.loadIssues();

      expect(controller.state.issuesError, isNull);
      final issue = controller.state.issues.single;
      expect(issue.lines.single.id, 21);
      expect(issue.lines.single.outstanding, 4);
      expect(api.onlyParams(LabApiRoutes.inventoryIssues)['outstanding_only'], true);
    });

    test('a quantity above the outstanding balance is refused before the request',
        () async {
      final controller = buildReturnController();
      controller.selectLine(
        IssueLineRecord.fromJson(<String, dynamic>{
          'issue_line_id': 21,
          'bag_id': 11,
          'outstanding_quantity': 4,
        }),
      );
      controller.setQuantity('5');

      expect(await controller.submit(), isFalse);
      expect(controller.state.error, contains('不能超过尚未归还数量'));
      expect(api.countFor(LabApiRoutes.inventoryReturn), 0);
    });

    test('a valid return targets the original issue line and reports the remainder',
        () async {
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.inventoryReturn: <String, dynamic>{
          'outstanding_quantity': 2,
          'inventory_revision': 'rev-7',
        },
        LabApiRoutes.inventoryIssues: <String, dynamic>{'issues': <dynamic>[]},
      });

      final controller = buildReturnController();
      controller.selectLine(
        IssueLineRecord.fromJson(<String, dynamic>{
          'issue_line_id': 21,
          'bag_id': 11,
          'trace_code': 'TRACE-11',
          'outstanding_quantity': 4,
        }),
      );
      controller.setQuantity('2');

      expect(await controller.submit(), isTrue);
      expect(controller.state.notice, contains('尚未归还 2'));
      expect(revisions, contains('rev-7'));

      final params = api.onlyParams(LabApiRoutes.inventoryReturn);
      expect(params['issue_line_id'], 21);
      expect(params['quantity'], 2.0);
      expect(params['request_key'], 'key-1');
    });

    test('a failed return keeps the same key for the retry', () async {
      api.onCall = (path, params) async {
        throw businessFailure('NETWORK_ERROR', '无法连接服务器。');
      };

      final controller = buildReturnController();
      controller.selectLine(
        IssueLineRecord.fromJson(<String, dynamic>{
          'issue_line_id': 21,
          'outstanding_quantity': 4,
        }),
      );
      controller.setQuantity('2');

      await controller.submit();
      await controller.submit();

      final calls = api.callsFor(LabApiRoutes.inventoryReturn);
      expect(calls.length, 2);
      expect(calls[0].params['request_key'], calls[1].params['request_key']);
      expect(controller.state.quantityText, '2',
          reason: 'a failure must not clear the quantity');
    });

    test('an issue-list failure is reported, not shown as "nothing to return"',
        () async {
      api.onCall = (path, params) async =>
          throw businessFailure('ACCESS_DENIED', '当前账号没有查看领料记录的权限。');

      final controller = buildReturnController();
      await controller.loadIssues();

      expect(controller.state.issues, isEmpty);
      expect(controller.state.issuesError, '当前账号没有查看领料记录的权限。');
      expect(controller.state.loadingIssues, isFalse);
    });
  });

  test('describeLabError surfaces the server Chinese message verbatim', () {
    expect(
      describeLabError(
        const LabApiException(code: 'X', message: '数量必须是正数。'),
      ),
      '数量必须是正数。',
    );
  });
}
