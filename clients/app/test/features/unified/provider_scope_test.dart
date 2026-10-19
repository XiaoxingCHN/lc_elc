import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lab_inventory_client/features/unified/models/session_scope.dart';
import 'package:lab_inventory_client/features/unified/providers/inventory_providers.dart';
import 'package:lab_inventory_client/features/unified/providers/label_providers.dart';
import 'package:lab_inventory_client/features/unified/providers/unified_providers.dart';
import 'package:lab_inventory_client/services/lab_api_client.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Provider-level session isolation.
///
/// Root's finding: watching only the uid rebuilt nothing when the SAME user id
/// was reached on another server/database, so the previous scope's API client,
/// cache directory, revision and half-filled forms survived a switch. These tests
/// pin the corrected behaviour: the whole scope is watched, and a change tears the
/// business state down.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late StateProvider<LabSessionScope> scope;
  late ProviderContainer container;

  const scopeA = LabSessionScope(
    baseUrl: 'http://server-a:8069',
    database: 'db_a',
    uid: 7,
  );
  const scopeOtherServer = LabSessionScope(
    baseUrl: 'http://server-b:8069',
    database: 'db_a',
    uid: 7,
  );
  const scopeOtherUser = LabSessionScope(
    baseUrl: 'http://server-a:8069',
    database: 'db_a',
    uid: 8,
  );

  setUp(() {
    SharedPreferences.setMockInitialValues(<String, Object>{});
    scope = StateProvider<LabSessionScope>((ref) => scopeA);
    container = ProviderContainer(
      overrides: <Override>[
        sessionScopeSourceProvider.overrideWith((ref) => ref.watch(scope)),
      ],
    );
    addTearDown(container.dispose);
  });

  test('the whole scope (server, database, uid, company) drives the providers', () {
    expect(container.read(effectiveSessionScopeProvider), scopeA);

    container.read(scope.notifier).state = scopeOtherServer;
    expect(container.read(effectiveSessionScopeProvider), scopeOtherServer);

    container.read(scope.notifier).state = scopeOtherUser;
    expect(container.read(effectiveSessionScopeProvider), scopeOtherUser);
  });

  test('the API client is rebuilt when the same uid moves to another server', () {
    final first = container.read(labApiProvider);
    container.read(scope.notifier).state = scopeOtherServer;
    final second = container.read(labApiProvider);

    expect(identical(first, second), isFalse,
        reason: 'a different server/db must not reuse the previous client binding');
  });

  test('the file cache switches to another scope directory', () {
    final first = container.read(assetCacheProvider);
    expect(first.scopeKey, scopeA.key);

    container.read(scope.notifier).state = scopeOtherUser;
    final second = container.read(assetCacheProvider);
    expect(second.scopeKey, scopeOtherUser.key);
    expect(second.scopeKey == first.scopeKey, isFalse);
  });

  test('a successful write revision does not leak into the next session', () {
    container.read(dataRevisionProvider.notifier).bump(inventory: 'rev-42');
    expect(container.read(dataRevisionProvider).inventory, 'rev-42');
    expect(container.read(dataRevisionProvider).sequence, 1);

    container.read(scope.notifier).state = scopeOtherUser;

    final after = container.read(dataRevisionProvider);
    expect(after.inventory, isEmpty);
    expect(after.sequence, 0);
  });

  test('a half-filled receipt form is dropped when the operator changes', () {
    final controller = container.read(receiptControllerProvider.notifier);
    controller.setItem(itemKey: 'lcsc:C1', itemName: '器件1');
    controller.setLocation(5, label: 'R01');
    controller.setQuantity('25');

    final before = container.read(receiptControllerProvider);
    expect(before.itemKey, 'lcsc:C1');

    container.read(scope.notifier).state = scopeOtherUser;

    final after = container.read(receiptControllerProvider);
    expect(after.itemKey, isEmpty, reason: 'another account must start clean');
    expect(after.quantityText, isEmpty);
    expect(after.locationId, isNull);
    expect(after.requestKey, isNot(before.requestKey),
        reason: 'a new session gets a new idempotency key');
  });

  test('the company context is part of the scope and of the cache key', () {
    final withoutCompany = container.read(assetCacheProvider).scopeKey;
    container.read(companyScopeProvider.notifier).state = '2';

    expect(container.read(effectiveSessionScopeProvider).company, '2');
    expect(container.read(assetCacheProvider).scopeKey, isNot(withoutCompany));
  });

  test('the label designer is reset on a session change', () {
    container
        .read(labelDesignerProvider.notifier)
        .toggleSelection(11, 'TRACE-11');
    expect(container.read(labelDesignerProvider).selection, isNotEmpty);

    container.read(scope.notifier).state = scopeOtherServer;
    expect(container.read(labelDesignerProvider).selection, isEmpty);
  });

  test('a signed-out session reports no uid and no persistable scope', () {
    container.read(scope.notifier).state = LabSessionScope.anonymous;
    expect(container.read(currentUidProvider), isNull);
    expect(container.read(effectiveSessionScopeProvider).canPersistBusinessData, isFalse);
    expect(container.read(labApiProvider), isA<LabApiClient>());
  });
}
