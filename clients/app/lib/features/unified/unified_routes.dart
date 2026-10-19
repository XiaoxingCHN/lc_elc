import 'package:lab_inventory_client/widgets/lab_ui.dart';
import 'package:go_router/go_router.dart';

import 'models/unified_item.dart';
import 'screens/history_screen.dart';
import 'screens/issue_screen.dart';
import 'screens/labels_screen.dart';
import 'screens/receipt_screen.dart';
import 'screens/pending_receipt_screen.dart';
import 'screens/return_screen.dart';
import 'screens/unified_catalog_screen.dart';
import 'screens/unified_item_detail_screen.dart';

/// Route paths of the unified client business.
///
/// These paths are NOT part of `business_api_contract.json` (that document
/// fixes the HTTP endpoints, not the app's own navigation). They are exported
/// here so the auth/router owner can add ONE line and keep ownership of
/// `lib/routes/app_router.dart` and `lib/main.dart`:
///
/// ```dart
/// routes: <RouteBase>[
///   ...existingRoutes,
///   ...unifiedRoutes,   // <- from lib/features/unified/unified_routes.dart
/// ],
/// ```
///
/// The library's home entry is [catalog]; the three stock operations, the label
/// designer and the trace screen are top-level routes so a deep link (or a
/// scanner intent) can reach them directly.
class UnifiedRoutes {
  const UnifiedRoutes._();

  /// THE unified component library (one list; there is no second library).
  static const String catalog = '/catalog';

  /// One card's detail. Takes `?item_key=lcsc:C123` (or `lab:42`).
  static const String itemDetailPath = '/catalog/item';

  /// 入库.
  static const String receipt = '/receipt';
  static const String pendingReceipt = '/receipt/prepare';

  /// 领料.
  static const String issue = '/issue';

  /// 归还.
  ///
  /// The word `return` is a Dart keyword, so the CONSTANT is named
  /// [returnGoods]; the PATH stays `/return` as agreed.
  static const String returnGoods = '/return';

  /// 标签设计/打印.
  static const String labels = '/labels';

  /// 历史追溯.
  static const String history = '/history';

  /// Detail location of one canonical identity.
  static String itemDetail(String itemKey) =>
      '$itemDetailPath?item_key=${Uri.encodeQueryComponent(itemKey)}';

  /// Receipt prefilled with one catalog row.
  static String receiptFor(UnifiedItem item) => receiptWith(item.itemKey, item.title);

  static String receiptWith(String itemKey, [String name = '']) {
    final query = <String, String>{'item_key': itemKey, if (name.isNotEmpty) 'name': name};
    return Uri(path: receipt, queryParameters: query).toString();
  }

  /// Issue prefilled with one catalog row.
  static String issueFor(UnifiedItem item) => issueWith(item.itemKey, item.title);

  static String issueWith(String itemKey, [String name = '']) {
    final query = <String, String>{'item_key': itemKey, if (name.isNotEmpty) 'name': name};
    return Uri(path: issue, queryParameters: query).toString();
  }

  /// History filtered to one item (or the whole library when `null`).
  static String historyFor(String? itemKey) {
    if (itemKey == null || itemKey.isEmpty) return history;
    return Uri(
      path: history,
      queryParameters: <String, String>{'item_key': itemKey},
    ).toString();
  }

  /// PUBLIC offline library (`/catalog?offline=1`).
  ///
  /// Used by the "查看本机缓存资料" entry on the login screen: no session, no
  /// server writes, public catalog facts only. The auth owner must allow this
  /// path while unauthenticated (see `lib/features/unified/README.md`).
  static const String offlineCatalog = '$catalog?offline=1';

  /// Offline detail of one cached catalog identity.
  static String offlineItemDetail(String itemKey) =>
      '$itemDetailPath?offline=1&item_key=${Uri.encodeQueryComponent(itemKey)}';

  /// True when a route's query asks for the offline library.
  static bool isOffline(Map<String, String> query) =>
      query['offline'] == '1' || query['offline'] == 'true';

  /// Labels prefilled for one bag.
  static String labelsForBag(int bagId) => Uri(
        path: labels,
        queryParameters: <String, String>{'kind': 'bag', 'ids': '$bagId'},
      ).toString();

  /// Labels prefilled for one location.
  static String labelsForLocation(int locationId) => Uri(
        path: labels,
        queryParameters: <String, String>{'kind': 'location', 'ids': '$locationId'},
      ).toString();
}

