import 'package:go_router/go_router.dart';

import '../unified/screens/unified_catalog_screen.dart';
import '../unified/unified_routes.dart';
import 'screens/inventory_manage_screen.dart';
import 'screens/location_contents_screen.dart';
import 'screens/location_overview_screen.dart';
import 'screens/stock_overview_screen.dart';

/// Paths of the four warehouse sections.
///
/// The sections are branches of ONE shell route, so each keeps its own
/// navigation stack: opening a part's detail from 器件库 and coming back lands
/// on 器件库, not on whatever the operator last looked at in another section.
///
/// The operational pages (入库 / 领料 / 归还 / 标签 / 历史) are NOT here. They
/// stay at the top level (`UnifiedRoutes`) and are pushed full-screen, so a deep
/// link, a scanner intent and the back button behave exactly as before.
class WarehouseRoutes {
  const WarehouseRoutes._();

  /// 库存速览 - the signed-in landing.
  static const String overview = '/stock';

  /// 仓位速览.
  static const String locations = '/stock/locations';

  /// One location's contents. `:id` is the `stock.location` id.
  static const String locationContentsPath = '/stock/locations/:id';

  /// 器件库 - the existing unified library, unchanged.
  static const String catalog = UnifiedRoutes.catalog;

  /// 库存管理 - the five operations.
  static const String manage = '/stock/manage';

  static String locationContents(int id) => '/stock/locations/$id';

  /// Section root for a branch index (the shell's four `initialLocation`s).
  static String rootForBranch(int index) {
    switch (index) {
      case 0:
        return overview;
      case 1:
        return locations;
      case 2:
        return catalog;
      default:
        return manage;
    }
  }
}

/// The four branches, in [WarehouseSection] order.
///
/// Each branch has a root and - where it needs one - its own child route, so
/// pushing a detail inside a section keeps that section's stack.
final List<StatefulShellBranch> warehouseBranches = <StatefulShellBranch>[
  // 0 - 库存速览
  StatefulShellBranch(
    routes: <RouteBase>[
      GoRoute(
        path: WarehouseRoutes.overview,
        name: 'warehouseOverview',
        builder: (context, state) => const StockOverviewScreen(),
      ),
    ],
  ),
  // 1 - 仓位速览 (+ one location's contents)
  StatefulShellBranch(
    routes: <RouteBase>[
      GoRoute(
        path: WarehouseRoutes.locations,
        name: 'warehouseLocations',
        builder: (context, state) => const LocationOverviewScreen(),
        routes: <RouteBase>[
          GoRoute(
            path: ':id',
            name: 'warehouseLocationContents',
            builder: (context, state) => LocationContentsScreen(
              locationId: int.tryParse(state.pathParameters['id'] ?? '') ?? 0,
            ),
          ),
        ],
      ),
    ],
  ),
  // 2 - 器件库 (the existing screen, unchanged)
  StatefulShellBranch(
    routes: <RouteBase>[
      GoRoute(
        path: WarehouseRoutes.catalog,
        name: 'warehouseCatalog',
        builder: (context, state) => UnifiedCatalogScreen(
          initialQuery: state.uri.queryParameters['query'],
          initialCategoryId:
              int.tryParse(state.uri.queryParameters['category_id'] ?? ''),
          offline: UnifiedRoutes.isOffline(state.uri.queryParameters),
        ),
      ),
    ],
  ),
  // 3 - 库存管理
  StatefulShellBranch(
    routes: <RouteBase>[
      GoRoute(
        path: WarehouseRoutes.manage,
        name: 'warehouseManage',
        builder: (context, state) => const InventoryManageScreen(),
      ),
    ],
  ),
];
