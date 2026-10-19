import 'package:freezed_annotation/freezed_annotation.dart';
import 'package:json_annotation/json_annotation.dart';

import 'odoo_json.dart';

part 'product.freezed.dart';
part 'product.g.dart';

/// Product (Component) mapped from `product.template` in Odoo.
///
/// Every field Odoo can answer with `false` (empty Char / Text / Date /
/// Many2one) is routed through a converter from `odoo_json.dart`; decoding a
/// raw `false` into a typed field would otherwise throw and break the list and
/// detail screens.
@freezed
abstract class Product with _$Product {
  const factory Product({
    required int id,
    required String name,

    /// Internal reference code (Odoo `default_code`); empty when unset.
    @JsonKey(fromJson: odooString) @Default('') String default_code,

    /// Laboratory SN code (LAB-XXXXXX). Empty when Odoo has none - it is not
    /// guaranteed to exist on products created before the lab module landed.
    @JsonKey(fromJson: odooString) @Default('') String lab_sn,

    /// LCSC C code (e.g. C123456); null for manual entries.
    @JsonKey(fromJson: odooStringOrNull) String? lab_lcsc_code,

    /// Manufacturer Part Number.
    @JsonKey(fromJson: odooStringOrNull) String? lab_mpn,

    /// Brand name.
    @JsonKey(fromJson: odooStringOrNull) String? lab_brand,

    /// Package type (e.g. 0805, SOP8).
    @JsonKey(fromJson: odooStringOrNull) String? lab_package,

    /// Component description.
    @JsonKey(fromJson: odooStringOrNull) String? lab_description,

    /// Specifications as a JSON string.
    @JsonKey(fromJson: odooStringOrNull) String? lab_specifications,

    /// Datasheet URL.
    @JsonKey(fromJson: odooStringOrNull) String? lab_datasheet_url,

    /// Source URL (e.g. the LCSC product page).
    @JsonKey(fromJson: odooStringOrNull) String? lab_source_url,

    /// Category as an Odoo Many2one `[id, displayName]`; `false` becomes null.
    @JsonKey(fromJson: odooListOrNull) List<dynamic>? categ_id,

    /// Product type (consu, product, service).
    @Default('consu') String type,

    /// Base64 encoded image (Odoo `image_1920`).
    @JsonKey(fromJson: odooStringOrNull) String? image_1920,

    /// Quantity on hand (computed from `stock.quant`).
    @JsonKey(fromJson: odooDouble) @Default(0.0) double qty_available,

    /// Active status. `false` is a meaningful value here and is preserved -
    /// see the note at the top of `odoo_json.dart`.
    @JsonKey(fromJson: odooBool) @Default(true) bool active,

    /// Created date.
    @JsonKey(fromJson: odooDateTimeOrNull) DateTime? create_date,

    /// Last write date.
    @JsonKey(fromJson: odooDateTimeOrNull) DateTime? write_date,
  }) = _Product;

  factory Product.fromJson(Map<String, dynamic> json) =>
      _$ProductFromJson(json);
}

/// Simplified product for list views.
@freezed
abstract class ProductSummary with _$ProductSummary {
  const factory ProductSummary({
    required int id,
    @JsonKey(fromJson: odooString) @Default('') String name,
    @JsonKey(fromJson: odooString) @Default('') String lab_sn,
    @JsonKey(fromJson: odooStringOrNull) String? lab_lcsc_code,
    @JsonKey(fromJson: odooStringOrNull) String? lab_mpn,
    @JsonKey(fromJson: odooStringOrNull) String? lab_package,
    @JsonKey(fromJson: odooDouble) @Default(0.0) double qty_available,
  }) = _ProductSummary;

  factory ProductSummary.fromJson(Map<String, dynamic> json) =>
      _$ProductSummaryFromJson(json);
}

/// Builds a [ProductSummary] from a full [Product].
///
/// Deliberately an extension rather than an extra factory constructor inside
/// the `@freezed` class: freezed only models one primary constructor per
/// class, and a hand-written additional factory on a freezed class is a
/// code-generation hazard.
extension ProductToSummary on Product {
  ProductSummary toSummary() => ProductSummary(
        id: id,
        name: name,
        lab_sn: lab_sn,
        lab_lcsc_code: lab_lcsc_code,
        lab_mpn: lab_mpn,
        lab_package: lab_package,
        qty_available: qty_available,
      );
}
