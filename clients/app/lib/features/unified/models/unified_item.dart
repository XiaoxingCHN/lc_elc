import 'identity.dart';
import 'json_read.dart';

/// One visible card of the UNIFIED component library.
///
/// List responses come from `/lab/api/catalog/search`, whose row shape is fixed
/// by `lc_elc/docs/business_api_contract.json`:
///
/// ```json
/// {"item_key":"lcsc:C123","catalog_code":"C123","lab_template_ids":[],
///  "sn_codes":[],"name":"","mpn":"","brand":"","package":"",
///  "category_id":null,"category_name":"","image_url":null,
///  "lab_quantity":0,"lab_available_quantity":0,"has_stock":false,
///  "catalog_stock":null,"parameters":[],"revision":""}
/// ```
///
/// Two invariants this model keeps:
///
///   * `catalog_stock` (mall stock) is a SEPARATE field. It never feeds
///     [labQuantity], it never influences ordering, and the UI must label it as
///     mall stock. Lab stock and mall stock are different numbers.
///   * sorting is the server's job (in-stock-first, globally). The client
///     appends pages in the order the server returned them and does not re-sort
///     locally, because a local sort would break the keyset cursor.
class UnifiedItem {
  const UnifiedItem({
    required this.itemKey,
    required this.catalogCode,
    required this.labTemplateIds,
    required this.snCodes,
    required this.name,
    required this.mpn,
    required this.brand,
    required this.packageName,
    required this.categoryId,
    required this.categoryName,
    required this.imageUrl,
    this.imageAlternateUrl,
    required this.labQuantity,
    required this.labAvailableQuantity,
    required this.hasStock,
    required this.catalogStock,
    required this.parameters,
    required this.revision,
    this.raw = const <String, dynamic>{},
  });

  /// Canonical identity: `lcsc:C123` or `lab:42`.
  final String itemKey;

  /// Normalized `C` code, `''` for an unbound local material.
  final String catalogCode;

  /// Local `product.template` ids aggregated under this card. A card may cover
  /// several archives (the contract keeps them separate in the detail view).
  final List<int> labTemplateIds;

  /// Every local SN under this card (one per physical material archive).
  final List<String> snCodes;

  final String name;
  final String mpn;
  final String brand;

  /// Package/footprint, e.g. `0805`, `SOP8`.
  ///
  /// Named `packageName` because `package` is a Dart built-in identifier; the
  /// JSON key stays `package`.
  final String packageName;
  final int? categoryId;
  final String categoryName;

  /// Real image reference from the captured catalog data, or `null`. Only a
  /// part of the captured rows has one; `null` must render an explicit
  /// placeholder, never a generated picture.
  ///
  /// The value may be an absolute CDN URL or a SAME-ORIGIN path such as
  /// `/lab/api/asset/...`. [AssetCacheStore] decides how to fetch it: a CDN is
  /// fetched without cookies, a same-origin path with the session.
  final String? imageUrl;

  /// Public original image URL, when the server sent one next to an
  /// authenticated reference. Used as a fallback, never as the primary source.
  final String? imageAlternateUrl;

  /// Internal lab quantity on hand, aggregated over the permitted templates.
  final double labQuantity;

  /// Internal lab quantity free to issue (reserved stock excluded).
  final double labAvailableQuantity;

  /// True when the lab itself holds stock - this is what the backend sorts by.
  final bool hasStock;

  /// MALL stock (立创现货). Informational only - never lab stock.
  final double? catalogStock;

  final List<UnifiedParameter> parameters;

  /// Inventory/catalog revision the row was computed from.
  final String revision;

  /// The untouched server row (diagnostics and forward compatibility).
  final Map<String, dynamic> raw;

  IdentityKind get identityKind => identityKindOf(itemKey);

  bool get isCatalogCard => identityKind == IdentityKind.catalog;
  bool get isLocalCard => identityKind == IdentityKind.lab;

  /// True when this card has local archives behind it.
  bool get hasLocalArchives => labTemplateIds.isNotEmpty || snCodes.isNotEmpty;

  /// Best available short title. Never empty: falls back to the identity, not
  /// to an invented name.
  String get title {
    if (name.isNotEmpty) return name;
    if (mpn.isNotEmpty) return mpn;
    if (catalogCode.isNotEmpty) return catalogCode;
    return itemKey;
  }

  /// Sub-line for the card: brand / package / MPN, whatever exists.
  String get subtitle {
    final parts = <String>[
      if (brand.isNotEmpty) brand,
      if (packageName.isNotEmpty) packageName,
      if (mpn.isNotEmpty) mpn,
    ];
    return parts.join(' · ');
  }

  /// `true` when there is a real captured image to show.
  bool get hasRealImage => imageUrl != null || imageAlternateUrl != null;

