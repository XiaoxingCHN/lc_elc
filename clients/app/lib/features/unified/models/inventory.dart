import 'detail_models.dart';
import 'identity.dart';
import 'json_read.dart';

/// A selectable 领用人.
///
/// The user's final decision: the borrower MUST be an existing system account
/// (`res.users`), never a free-text name. The server returns the accounts the
/// current operator is allowed to choose from; the client never invents one and
/// never substitutes a typed name.
class Borrower {
  const Borrower({
    required this.id,
    required this.name,
    required this.login,
    required this.isSelf,
    required this.active,
    this.raw = const <String, dynamic>{},
  });

  final int id;
  final String name;
  final String login;

  /// The server marked this entry as the signed-in operator.
  final bool isSelf;

  final bool active;
  final Map<String, dynamic> raw;

  String get display {
    if (name.isNotEmpty && login.isNotEmpty && name != login) return '$name ($login)';
    if (name.isNotEmpty) return name;
    if (login.isNotEmpty) return login;
    return '#$id';
  }

  factory Borrower.fromJson(Map<String, dynamic> json) {
    return Borrower(
      id: firstInt(json, const ['id', 'user_id', 'res_id', 'borrower_id']) ?? 0,
      name: firstString(json, const ['name', 'display_name', 'borrower_name']) ?? '',
      login: firstString(json, const ['login', 'email', 'user_login']) ?? '',
      isSelf: firstBool(json, const ['is_self', 'self', 'is_me', 'is_current_user']) ??
          false,
      active: firstBool(json, const ['active', 'is_active']) ?? true,
      raw: json,
    );
  }
}

/// Server-side permission flags of the signed-in operator.
///
/// Missing flags default to the SAFE value: without an explicit
/// "may issue for other people" the picker stays locked to the operator's own
/// account, so a client that cannot read the flag can never impersonate anyone.
class InventoryPermissions {
  const InventoryPermissions({
    required this.canIssueForOthers,
    required this.canReceipt,
    required this.canIssue,
    required this.canReturn,
    required this.canCreateLocation,
    required this.canPrintLabels,
    required this.selfBorrowerId,
    required this.uid,
    required this.known,
    this.raw = const <String, dynamic>{},
  });

  /// May this operator issue material to somebody else?
  final bool canIssueForOthers;

  final bool canReceipt;
  final bool canIssue;
  final bool canReturn;
  final bool canCreateLocation;
  final bool canPrintLabels;

  /// Explicit "this is my own borrower account" id, when the server sends one.
  final int? selfBorrowerId;

  /// Authenticated user id the server reports (used to find the self account).
  final int? uid;

  /// True when the server actually returned a non-empty permission payload.
  ///
  /// The UI uses this to explain a locked picker ("服务端未返回代领权限") instead of
  /// silently pretending the operator is unrestricted.
  final bool known;

  final Map<String, dynamic> raw;

  static const InventoryPermissions unknown = InventoryPermissions(
    canIssueForOthers: false,
    canReceipt: false,
    canIssue: false,
    canReturn: false,
    canCreateLocation: false,
    canPrintLabels: false,
    selfBorrowerId: null,
    uid: null,
    known: false,
  );

  factory InventoryPermissions.fromJson(Object? value) {
    if (value is! Map) return unknown;
    final json = asMap(value);
    if (json.isEmpty) return unknown;

    // Permissions may arrive flat or nested under one of these keys.
    final merged = <String, dynamic>{...json};
    for (final key in const ['permissions', 'rights', 'acl', 'flags']) {
      final nested = json[key];
      if (nested is Map) {
        asMap(nested).forEach((name, item) => merged.putIfAbsent(name, () => item));
      }
    }

    bool flag(List<String> keys) {
      for (final key in keys) {
        final value = merged[key];
        if (value is bool) return value;
        if (value is num) return value != 0;
        if (value is String) return asBool(value);
      }
      return false;
    }

    final manage = flag(const [
      'can_issue_for_others',
      'issue_for_others',
      'can_issue_as_other',
      'can_issue_for_other_user',
      'inventory_manager',
      'is_inventory_manager',
      'manage_inventory',
      'can_manage_inventory',
      'can_manage',
      'is_manager',
    ]);

    return InventoryPermissions(
      canIssueForOthers: manage,
      canReceipt: flag(const ['can_receipt', 'receipt', 'can_receive']) || manage,
      canIssue: flag(const ['can_issue', 'issue']) || manage,
      canReturn: flag(const ['can_return', 'return']) || manage,
      canCreateLocation: flag(const ['can_create_location', 'location_create']) || manage,
      canPrintLabels: flag(const ['can_print_labels', 'labels', 'can_print']) || manage,
      selfBorrowerId: firstInt(merged, const [
        'self_borrower_id',
        'own_borrower_id',
        'borrower_id',
        'own_user_id',
      ]),
      uid: firstInt(merged, const ['uid', 'user_id', 'current_uid']),
      known: true,
      raw: json,
    );
  }
}

