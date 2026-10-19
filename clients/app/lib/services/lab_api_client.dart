import 'package:uuid/uuid.dart';

import '../features/unified/models/detail_models.dart';
import '../features/unified/models/catalog_query.dart';
import '../features/unified/models/inventory.dart';
import '../features/unified/models/json_read.dart';
import '../features/unified/models/labels.dart';
import '../features/unified/models/unified_item.dart';
import '../models/lab_api_exception.dart';

/// One business-endpoint call.
///
/// [OdooClient.callRoute] is the only implementation used in production: it
/// reuses the authenticated `session_id` cookie jar and turns the
/// `{ok, data, error}` envelope into either `data` or a [LabApiException]. This
/// client never opens its own cookie jar and never logs in by itself.
///
/// Tests pass a recording function instead, so every payload assertion runs
/// against the REAL serialisation code without a socket.
typedef LabRouteCall = Future<Map<String, dynamic>> Function(
  String path,
  Map<String, dynamic> params,
);

/// Generates the idempotency key of one write.
///
/// The SAME key must be reused while the operator retries the same submission:
/// that is what makes a retry after a timeout safe (the server de-duplicates
/// `request_key` + payload fingerprint). A new key is issued only for a new
/// submission.
String newRequestKey() => const Uuid().v4();

/// Route paths of `lc_elc/docs/business_api_contract.json`.
///
/// Paths are the contract's own; nothing here invents an endpoint.
class LabApiRoutes {
  const LabApiRoutes._();

  // Catalog (one unified library - there is no second "lab library" endpoint).
  static const String catalogSearch = '/lab/api/catalog/search';
  static const String catalogDetail = '/lab/api/catalog/detail';
  static const String catalogCategories = '/lab/api/catalog/categories';
  static const String catalogFacets = '/lab/api/catalog/facets';
  static const String catalogBind = '/lab/api/catalog/bind';
  static const String catalogCreateMaterial = '/lab/api/catalog/create_material';

  // Inventory / workflow.
  static const String inventoryBootstrap = '/lab/api/inventory/bootstrap';
  static const String inventoryLocations = '/lab/api/inventory/locations';
  static const String inventoryLocationCreate = '/lab/api/inventory/location_create';
  static const String inventoryResolveCode = '/lab/api/inventory/resolve_code';
  static const String inventoryReceipt = '/lab/api/inventory/receipt';
  static const String inventoryIssue = '/lab/api/inventory/issue';
  static const String inventoryReturn = '/lab/api/inventory/return';
  static const String inventoryIssues = '/lab/api/inventory/issues';
  static const String inventoryHistory = '/lab/api/inventory/history';

  // Labels (reading this never writes stock).
  static const String labelsPreview = '/lab/api/labels/preview';
}

/// Typed access to every `/lab/api/...` route this client uses.
///
/// Design rules enforced here:
///   * a failure is never returned as data - the transport throws
///     [LabApiException] and it propagates unchanged, so no caller can turn a
///     permission error or a dead session into an empty list;
///   * `limit` is the server's page size (`<= 200`), never `1000`;
///   * pagination is the opaque `cursor`; no OFFSET, no client-side filtering of
///     an already-loaded page;
///   * every write carries a caller-supplied `request_key`.
class LabApiClient {
  LabApiClient({required LabRouteCall call}) : _call = call;

  final LabRouteCall _call;

  /// Largest page the contract allows.
  static const int maxPageSize = 200;

  /// Default page size the UI uses.
  static const int defaultPageSize = 50;

  /// Drops null values, keeps empty strings/lists (the contract declares them).
  static Map<String, dynamic> _prune(Map<String, dynamic> params) {
    final result = <String, dynamic>{};
    params.forEach((key, value) {
      if (value == null) return;
      result[key] = value;
    });
    return result;
  }

  Future<Map<String, dynamic>> _invoke(
    String path,
    Map<String, dynamic> params,
  ) =>
      _call(path, _prune(params));

  // ---------------------------------------------------------------------------
  // Unified library (one list, one detail)
  // ---------------------------------------------------------------------------

  /// `/lab/api/catalog/search` - THE unified list.
  ///
  /// Ordering (in-stock first, globally) and the cursor are the server's; this
  /// method returns the page as-is.
  Future<CatalogSearchPage> search(
    CatalogQuery query, {
    String? cursor,
    int limit = defaultPageSize,
  }) async {
    final size = limit.clamp(1, maxPageSize);
    final data = await _invoke(
      LabApiRoutes.catalogSearch,
      query.toSearchParams(cursor: cursor, limit: size),
    );
    return CatalogSearchPage.fromJson(data);
  }