  /// Candidate references in the order the cache should try them.
  List<String> get imageReferences => <String>[
        if (imageUrl != null) imageUrl!,
        if (imageAlternateUrl != null) imageAlternateUrl!,
      ];

  factory UnifiedItem.fromJson(Map<String, dynamic> json) {
    final catalogCode = normalizeCatalogCode(
      firstValue(json, const ['catalog_code', 'lcsc_code', 'code']),
    );
    // The server key wins; a derived key is only a fallback and only when the
    // value is genuinely usable (null/invalid codes never merge).
    final itemKey = deriveItemKey(json) ?? 'unidentified:${json.hashCode}';

    final templateIds = <int>[];
    for (final id in asList(json['lab_template_ids'])) {
      final value = asInt(id);
      if (value != null && value > 0) templateIds.add(value);
    }
    final singleTemplate = firstInt(json, const ['product_template_id']);
    if (singleTemplate != null &&
        singleTemplate > 0 &&
        !templateIds.contains(singleTemplate)) {
      templateIds.add(singleTemplate);
    }

    return UnifiedItem(
      itemKey: itemKey,
      catalogCode: isUsableCatalogCode(catalogCode)
          ? catalogCode
          : (itemKey.startsWith(kCatalogKeyPrefix)
              ? itemKey.substring(kCatalogKeyPrefix.length)
              : ''),
      labTemplateIds: templateIds,
      snCodes: asStringList(json['sn_codes'] ?? json['sns']),
      name: firstString(json, const ['name', 'display_name', 'product_name']) ?? '',
      mpn: firstString(json, const ['mpn', 'lab_mpn', 'part_number']) ?? '',
      brand: firstString(json, const ['brand', 'lab_brand', 'brand_name']) ?? '',
      packageName: firstString(json, const ['package', 'lab_package', 'footprint']) ?? '',
      categoryId: firstInt(json, const ['category_id', 'categ_id', 'catalog_id']),
      categoryName:
          firstString(json, const ['category_name', 'category', 'categ_name']) ?? '',
      imageUrl: asAssetReference(
        firstValue(json, const ['image_url', 'thumb_url', 'thumbnail', 'image_file_url']),
      ),
      imageAlternateUrl: asAssetReference(
        firstValue(json, const [
          'original_url',
          'image_original_url',
          'image_public_url',
          'public_image_url',
        ]),
      ),
      labQuantity: firstDouble(json, const ['lab_quantity', 'quantity', 'qty']) ?? 0,
      labAvailableQuantity: firstDouble(
            json,
            const ['lab_available_quantity', 'available_quantity', 'free_quantity'],
          ) ??
          firstDouble(json, const ['lab_quantity', 'quantity', 'qty']) ??
          0,
      hasStock: firstBool(json, const ['has_stock', 'in_stock']) ??
          (firstDouble(json, const ['lab_quantity', 'quantity', 'qty']) ?? 0) > 0,
      catalogStock:
          firstDouble(json, const ['catalog_stock', 'mall_stock', 'stock']),
      parameters: UnifiedParameter.listFrom(json['parameters'] ?? json['params']),
      revision: firstString(json, const ['revision', 'inventory_revision']) ?? '',
      raw: json,
    );
  }

  /// Quantity in the shape the UI prints (no trailing `.0` for whole numbers).
  static String formatQuantity(double value) {
    if (value == value.roundToDouble()) return value.toInt().toString();
    return value.toStringAsFixed(2);
  }

  String get labQuantityLabel => formatQuantity(labQuantity);

  String get catalogStockLabel => catalogStock == null
      ? '未采集'
      : '立创现货 ${formatQuantity(catalogStock!)}';
}

/// One catalog parameter (`容值 = 10uF`).
class UnifiedParameter {
  const UnifiedParameter({
    required this.code,
    required this.name,
    required this.value,
  });

  /// Stable parameter code used by the filter facet, e.g. `param_11032_n`.
  final String code;

  /// Human name, e.g. `容值`.
  final String name;

  /// Displayed value, e.g. `10uF`.
  final String value;

  /// Label shown in the detail list / label designer.
  String get label => name.isNotEmpty ? name : code;

  factory UnifiedParameter.fromJson(Map<String, dynamic> json) {
    return UnifiedParameter(
      code: firstString(
            json,
            const ['code', 'parameterCode', 'parameter_code', 'key'],
          ) ??
          '',
      name: firstString(
            json,
            const ['name', 'parameterName', 'parameter_name', 'label'],
          ) ??
          '',
      value: firstString(
            json,
            const [
              'value',
              'parameterDetailValue',
              'parameter_value',
              'display_value',
              'text',
            ],
          ) ??
          '',
    );
  }