/// `/lab/api/inventory/bootstrap`: everything a write flow needs up front.
class InventoryBootstrap {
  const InventoryBootstrap({
    required this.locations,
    required this.borrowers,
    required this.permissions,
    required this.inventoryRevision,
    this.raw = const <String, dynamic>{},
  });

  final List<LabStockLocation> locations;

  /// The system accounts the operator may pick as 领用人.
  final List<Borrower> borrowers;

  final InventoryPermissions permissions;
  final String inventoryRevision;
  final Map<String, dynamic> raw;

  bool get canIssueForOthers => permissions.canIssueForOthers;

  /// The borrower entry that stands for the signed-in operator, or `null`.
  ///
  /// Resolution order: the server's own `is_self` marker, then the permission's
  /// explicit self id, then a match against the authenticated uid. No guess is
  /// made from a name.
  Borrower? selfBorrower({int? currentUid}) {
    for (final borrower in borrowers) {
      if (borrower.isSelf) return borrower;
    }
    final explicit = permissions.selfBorrowerId;
    if (explicit != null) {
      for (final borrower in borrowers) {
        if (borrower.id == explicit) return borrower;
      }
    }
    final uid = currentUid ?? permissions.uid;
    if (uid != null) {
      for (final borrower in borrowers) {
        if (borrower.id == uid) return borrower;
      }
    }
    return null;
  }

  /// The accounts the operator is allowed to select right now.
  ///
  /// An ordinary operator gets exactly their own account (self-service issue is
  /// self-only, by the user's explicit rule). An inventory manager gets the full
  /// server-authorised list. The operator is always recorded separately by the
  /// server from the authenticated session, so being able to pick somebody else
  /// never lets the client claim to be that person.
  List<Borrower> selectableBorrowers({int? currentUid}) {
    final active = borrowers.where((borrower) => borrower.active).toList();
    if (canIssueForOthers) return active;
    final self = selfBorrower(currentUid: currentUid);
    if (self == null) return const <Borrower>[];
    return <Borrower>[self];
  }

  LabStockLocation? locationById(int? id) {
    if (id == null) return null;
    for (final location in locations) {
      if (location.id == id) return location;
    }
    return null;
  }

  static const InventoryBootstrap empty = InventoryBootstrap(
    locations: <LabStockLocation>[],
    borrowers: <Borrower>[],
    permissions: InventoryPermissions.unknown,
    inventoryRevision: '',
  );

  factory InventoryBootstrap.fromJson(Map<String, dynamic> json) {
    return InventoryBootstrap(
      locations: asMapList(json['locations']).map(LabStockLocation.fromJson).toList(),
      borrowers: asMapList(json['borrowers'])
          .map(Borrower.fromJson)
          .where((borrower) => borrower.id > 0)
          .toList(),
      permissions: InventoryPermissions.fromJson(json['permissions']),
      inventoryRevision: firstString(json, const ['inventory_revision']) ?? '',
      raw: json,
    );
  }
}