  /// `/lab/api/catalog/detail` - parameters, files, locations, bags, history.
  Future<CatalogDetail> detail(String itemKey) async {
    return CatalogDetail.fromJson(await detailJson(itemKey));
  }

  /// The RAW detail payload.
  ///
  /// Returned unchanged so the caller can persist it for offline use (root's
  /// requirement: caching the file bytes alone is not enough - an offline detail
  /// must still list its manuals). Nothing here interprets or rewrites it.
  Future<Map<String, dynamic>> detailJson(String itemKey) async {
    final key = itemKey.trim();
    if (key.isEmpty) {
      throw const LabApiException(
        code: 'BAD_REQUEST',
        message: '缺少器件标识，无法打开详情。',
      );
    }
    return _invoke(
      LabApiRoutes.catalogDetail,
      <String, dynamic>{'item_key': key},
    );
  }

  /// `/lab/api/catalog/categories` - the navigation tree.
  Future<List<CatalogCategory>> categories() async {
    final data = await _invoke(LabApiRoutes.catalogCategories, const {});
    final nodes = data['categories'] ?? data['nodes'] ?? data['items'];
    final parsed = asMapList(nodes).map(CatalogCategory.fromJson).toList();
    // A nested payload already carries its children; a flat one does not.
    final hasNested = parsed.any((node) => node.children.isNotEmpty);
    return hasNested ? parsed : CatalogCategory.forest(parsed);
  }

  /// `/lab/api/catalog/facets` - available filter values for the current query.
  Future<CatalogFacets> facets(CatalogQuery query) async {
    final data = await _invoke(LabApiRoutes.catalogFacets, query.toFacetParams());
    return CatalogFacets.fromJson(data);
  }

  /// `/lab/api/catalog/bind` - attach a captured catalog row to an existing
  /// local `product.template`.
  Future<BindResult> bind({
    required int productTemplateId,
    required String catalogCode,
  }) async {
    final data = await _invoke(LabApiRoutes.catalogBind, <String, dynamic>{
      'product_template_id': productTemplateId,
      'catalog_code': catalogCode,
    });
    return BindResult.fromJson(data);
  }

  /// `/lab/api/catalog/create_material` - create the local archive + its SN.
  Future<CreateMaterialResult> createMaterial(String itemKey) async {
    final data = await _invoke(
      LabApiRoutes.catalogCreateMaterial,
      <String, dynamic>{'item_key': itemKey},
    );
    return CreateMaterialResult.fromJson(data);
  }

  // ---------------------------------------------------------------------------
  // Inventory write flows
  // ---------------------------------------------------------------------------

  /// `/lab/api/inventory/bootstrap` - locations, selectable borrowers, rights.
  Future<InventoryBootstrap> bootstrap() async {
    final data = await _invoke(LabApiRoutes.inventoryBootstrap, const {});
    return InventoryBootstrap.fromJson(data);
  }

  /// `/lab/api/inventory/locations`.
  Future<List<LabStockLocation>> locations() async {
    final data = await _invoke(LabApiRoutes.inventoryLocations, const {});
    final nodes = data['locations'] ?? data['items'];
    return asMapList(nodes).map(LabStockLocation.fromJson).toList();
  }

  /// `/lab/api/inventory/location_create` - a new internal location + 库码.
  Future<LabStockLocation> createLocation({
    required String name,
    int? parentId,
  }) async {
    final data = await _invoke(LabApiRoutes.inventoryLocationCreate, <String, dynamic>{
      'name': name,
      'parent_id': parentId,
    });
    final location = asMap(data['location']);
    if (location.isEmpty) {
      // Some controllers answer with the location fields at top level.
      return LabStockLocation.fromJson(data);
    }
    return LabStockLocation.fromJson(location);
  }