  /// Reads either a list of parameter objects or a `{code: value}` map.
  static List<UnifiedParameter> listFrom(Object? value) {
    if (value is Map) {
      return asMap(value)
          .entries
          .map(
            (entry) => UnifiedParameter(
              code: entry.key,
              name: '',
              value: asString(entry.value) ?? '',
            ),
          )
          .where((parameter) => parameter.value.isNotEmpty)
          .toList();
    }
    return asMapList(value)
        .map(UnifiedParameter.fromJson)
        .where((parameter) => parameter.value.isNotEmpty || parameter.name.isNotEmpty)
        .toList();
  }
}

/// One page of `/lab/api/catalog/search`.
class CatalogSearchPage {
  const CatalogSearchPage({
    required this.items,
    required this.nextCursor,
    required this.total,
    required this.inventoryRevision,
    required this.catalogRevision,
    this.raw = const <String, dynamic>{},
  });

  final List<UnifiedItem> items;

  /// Opaque keyset cursor for the next page, or `null` when the list is done.
  final String? nextCursor;

  /// Total number of matching rows across the whole captured library.
  final int total;

  final String inventoryRevision;
  final String catalogRevision;

  final Map<String, dynamic> raw;

  bool get hasMore => nextCursor != null && nextCursor!.isNotEmpty;

  factory CatalogSearchPage.fromJson(Map<String, dynamic> json) {
    return CatalogSearchPage(
      items: asMapList(json['items']).map(UnifiedItem.fromJson).toList(),
      nextCursor: asString(json['next_cursor']),
      total: firstInt(json, const ['total', 'total_estimate', 'total_count']) ?? 0,
      inventoryRevision:
          firstString(json, const ['inventory_revision']) ?? '',
      catalogRevision: firstString(json, const ['catalog_revision']) ?? '',
      raw: json,
    );
  }

  static const CatalogSearchPage empty = CatalogSearchPage(
    items: <UnifiedItem>[],
    nextCursor: null,
    total: 0,
    inventoryRevision: '',
    catalogRevision: '',
  );
}

/// One selectable value of a filter facet.
class FacetOption {
  const FacetOption({required this.value, required this.label, this.count});

  final String value;
  final String label;
  final int? count;

  String get display => count == null ? label : '$label ($count)';

  /// Accepts `"0805"`, `{"value":"0805","count":12}` and
  /// `{"code":"VISHAY","label":"VISHAY(威世)","count":9}`.
  factory FacetOption.fromJson(Object? value) {
    if (value is Map) {
      final json = asMap(value);
      final raw = firstString(
            json,
            const ['value', 'code', 'package', 'brand', 'brand_code', 'id', 'name'],
          ) ??
          '';
      final label = firstString(
            json,
            const ['label', 'display_name', 'name', 'brand', 'value'],
          ) ??
          raw;
      return FacetOption(
        value: raw,
        label: label.isEmpty ? raw : label,
        count: firstInt(json, const ['count', 'product_count', 'total']),
      );
    }
    final text = asString(value) ?? '';
    return FacetOption(value: text, label: text);
  }
}

/// One parameter family in the facet response, with its available values.
class ParameterFacet {
  const ParameterFacet({
    required this.code,
    required this.name,
    required this.values,
  });

  final String code;
  final String name;
  final List<FacetOption> values;

  String get label => name.isNotEmpty ? name : code;

  factory ParameterFacet.fromJson(Map<String, dynamic> json) {
    final code =
        firstString(json, const ['code', 'parameterCode', 'parameter_code', 'key']) ??
            '';
    return ParameterFacet(
      code: code,
      name: firstString(
            json,
            const ['name', 'parameterName', 'parameter_name', 'label'],
          ) ??
          code,
      values: asList(json['values'] ?? json['options'])
          .map(FacetOption.fromJson)
          .where((option) => option.value.isNotEmpty)
          .toList(),
    );
  }
}

/// `/lab/api/catalog/facets` response: everything the operator may filter by.
class CatalogFacets {
  const CatalogFacets({
    required this.brands,
    required this.packages,
    required this.parameters,
    this.raw = const <String, dynamic>{},
  });

  final List<FacetOption> brands;
  final List<FacetOption> packages;
  final List<ParameterFacet> parameters;
  final Map<String, dynamic> raw;

  bool get isEmpty =>
      brands.isEmpty && packages.isEmpty && parameters.isEmpty;

  static const CatalogFacets empty = CatalogFacets(
    brands: <FacetOption>[],
    packages: <FacetOption>[],
    parameters: <ParameterFacet>[],
  );