/// The routes to append to the app router.
///
/// `config_error` / permission handling stays with the auth layer; these routes
/// only build screens. Every screen reads its data from Riverpod providers, so
/// no constructor plumbing is needed from `main.dart`.
final List<RouteBase> unifiedRoutes = <RouteBase>[
  GoRoute(
    path: UnifiedRoutes.pendingReceipt,
    builder: (context, state) => LabPageFrame(
      fallbackLocation: UnifiedRoutes.catalog,
      child: PendingReceiptScreen(initialTab: state.uri.queryParameters['step'] == 'scan' ? 1 : 0,
        initialItemKey: state.uri.queryParameters['item_key']),
    ),
  ),
  GoRoute(
    path: UnifiedRoutes.catalog,
    name: 'unifiedCatalog',
    builder: (context, state) => UnifiedCatalogScreen(
      initialQuery: state.uri.queryParameters['query'],
      initialCategoryId: int.tryParse(state.uri.queryParameters['category_id'] ?? ''),
      offline: UnifiedRoutes.isOffline(state.uri.queryParameters),
    ),
  ),
  GoRoute(
    path: UnifiedRoutes.itemDetailPath,
    name: 'unifiedItemDetail',
    builder: (context, state) => LabPageFrame(
      fallbackLocation: UnifiedRoutes.isOffline(state.uri.queryParameters) ? UnifiedRoutes.offlineCatalog : UnifiedRoutes.catalog,
      child: UnifiedItemDetailScreen(
      itemKey: state.uri.queryParameters['item_key'] ?? '',
      offline: UnifiedRoutes.isOffline(state.uri.queryParameters),
    ),
    ),
  ),
  GoRoute(
    path: UnifiedRoutes.receipt,
    name: 'unifiedReceipt',
    builder: (context, state) => LabPageFrame(
      fallbackLocation: UnifiedRoutes.isOffline(state.uri.queryParameters) ? UnifiedRoutes.offlineCatalog : UnifiedRoutes.catalog,
      child: ReceiptScreen(
      initialItemKey: state.uri.queryParameters['item_key'],
      initialItemName: state.uri.queryParameters['name'],
      initialCode: state.uri.queryParameters['code'],
    ),
    ),
  ),
  GoRoute(
    path: UnifiedRoutes.issue,
    name: 'unifiedIssue',
    builder: (context, state) => LabPageFrame(
      fallbackLocation: UnifiedRoutes.isOffline(state.uri.queryParameters) ? UnifiedRoutes.offlineCatalog : UnifiedRoutes.catalog,
      child: IssueScreen(
      initialItemKey: state.uri.queryParameters['item_key'],
      initialItemName: state.uri.queryParameters['name'],
    ),
    ),
  ),
  GoRoute(
    path: UnifiedRoutes.returnGoods,
    name: 'unifiedReturn',
    builder: (context, state) => LabPageFrame(
      fallbackLocation: UnifiedRoutes.isOffline(state.uri.queryParameters) ? UnifiedRoutes.offlineCatalog : UnifiedRoutes.catalog,
      child: ReturnScreen(
      initialIssueId: int.tryParse(state.uri.queryParameters['issue_id'] ?? ''),
    ),
    ),
  ),
  GoRoute(
    path: UnifiedRoutes.labels,
    name: 'unifiedLabels',
    builder: (context, state) => LabPageFrame(
      fallbackLocation: UnifiedRoutes.isOffline(state.uri.queryParameters) ? UnifiedRoutes.offlineCatalog : UnifiedRoutes.catalog,
      child: LabelsScreen(
      initialKind: state.uri.queryParameters['kind'],
      initialIds: state.uri.queryParameters['ids'],
    ),
    ),
  ),
  GoRoute(
    path: UnifiedRoutes.history,
    name: 'unifiedHistory',
    builder: (context, state) => LabPageFrame(
      fallbackLocation: UnifiedRoutes.isOffline(state.uri.queryParameters) ? UnifiedRoutes.offlineCatalog : UnifiedRoutes.catalog,
      child: HistoryScreen(
      initialItemKey: state.uri.queryParameters['item_key'],
      initialBagId: int.tryParse(state.uri.queryParameters['bag_id'] ?? ''),
    ),
    ),
  ),
];