/// Result of `/lab/api/inventory/resolve_code`.
///
/// The same entry point accepts a本系统 trace code (`LABB:`), a location code
/// (`LABL:`), and the original LCSC bag payload that the supplier printed.
class ResolvedCode {
  const ResolvedCode({
    required this.raw,
    required this.kind,
    required this.itemKey,
    required this.bag,
    required this.location,
    required this.supplierMetadata,
    this.productTemplateId,
    this.sn,
    this.materials = const <LabMaterial>[],
    this.rawJson = const <String, dynamic>{},
  });

  static const String kindBag = 'bag';
  static const String kindLocation = 'location';
  static const String kindSupplier = 'supplier';
  static const String kindCatalog = 'catalog';
  static const String kindUnknown = 'unknown';

  /// The exact text the operator scanned / typed / pasted.
  final String raw;

  /// One of [kindBag], [kindLocation], [kindSupplier], [kindCatalog],
  /// [kindUnknown].
  final String kind;

  final String itemKey;
  final LabBag? bag;
  final LabStockLocation? location;
  final Map<String, dynamic> supplierMetadata;

  /// The EXACT local archive the scanned code belongs to, when the server
  /// reports it (an SN scan or an existing bag).
  ///
  /// Root's rule: a scan that identifies an SN keeps that archive, so a receipt
  /// can never be mis-bound to another archive of the same C code.
  final int? productTemplateId;

  /// SN carried by the scanned code, when there is one.
  final String? sn;

  /// Candidate archives the server offered when a choice is required.
  final List<LabMaterial> materials;

  final Map<String, dynamic> rawJson;

  bool get isBag => kind == kindBag && bag != null;
  bool get isLocation => kind == kindLocation && location != null;
  bool get isSupplier => kind == kindSupplier;
  bool get isCatalog => kind == kindCatalog;
  bool get isUnknown =>
      kind == kindUnknown || (bag == null && location == null && itemKey.isEmpty);

  /// True when a receipt can be built from this scan.
  bool get canReceipt => isBag || isSupplier || isCatalog || itemKey.isNotEmpty;

  /// Location implied by the scan (a bag knows where it sits).
  int? get impliedLocationId => bag?.locationId ?? location?.id;

  /// The trace code to store on the receipt, when the scan carried one.
  String? get supplierQr {
    if (bag != null && bag!.traceCode.isNotEmpty) return bag!.labelPayload;
    if (raw.isNotEmpty && !isLocation) return raw;
    return null;
  }

  String get displayKind {
    switch (kind) {
      case kindBag:
        return '追溯袋码';
      case kindLocation:
        return '库位码';
      case kindSupplier:
        return '立创来料码';
      case kindCatalog:
        return '器件编码';
      default:
        return '未识别';
    }
  }

  factory ResolvedCode.fromJson(String raw, Map<String, dynamic> json) {
    final bagJson = asMap(json['bag']);
    final locationJson = asMap(json['location']);
    final supplier = asMap(json['supplier_metadata']);

    final bag = bagJson.isEmpty ? null : LabBag.fromJson(bagJson);
    final location =
        locationJson.isEmpty ? null : LabStockLocation.fromJson(locationJson);

    var kind = (firstString(json, const ['kind', 'type', 'code_kind']) ?? '')
        .toLowerCase()
        .trim();
    if (kind.isEmpty) {
      if (bag != null) {
        kind = kindBag;
      } else if (location != null) {
        kind = kindLocation;
      } else if (supplier.isNotEmpty) {
        kind = kindSupplier;
      }
    }
    // The server may answer `unknown` while still returning a usable item key.
    final itemKey = deriveItemKey(json) ?? bag?.itemKey ?? '';
    if (kind == kindUnknown && itemKey.isNotEmpty) {
      kind = kindCatalog;
    }

    return ResolvedCode(
      raw: raw,
      kind: kind.isEmpty ? kindUnknown : kind,
      itemKey: itemKey,
      bag: bag,
      location: location,
      supplierMetadata: supplier,
      // The exact archive is taken from the scan - never derived by "first".
      productTemplateId: firstInt(
            json,
            const ['product_template_id', 'template_id', 'lab_template_id'],
          ) ??
          bag?.productTemplateId,
      sn: firstString(json, const ['sn', 'sn_code', 'lab_sn']) ?? bag?.sn,
      materials: LabMaterial.listFrom(
        json['materials'] ?? json['candidates'] ?? json['archives'],
      ),
      rawJson: json,
    );
  }