  factory CatalogFacets.fromJson(Map<String, dynamic> json) {
    // Some servers group the parameter families by parameter code instead.
    final parameters = <ParameterFacet>[];
    final parameterNode = json['parameters'];
    if (parameterNode is Map) {
      asMap(parameterNode).forEach((key, value) {
        if (value is Map) {
          parameters.add(ParameterFacet.fromJson(asMap(value)));
        } else {
          parameters.add(
            ParameterFacet(
              code: key,
              name: key,
              values: asList(value)
                  .map(FacetOption.fromJson)
                  .where((option) => option.value.isNotEmpty)
                  .toList(),
            ),
          );
        }
      });
    } else {
      parameters.addAll(
        asMapList(parameterNode).map(ParameterFacet.fromJson),
      );
    }

    return CatalogFacets(
      brands: asList(json['brands'])
          .map(FacetOption.fromJson)
          .where((option) => option.value.isNotEmpty)
          .toList(),
      packages: asList(json['packages'])
          .map(FacetOption.fromJson)
          .where((option) => option.value.isNotEmpty)
          .toList(),
      parameters: parameters
          .where((facet) => facet.code.isNotEmpty && facet.values.isNotEmpty)
          .toList(),
      raw: json,
    );
  }
}

/// One node of the catalog category tree (`/lab/api/catalog/categories`).
///
/// IMPORTANT (root-decided): `category_id` is the POSTGRES tree id used by the
/// `category_id` filter of `/lab/api/catalog/search`. The mall's own
/// `catalog_id` is a DIFFERENT number that lives in the same category JSON, so
/// it is kept in [catalogId] for reference only and is never substituted for
/// [id]. `parentId` is a Postgres tree id as well - building the tree with a
/// mall id would silently drop branches.
class CatalogCategory {
  const CatalogCategory({
    required this.id,
    required this.name,
    this.catalogId,
    this.parentId,
    this.level,
    this.productCount,
    this.children = const <CatalogCategory>[],
  });

  /// Postgres category-tree id (the value the search filter accepts).
  final int id;

  /// The captured mall catalog id (`catalog_id`) - reference only.
  final int? catalogId;

  final String name;

  /// Postgres id of the parent node.
  final int? parentId;

  final int? level;
  final int? productCount;
  final List<CatalogCategory> children;

  bool get hasChildren => children.isNotEmpty;

  String get display =>
      productCount == null ? name : '$name (${productCount!})';

  /// Same node with a different child list (the tree builder never mutates).
  CatalogCategory withChildren(List<CatalogCategory> newChildren) {
    return CatalogCategory(
      id: id,
      name: name,
      catalogId: catalogId,
      parentId: parentId,
      level: level,
      productCount: productCount,
      children: newChildren,
    );
  }

  factory CatalogCategory.fromJson(Map<String, dynamic> json) {
    return CatalogCategory(
      // `catalog_id` is deliberately NOT a fallback here.
      id: firstInt(json, const ['id', 'category_id']) ?? 0,
      catalogId: firstInt(json, const ['catalog_id']),
      name: firstString(json, const ['name', 'catalogName', 'label']) ?? '',
      parentId: firstInt(json, const ['parent_id', 'parentId']),
      level: firstInt(json, const ['level', 'depth']),
      productCount:
          firstInt(json, const ['product_count', 'groupProductCount', 'count']),
      children: asList(json['children'])
          .map((child) => CatalogCategory.fromJson(asMap(child)))
          .toList(),
    );
  }

  /// Builds a tree from either a nested payload or a flat parent/child list.
  ///
  /// A node whose `parent_id` points at a node that is not in the payload is
  /// promoted to a root instead of disappearing - a partial category list must
  /// still be navigable. The input nodes are not mutated.
  static List<CatalogCategory> forest(List<CatalogCategory> nodes) {
    final byId = <int, CatalogCategory>{};
    for (final node in nodes) {
      if (node.id != 0) byId[node.id] = node;
    }

    final childrenById = <int, List<CatalogCategory>>{};
    final roots = <CatalogCategory>[];
    for (final node in nodes) {
      final parent = node.parentId == null ? null : byId[node.parentId];
      if (parent == null || parent.id == node.id) {
        roots.add(node);
        continue;
      }
      childrenById.putIfAbsent(parent.id, () => <CatalogCategory>[]).add(node);
    }

    List<CatalogCategory> attach(CatalogCategory node) {
      final flat = childrenById[node.id] ?? const <CatalogCategory>[];
      final nested = node.children;
      if (flat.isEmpty && nested.isEmpty) return const <CatalogCategory>[];

      final result = <CatalogCategory>[];
      for (final child in nested) {
        result.add(child.withChildren(attach(child)));
      }
      for (final child in flat) {
        if (result.any((existing) => existing.id == child.id)) continue;
        result.add(child.withChildren(attach(child)));
      }
      return result;
    }

    return roots.map((node) => node.withChildren(attach(node))).toList();
  }
}
