import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/detail_models.dart';
import 'package:lab_inventory_client/features/unified/providers/inventory_providers.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';
import 'package:lab_inventory_client/models/lab_api_exception.dart';

import 'support/fake_lab_api.dart';

/// 入库 (receipt) flow.
///
/// The rules pinned here are the ones acceptance scenario 2 and 5 depend on:
/// stock changes only on an explicit confirmation, the idempotency key survives a
/// failure so a retry cannot create a second bag, a failure never clears what the
/// operator typed, and success refreshes the list/detail/history through the
/// revision signal.
void main() {
  late FakeLabApi api;
  late List<String> revisions;
  late List<String> keys;

  String nextKey() => keys.removeAt(0);

  ReceiptController buildController() => ReceiptController(
        api: api.client,
        newRequestKey: nextKey,
        onInventoryChanged: revisions.add,
      );

  setUp(() {
    api = FakeLabApi();
    revisions = <String>[];
    keys = <String>['key-1', 'key-2', 'key-3'];
  });

  test('an unreadable code produces an actionable message and keeps the input',
      () async {
    api.onCall = (path, params) async {
      throw businessFailure(
        'UNRESOLVED_CODE',
        '无法识别该编码，请确认是否为追溯袋码或库位码。',
      );
    };

    final controller = buildController();
    controller.setInput('XYZ-123');
    await controller.resolve();

    expect(controller.state.error, '无法识别该编码，请确认是否为追溯袋码或库位码。');
    expect(controller.state.input, 'XYZ-123',
        reason: 'the operator must be able to correct the code');
    expect(controller.state.resolving, isFalse);
  });

  test('resolving a bag fills the item and the implied location, and resolves nothing into stock',
      () async {
    api.answerWith(<String, Map<String, dynamic>>{
      LabApiRoutes.inventoryResolveCode: <String, dynamic>{
        'kind': 'bag',
        'item_key': 'lcsc:C9',
        'bag': <String, dynamic>{
          'id': 3,
          'trace_code': 'TRACE-3',
          'quantity': 50,
          'location_id': 4,
        },
        'location': <String, dynamic>{'id': 4, 'code': 'K000001', 'name': 'R01'},
      },
    });

    final controller = buildController();
    controller.setInput('LABB:TRACE-3');
    await controller.resolve();

    expect(controller.state.itemKey, 'lcsc:C9');
    expect(controller.state.locationId, 4);
    expect(controller.state.supplierQr, 'LABB:TRACE-3');
    expect(controller.state.notice, isNotNull);
    // No stock write happened: only resolve_code was called.
    expect(api.countFor(LabApiRoutes.inventoryReceipt), 0);
  });

  test('submit refuses an incomplete form without calling the server', () async {
    final controller = buildController();
    controller.setQuantity('0');

    final ok = await controller.submit();

    expect(ok, isFalse);
    expect(controller.state.error, contains('器件'));
    expect(api.calls, isEmpty);
  });

  test('a successful receipt rotates the key, reports the server quantity and bumps the revision',
      () async {
    api.answerWith(<String, Map<String, dynamic>>{
      LabApiRoutes.inventoryReceipt: <String, dynamic>{
        'item_key': 'lcsc:C1',
        'lab_quantity': 110,
        'inventory_revision': 'rev-2',
        'bag': <String, dynamic>{'id': 8, 'trace_code': 'T8'},
      },
    });

    final controller = buildController();
    controller.setItem(itemKey: 'lcsc:C1', itemName: '10uF');
    controller.setLocation(3, label: 'R01');
    controller.setQuantity('10');
    final ok = await controller.submit();

    expect(ok, isTrue);
    expect(controller.state.succeeded, isTrue);
    expect(controller.state.notice, contains('110'));
    expect(controller.state.requestKey, 'key-2',
        reason: 'a fresh submission gets a fresh key');
    expect(revisions, <String>['rev-2'],
        reason: 'the list/detail/history must refresh');

    final params = api.onlyParams(LabApiRoutes.inventoryReceipt);
    expect(params['request_key'], 'key-1');
    expect(params['item_key'], 'lcsc:C1');
    expect(params['location_id'], 3);
    expect(params['quantity'], 10.0);
  });

  test('a failed receipt keeps the SAME key and every typed value, so 重试 is idempotent',
      () async {
    var failFirst = true;
    api.onCall = (path, params) async {
      if (failFirst) {
        failFirst = false;
        throw businessFailure('NETWORK_ERROR', '无法连接服务器，请检查网络后重试。');
      }
      return <String, dynamic>{
        'item_key': 'lcsc:C1',
        'lab_quantity': 110,
        'inventory_revision': 'rev-3',
      };
    };

    final controller = buildController();
    controller.setItem(itemKey: 'lcsc:C1', itemName: '10uF');
    controller.setLocation(3, label: 'R01');
    controller.setQuantity('10');

    expect(await controller.submit(), isFalse);
    final failed = controller.state;
    expect(failed.error, '无法连接服务器，请检查网络后重试。');
    expect(failed.requestKey, 'key-1', reason: 'the key must survive the failure');
    expect(failed.itemKey, 'lcsc:C1');
    expect(failed.locationId, 3);
    expect(failed.quantityText, '10');

    // The operator presses 重试 without changing anything.
    expect(await controller.submit(), isTrue);

    final first = api.callsFor(LabApiRoutes.inventoryReceipt)[0].params;
    final second = api.callsFor(LabApiRoutes.inventoryReceipt)[1].params;
    expect(first['request_key'], second['request_key'],
        reason: 'a retry of the same submission must reuse the idempotency key');
  });

  test('a catalog row without a local archive is created and the receipt retried',
      () async {
    var receiptCalls = 0;
    api.onCall = (path, params) async {
      if (path == LabApiRoutes.catalogCreateMaterial) {
        return <String, dynamic>{
          'product_template_id': 42,
          'product_id': 55,
          'sn': 'LAB-000001',
          'item_key': 'lcsc:C1',
        };
      }
      if (path == LabApiRoutes.inventoryReceipt) {
        receiptCalls++;
        if (receiptCalls == 1) {
          throw businessFailure('MATERIAL_NOT_FOUND', '该器件还没有本地物料档案。');
        }
        return <String, dynamic>{
          'item_key': 'lcsc:C1',
          'lab_quantity': 10,
          'inventory_revision': 'rev-4',
        };
      }
      throw StateError('unexpected $path');
    };

    final controller = buildController();
    controller.setItem(itemKey: 'lcsc:C1');
    controller.setLocation(3, label: 'R01');
    controller.setQuantity('10');

    final ok = await controller.submit();

    expect(ok, isTrue, reason: 'a first receipt must not fail with "material missing"');
    expect(api.countFor(LabApiRoutes.catalogCreateMaterial), 1);
    expect(api.countFor(LabApiRoutes.inventoryReceipt), 2);
    expect(controller.state.notice, contains('LAB-000001'));
    expect(
      api.callsFor(LabApiRoutes.inventoryReceipt)[0].params['request_key'],
      api.callsFor(LabApiRoutes.inventoryReceipt)[1].params['request_key'],
      reason: 'the retry after auto-creation keeps the same submission key',
    );
  });

  test('a validation failure does not trigger the auto-create branch', () async {
    api.onCall = (path, params) async {
      if (path == LabApiRoutes.catalogCreateMaterial) {
        throw StateError('create_material must not be called for a validation error');
      }
      throw businessFailure('VALIDATION_ERROR', '数量必须大于 0。');
    };

    final controller = buildController();
    controller.setItem(itemKey: 'lcsc:C1');
    controller.setLocation(3, label: 'R01');
    controller.setQuantity('5');

    expect(await controller.submit(), isFalse);
    expect(controller.state.error, '数量必须大于 0。');
    expect(api.countFor(LabApiRoutes.catalogCreateMaterial), 0);
  });

  test('a session failure is surfaced, not swallowed', () async {
    api.onCall = (path, params) async =>
        throw const LabSessionExpiredException();

    final controller = buildController();
    controller.setItem(itemKey: 'lcsc:C1');
    controller.setLocation(3, label: 'R01');
    controller.setQuantity('5');

    expect(await controller.submit(), isFalse);
    expect(controller.state.errorCode, 'SESSION_INVALID');
  });

  test('reset starts a brand-new submission key', () {
    final controller = buildController();
    final before = controller.state.requestKey;
    controller.setQuantity('5');
    controller.reset();

    expect(controller.state.quantityText, isEmpty);
    expect(controller.state.requestKey, isNot(before),
        reason: 'the next submission must not reuse the previous idempotency key');
  });

  group('SN / local archive binding', () {
    LabMaterial material({int id = 42, String sn = 'LAB-000001', String name = ''}) {
      return LabMaterial.fromJson(<String, dynamic>{
        'product_template_id': id,
        'sn': sn,
        'name': name,
      });
    }

    test('a scan of an SN keeps THAT archive instead of taking the first', () async {
      api.onCall = (path, params) async {
        if (path == LabApiRoutes.inventoryResolveCode) {
          return <String, dynamic>{
            'kind': 'bag',
            'item_key': 'lcsc:C1',
            'product_template_id': 43,
            'sn': 'LAB-000043',
            'bag': <String, dynamic>{
              'id': 5,
              'trace_code': 'T5',
              'product_template_id': 43,
              'sn': 'LAB-000043',
            },
            'materials': <Map<String, dynamic>>[
              <String, dynamic>{'product_template_id': 42, 'sn': 'LAB-000001'},
              <String, dynamic>{'product_template_id': 43, 'sn': 'LAB-000043'},
            ],
          };
        }
        return <String, dynamic>{
          'item_key': 'lcsc:C1',
          'lab_quantity': 10,
          'inventory_revision': 'rev-8',
        };
      };

      final controller = buildController();
      controller.setInput('LABB:T5');
      await controller.resolve();

      expect(controller.state.templateId, 43);
      expect(controller.state.sn, 'LAB-000043');
      expect(controller.state.needsTemplateChoice, isFalse,
          reason: 'the scan already named the archive');

      controller.setLocation(3, label: 'R01');
      controller.setQuantity('5');
      expect(await controller.submit(), isTrue);

      final params = api.onlyParams(LabApiRoutes.inventoryReceipt);
      expect(params['product_template_id'], 43,
          reason: 'the scanned SN archive must be the one bound');
    });

    test('several archives with no choice are refused locally, nothing is sent',
        () async {
      final controller = buildController();
      controller.setItem(itemKey: 'lcsc:C1');
      controller.setMaterials(<LabMaterial>[
        material(id: 42, sn: 'LAB-A'),
        material(id: 43, sn: 'LAB-B'),
      ]);
      controller.setLocation(3, label: 'R01');
      controller.setQuantity('5');

      expect(controller.state.templateId, isNull,
          reason: 'the first archive must never be auto-picked');
      expect(controller.state.needsTemplateChoice, isTrue);

      expect(await controller.submit(), isFalse);
      expect(controller.state.error, contains('本地档案'));
      expect(api.calls, isEmpty);
    });

    test('a single archive is selected automatically', () async {
      api.answerWith(<String, Map<String, dynamic>>{
        LabApiRoutes.inventoryReceipt: <String, dynamic>{
          'item_key': 'lcsc:C1',
          'lab_quantity': 5,
          'inventory_revision': 'rev-9',
        },
      });

      final controller = buildController();
      controller.setItem(itemKey: 'lcsc:C1');
      controller.setMaterials(<LabMaterial>[material(id: 42, sn: 'LAB-ONLY')]);
      controller.setLocation(3, label: 'R01');
      controller.setQuantity('5');

      expect(controller.state.templateId, 42);
      expect(await controller.submit(), isTrue);
      expect(api.onlyParams(LabApiRoutes.inventoryReceipt)['product_template_id'], 42);
    });

    test('a server AMBIGUOUS_MATERIAL surfaces the candidates and keeps the key',
        () async {
      var attempt = 0;
      api.onCall = (path, params) async {
        attempt++;
        if (attempt == 1) {
          throw LabApiException(
            code: 'AMBIGUOUS_MATERIAL',
            message: '该编号对应多个本地档案，请指定要入库的档案。',
            fields: <String, dynamic>{
              'candidates': <Map<String, dynamic>>[
                <String, dynamic>{'product_template_id': 42, 'sn': 'LAB-A'},
                <String, dynamic>{'product_template_id': 43, 'sn': 'LAB-B'},
              ],
            },
          );
        }
        return <String, dynamic>{
          'item_key': 'lcsc:C1',
          'lab_quantity': 5,
          'inventory_revision': 'rev-10',
        };
      };

      final controller = buildController();
      controller.setItem(itemKey: 'lcsc:C1');
      controller.setLocation(3, label: 'R01');
      controller.setQuantity('5');

      expect(await controller.submit(), isFalse);
      expect(controller.state.errorCode, 'AMBIGUOUS_MATERIAL');
      expect(controller.state.error, contains('LAB-A'));
      expect(controller.state.error, contains('LAB-B'));
      expect(controller.state.materials.length, 2);
      expect(controller.state.templateId, isNull);

      // The operator now picks one and retries with the SAME submission key.
      final chosen = controller.state.materials.last;
      controller.setTemplate(chosen.templateId, sn: chosen.sn);

      expect(await controller.submit(), isTrue);
      final calls = api.callsFor(LabApiRoutes.inventoryReceipt);
      expect(calls.length, 2);
      expect(calls[0].params['request_key'], calls[1].params['request_key']);
      expect(calls[1].params['product_template_id'], 43);
    });

    test('with no archive at all the client sends no template id', () async {
      api.onCall = (path, params) async {
        if (path == LabApiRoutes.catalogCreateMaterial) {
          return <String, dynamic>{
            'product_template_id': 77,
            'sn': 'LAB-NEW',
            'item_key': 'lcsc:C1',
          };
        }
        if (path == LabApiRoutes.inventoryReceipt) {
          final hasTemplate = params.containsKey('product_template_id');
          if (!hasTemplate) {
            throw businessFailure('MATERIAL_NOT_FOUND', '该器件还没有本地物料档案。');
          }
          return <String, dynamic>{
            'item_key': 'lcsc:C1',
            'lab_quantity': 5,
            'inventory_revision': 'rev-11',
          };
        }
        throw StateError('unexpected $path');
      };

      final controller = buildController();
      controller.setItem(itemKey: 'lcsc:C1');
      controller.setLocation(3, label: 'R01');
      controller.setQuantity('5');

      expect(await controller.submit(), isTrue);
      final calls = api.callsFor(LabApiRoutes.inventoryReceipt);
      expect(calls.first.params.containsKey('product_template_id'), isFalse,
          reason: 'no archive is known, so the server decides (on-demand create)');
      expect(calls.last.params['product_template_id'], 77,
          reason: 'the retry uses the archive the server just created');
    });

    test('the merged identity stays the C code whatever archive is chosen', () async {
      final controller = buildController();
      controller.setItem(itemKey: 'lcsc:C1');
      controller.setMaterials(<LabMaterial>[
        material(id: 42, sn: 'LAB-A'),
        material(id: 43, sn: 'LAB-B'),
      ]);
      controller.setTemplate(43, sn: 'LAB-B');

      expect(controller.state.itemKey, 'lcsc:C1',
          reason: 'choosing an archive never rewrites the canonical item key');
      expect(controller.state.templateId, 43);
    });
  });
}
