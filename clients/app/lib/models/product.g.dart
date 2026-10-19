// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'product.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_Product _$ProductFromJson(Map<String, dynamic> json) => _Product(
  id: (json['id'] as num).toInt(),
  name: json['name'] as String,
  default_code: json['default_code'] == null
      ? ''
      : odooString(json['default_code']),
  lab_sn: json['lab_sn'] == null ? '' : odooString(json['lab_sn']),
  lab_lcsc_code: odooStringOrNull(json['lab_lcsc_code']),
  lab_mpn: odooStringOrNull(json['lab_mpn']),
  lab_brand: odooStringOrNull(json['lab_brand']),
  lab_package: odooStringOrNull(json['lab_package']),
  lab_description: odooStringOrNull(json['lab_description']),
  lab_specifications: odooStringOrNull(json['lab_specifications']),
  lab_datasheet_url: odooStringOrNull(json['lab_datasheet_url']),
  lab_source_url: odooStringOrNull(json['lab_source_url']),
  categ_id: odooListOrNull(json['categ_id']),
  type: json['type'] as String? ?? 'consu',
  image_1920: odooStringOrNull(json['image_1920']),
  qty_available: json['qty_available'] == null
      ? 0.0
      : odooDouble(json['qty_available']),
  active: json['active'] == null ? true : odooBool(json['active']),
  create_date: odooDateTimeOrNull(json['create_date']),
  write_date: odooDateTimeOrNull(json['write_date']),
);

Map<String, dynamic> _$ProductToJson(_Product instance) => <String, dynamic>{
  'id': instance.id,
  'name': instance.name,
  'default_code': instance.default_code,
  'lab_sn': instance.lab_sn,
  'lab_lcsc_code': instance.lab_lcsc_code,
  'lab_mpn': instance.lab_mpn,
  'lab_brand': instance.lab_brand,
  'lab_package': instance.lab_package,
  'lab_description': instance.lab_description,
  'lab_specifications': instance.lab_specifications,
  'lab_datasheet_url': instance.lab_datasheet_url,
  'lab_source_url': instance.lab_source_url,
  'categ_id': instance.categ_id,
  'type': instance.type,
  'image_1920': instance.image_1920,
  'qty_available': instance.qty_available,
  'active': instance.active,
  'create_date': instance.create_date?.toIso8601String(),
  'write_date': instance.write_date?.toIso8601String(),
};

_ProductSummary _$ProductSummaryFromJson(Map<String, dynamic> json) =>
    _ProductSummary(
      id: (json['id'] as num).toInt(),
      name: json['name'] == null ? '' : odooString(json['name']),
      lab_sn: json['lab_sn'] == null ? '' : odooString(json['lab_sn']),
      lab_lcsc_code: odooStringOrNull(json['lab_lcsc_code']),
      lab_mpn: odooStringOrNull(json['lab_mpn']),
      lab_package: odooStringOrNull(json['lab_package']),
      qty_available: json['qty_available'] == null
          ? 0.0
          : odooDouble(json['qty_available']),
    );

Map<String, dynamic> _$ProductSummaryToJson(_ProductSummary instance) =>
    <String, dynamic>{
      'id': instance.id,
      'name': instance.name,
      'lab_sn': instance.lab_sn,
      'lab_lcsc_code': instance.lab_lcsc_code,
      'lab_mpn': instance.lab_mpn,
      'lab_package': instance.lab_package,
      'qty_available': instance.qty_available,
    };