  static ResolvedCode unresolved(String raw) => ResolvedCode(
        raw: raw,
        kind: kindUnknown,
        itemKey: '',
        bag: null,
        location: null,
        supplierMetadata: const <String, dynamic>{},
      );
}

/// `/lab/api/inventory/receipt` result.
class ReceiptResult {
  const ReceiptResult({
    required this.operation,
    required this.bag,
    required this.itemKey,
    required this.labQuantity,
    required this.inventoryRevision,
  });

  final LabOperation? operation;
  final LabBag? bag;
  final String itemKey;

  /// The lab quantity the server reports AFTER this receipt (authoritative).
  final double? labQuantity;

  final String inventoryRevision;

  factory ReceiptResult.fromJson(Map<String, dynamic> json) {
    final operationJson = asMap(json['operation']);
    final bagJson = asMap(json['bag']);
    return ReceiptResult(
      operation:
          operationJson.isEmpty ? null : LabOperation.fromJson(operationJson),
      bag: bagJson.isEmpty ? null : LabBag.fromJson(bagJson),
      itemKey: deriveItemKey(json) ?? '',
      labQuantity: firstDouble(json, const ['lab_quantity', 'quantity', 'on_hand']),
      inventoryRevision: firstString(json, const ['inventory_revision']) ?? '',
    );
  }
}

/// `/lab/api/inventory/issue` result.
class IssueResult {
  const IssueResult({required this.operation, required this.inventoryRevision});

  final LabOperation? operation;
  final String inventoryRevision;

  factory IssueResult.fromJson(Map<String, dynamic> json) {
    final operationJson = asMap(json['operation']);
    return IssueResult(
      operation:
          operationJson.isEmpty ? null : LabOperation.fromJson(operationJson),
      inventoryRevision: firstString(json, const ['inventory_revision']) ?? '',
    );
  }
}

/// `/lab/api/inventory/return` result.
///
/// [outstandingQuantity] is the server's remaining unreturned amount after this
/// return; the UI shows it instead of computing its own balance.
class ReturnResult {
  const ReturnResult({
    required this.operation,
    required this.outstandingQuantity,
    required this.inventoryRevision,
  });

  final LabOperation? operation;
  final double? outstandingQuantity;
  final String inventoryRevision;

  factory ReturnResult.fromJson(Map<String, dynamic> json) {
    final operationJson = asMap(json['operation']);
    return ReturnResult(
      operation:
          operationJson.isEmpty ? null : LabOperation.fromJson(operationJson),
      outstandingQuantity: firstDouble(
        json,
        const ['outstanding_quantity', 'outstanding', 'unreturned_quantity'],
      ),
      inventoryRevision: firstString(json, const ['inventory_revision']) ?? '',
    );
  }
}

/// `/lab/api/catalog/create_material` result (a new local archive + its SN).
class CreateMaterialResult {
  const CreateMaterialResult({
    required this.itemKey,
    required this.productTemplateId,
    required this.productId,
    required this.sn,
  });

  final String itemKey;
  final int? productTemplateId;
  final int? productId;

  /// The SN the server generated. The client never invents one.
  final String sn;

  factory CreateMaterialResult.fromJson(Map<String, dynamic> json) {
    return CreateMaterialResult(
      itemKey: deriveItemKey(json) ?? '',
      productTemplateId: firstInt(json, const ['product_template_id', 'template_id']),
      productId: firstInt(json, const ['product_id']),
      sn: firstString(json, const ['sn', 'sn_code', 'lab_sn']) ?? '',
    );
  }
}

/// `/lab/api/catalog/bind` result.
class BindResult {
  const BindResult({required this.itemKey, required this.productTemplateId});

  final String itemKey;
  final int? productTemplateId;

  factory BindResult.fromJson(Map<String, dynamic> json) {
    return BindResult(
      itemKey: deriveItemKey(json) ?? '',
      productTemplateId: firstInt(json, const ['product_template_id', 'template_id']),
    );
  }
}