  /// `/lab/api/inventory/resolve_code` - interpret one scanned/typed code.
  ///
  /// Accepts this system's trace code, a location code, an item code, and the
  /// original LCSC bag payload. The interpretation is the server's; a code it
  /// cannot place comes back as [ResolvedCode.kindUnknown] (or as a
  /// [LabApiException] with a Chinese message, which the caller shows as-is).
  Future<ResolvedCode> resolveCode(String raw) async {
    final text = raw.trim();
    if (text.isEmpty) {
      throw const LabApiException(
        code: 'EMPTY_CODE',
        message: '请输入或扫描要解析的编码。',
      );
    }
    final data = await _invoke(
      LabApiRoutes.inventoryResolveCode,
      <String, dynamic>{'raw': text},
    );
    return ResolvedCode.fromJson(text, data);
  }

  /// `/lab/api/inventory/receipt` - create REAL bag stock in a location.
  ///
  /// [productTemplateId] is the EXACT local archive the new bag belongs to. It is
  /// optional in the contract: omit it and the server decides (auto-select the
  /// single archive, create one on demand, or answer `AMBIGUOUS_MATERIAL` with
  /// candidates). Sending it is what keeps a scan of one SN from being bound to
  /// another archive of the same C code.
  Future<ReceiptResult> receipt({
    required String requestKey,
    required String itemKey,
    required int locationId,
    required double quantity,
    int? productTemplateId,
    String? supplierQr,
    String note = '',
  }) async {
    final data = await _invoke(LabApiRoutes.inventoryReceipt, <String, dynamic>{
      'request_key': requestKey,
      'item_key': itemKey,
      'location_id': locationId,
      'quantity': quantity,
      'product_template_id': productTemplateId,
      'supplier_qr': supplierQr,
      'note': note,
    });
    return ReceiptResult.fromJson(data);
  }

  /// `/lab/api/inventory/issue` - take material out of specific bags.
  ///
  /// [borrowerId] MUST be an existing system account taken from
  /// [InventoryBootstrap.selectableBorrowers]; the server records the ACTOR
  /// from the authenticated session, so this field can never impersonate the
  /// operator.
  Future<IssueResult> issue({
    required String requestKey,
    required int borrowerId,
    required String project,
    required List<({int bagId, double quantity})> lines,
    String note = '',
  }) async {
    final data = await _invoke(LabApiRoutes.inventoryIssue, <String, dynamic>{
      'request_key': requestKey,
      'borrower_id': borrowerId,
      'project': project,
      'lines': lines
          .map((line) => <String, dynamic>{
                'bag_id': line.bagId,
                'quantity': line.quantity,
              })
          .toList(),
      'note': note,
    });
    return IssueResult.fromJson(data);
  }

  /// `/lab/api/inventory/return` - return against the ORIGINAL issue line.
  Future<ReturnResult> returnQuantity({
    required String requestKey,
    required int issueLineId,
    required double quantity,
    String note = '',
  }) async {
    final data = await _invoke(LabApiRoutes.inventoryReturn, <String, dynamic>{
      'request_key': requestKey,
      'issue_line_id': issueLineId,
      'quantity': quantity,
      'note': note,
    });
    return ReturnResult.fromJson(data);
  }

  /// `/lab/api/inventory/issues` - issue records, optionally outstanding only.
  Future<IssuePage> issues({
    String query = '',
    bool outstandingOnly = true,
    String? cursor,
    int limit = defaultPageSize,
  }) async {
    final data = await _invoke(LabApiRoutes.inventoryIssues, <String, dynamic>{
      'query': query,
      'outstanding_only': outstandingOnly,
      'cursor': cursor,
      'limit': limit.clamp(1, maxPageSize),
    });
    return IssuePage.fromJson(data);
  }

  /// `/lab/api/inventory/history` - the immutable trace feed.
  Future<OperationPage> history({
    String? itemKey,
    int? bagId,
    String? cursor,
    int limit = defaultPageSize,
  }) async {
    final data = await _invoke(LabApiRoutes.inventoryHistory, <String, dynamic>{
      'item_key': itemKey,
      'bag_id': bagId,
      'cursor': cursor,
      'limit': limit.clamp(1, maxPageSize),
    });
    return OperationPage.fromJson(data);
  }

  // ---------------------------------------------------------------------------
  // Labels
  // ---------------------------------------------------------------------------

  /// `/lab/api/labels/preview` - render a real A4 PDF.
  ///
  /// This is read-only: generating or reprinting a label never changes stock.
  Future<LabelPdfResult> previewLabels(LabelSpec spec) async {
    final data = await _invoke(LabApiRoutes.labelsPreview, spec.toParams());
    return LabelPdfResult.fromJson(data);
  }
}
