// GENERATED CODE - DO NOT MODIFY BY HAND
// coverage:ignore-file
// ignore_for_file: type=lint, type=warning, deprecated_member_use, deprecated_member_use_from_same_package
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'product.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

// GENERATED CODE - DO NOT MODIFY BY HAND
// dart format off
T _$identity<T>(T value) => value;

/// @nodoc
mixin _$Product {

 int get id; String get name;/// Internal reference code (Odoo `default_code`); empty when unset.
@JsonKey(fromJson: odooString) String get default_code;/// Laboratory SN code (LAB-XXXXXX). Empty when Odoo has none - it is not
/// guaranteed to exist on products created before the lab module landed.
@JsonKey(fromJson: odooString) String get lab_sn;/// LCSC C code (e.g. C123456); null for manual entries.
@JsonKey(fromJson: odooStringOrNull) String? get lab_lcsc_code;/// Manufacturer Part Number.
@JsonKey(fromJson: odooStringOrNull) String? get lab_mpn;/// Brand name.
@JsonKey(fromJson: odooStringOrNull) String? get lab_brand;/// Package type (e.g. 0805, SOP8).
@JsonKey(fromJson: odooStringOrNull) String? get lab_package;/// Component description.
@JsonKey(fromJson: odooStringOrNull) String? get lab_description;/// Specifications as a JSON string.
@JsonKey(fromJson: odooStringOrNull) String? get lab_specifications;/// Datasheet URL.
@JsonKey(fromJson: odooStringOrNull) String? get lab_datasheet_url;/// Source URL (e.g. the LCSC product page).
@JsonKey(fromJson: odooStringOrNull) String? get lab_source_url;/// Category as an Odoo Many2one `[id, displayName]`; `false` becomes null.
@JsonKey(fromJson: odooListOrNull) List<dynamic>? get categ_id;/// Product type (consu, product, service).
 String get type;/// Base64 encoded image (Odoo `image_1920`).
@JsonKey(fromJson: odooStringOrNull) String? get image_1920;/// Quantity on hand (computed from `stock.quant`).
@JsonKey(fromJson: odooDouble) double get qty_available;/// Active status. `false` is a meaningful value here and is preserved -
/// see the note at the top of `odoo_json.dart`.
@JsonKey(fromJson: odooBool) bool get active;/// Created date.
@JsonKey(fromJson: odooDateTimeOrNull) DateTime? get create_date;/// Last write date.
@JsonKey(fromJson: odooDateTimeOrNull) DateTime? get write_date;
/// Create a copy of Product
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$ProductCopyWith<Product> get copyWith => _$ProductCopyWithImpl<Product>(this as Product, _$identity);

  /// Serializes this Product to a JSON map.
  Map<String, dynamic> toJson();


@override
bool operator ==(Object other) {
  final _this = this as Product;
  return identical(this, other) || (other.runtimeType == runtimeType&&other is Product&&(identical(other.id, _this.id) || other.id == _this.id)&&(identical(other.name, _this.name) || other.name == _this.name)&&(identical(other.default_code, _this.default_code) || other.default_code == _this.default_code)&&(identical(other.lab_sn, _this.lab_sn) || other.lab_sn == _this.lab_sn)&&(identical(other.lab_lcsc_code, _this.lab_lcsc_code) || other.lab_lcsc_code == _this.lab_lcsc_code)&&(identical(other.lab_mpn, _this.lab_mpn) || other.lab_mpn == _this.lab_mpn)&&(identical(other.lab_brand, _this.lab_brand) || other.lab_brand == _this.lab_brand)&&(identical(other.lab_package, _this.lab_package) || other.lab_package == _this.lab_package)&&(identical(other.lab_description, _this.lab_description) || other.lab_description == _this.lab_description)&&(identical(other.lab_specifications, _this.lab_specifications) || other.lab_specifications == _this.lab_specifications)&&(identical(other.lab_datasheet_url, _this.lab_datasheet_url) || other.lab_datasheet_url == _this.lab_datasheet_url)&&(identical(other.lab_source_url, _this.lab_source_url) || other.lab_source_url == _this.lab_source_url)&&const DeepCollectionEquality().equals(other.categ_id, _this.categ_id)&&(identical(other.type, _this.type) || other.type == _this.type)&&(identical(other.image_1920, _this.image_1920) || other.image_1920 == _this.image_1920)&&(identical(other.qty_available, _this.qty_available) || other.qty_available == _this.qty_available)&&(identical(other.active, _this.active) || other.active == _this.active)&&(identical(other.create_date, _this.create_date) || other.create_date == _this.create_date)&&(identical(other.write_date, _this.write_date) || other.write_date == _this.write_date));
}

@JsonKey(includeFromJson: false, includeToJson: false)
@override
int get hashCode {
  final _this = this as Product;
  return Object.hashAll([runtimeType,_this.id,_this.name,_this.default_code,_this.lab_sn,_this.lab_lcsc_code,_this.lab_mpn,_this.lab_brand,_this.lab_package,_this.lab_description,_this.lab_specifications,_this.lab_datasheet_url,_this.lab_source_url,const DeepCollectionEquality().hash(_this.categ_id),_this.type,_this.image_1920,_this.qty_available,_this.active,_this.create_date,_this.write_date]);
}

@override
String toString() {
  final _this = this as Product;
  return 'Product(id: ${_this.id}, name: ${_this.name}, default_code: ${_this.default_code}, lab_sn: ${_this.lab_sn}, lab_lcsc_code: ${_this.lab_lcsc_code}, lab_mpn: ${_this.lab_mpn}, lab_brand: ${_this.lab_brand}, lab_package: ${_this.lab_package}, lab_description: ${_this.lab_description}, lab_specifications: ${_this.lab_specifications}, lab_datasheet_url: ${_this.lab_datasheet_url}, lab_source_url: ${_this.lab_source_url}, categ_id: ${_this.categ_id}, type: ${_this.type}, image_1920: ${_this.image_1920}, qty_available: ${_this.qty_available}, active: ${_this.active}, create_date: ${_this.create_date}, write_date: ${_this.write_date})';
}


}

/// @nodoc
abstract mixin class $ProductCopyWith<$Res>  {
  factory $ProductCopyWith(Product value, $Res Function(Product) _then) = _$ProductCopyWithImpl;
@useResult
$Res call({
 int id, String name,@JsonKey(fromJson: odooString) String default_code,@JsonKey(fromJson: odooString) String lab_sn,@JsonKey(fromJson: odooStringOrNull) String? lab_lcsc_code,@JsonKey(fromJson: odooStringOrNull) String? lab_mpn,@JsonKey(fromJson: odooStringOrNull) String? lab_brand,@JsonKey(fromJson: odooStringOrNull) String? lab_package,@JsonKey(fromJson: odooStringOrNull) String? lab_description,@JsonKey(fromJson: odooStringOrNull) String? lab_specifications,@JsonKey(fromJson: odooStringOrNull) String? lab_datasheet_url,@JsonKey(fromJson: odooStringOrNull) String? lab_source_url,@JsonKey(fromJson: odooListOrNull) List<dynamic>? categ_id, String type,@JsonKey(fromJson: odooStringOrNull) String? image_1920,@JsonKey(fromJson: odooDouble) double qty_available,@JsonKey(fromJson: odooBool) bool active,@JsonKey(fromJson: odooDateTimeOrNull) DateTime? create_date,@JsonKey(fromJson: odooDateTimeOrNull) DateTime? write_date
});




}
/// @nodoc
class _$ProductCopyWithImpl<$Res>
    implements $ProductCopyWith<$Res> {
  _$ProductCopyWithImpl(this._self, this._then);

  final Product _self;
  final $Res Function(Product) _then;

/// Create a copy of Product
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') @override $Res call({Object? id = null,Object? name = null,Object? default_code = null,Object? lab_sn = null,Object? lab_lcsc_code = freezed,Object? lab_mpn = freezed,Object? lab_brand = freezed,Object? lab_package = freezed,Object? lab_description = freezed,Object? lab_specifications = freezed,Object? lab_datasheet_url = freezed,Object? lab_source_url = freezed,Object? categ_id = freezed,Object? type = null,Object? image_1920 = freezed,Object? qty_available = null,Object? active = null,Object? create_date = freezed,Object? write_date = freezed,}) {
  return _then(Product(
id: null == id ? _self.id : id // ignore: cast_nullable_to_non_nullable
as int,name: null == name ? _self.name : name // ignore: cast_nullable_to_non_nullable
as String,default_code: null == default_code ? _self.default_code : default_code // ignore: cast_nullable_to_non_nullable
as String,lab_sn: null == lab_sn ? _self.lab_sn : lab_sn // ignore: cast_nullable_to_non_nullable
as String,lab_lcsc_code: freezed == lab_lcsc_code ? _self.lab_lcsc_code : lab_lcsc_code // ignore: cast_nullable_to_non_nullable
as String?,lab_mpn: freezed == lab_mpn ? _self.lab_mpn : lab_mpn // ignore: cast_nullable_to_non_nullable
as String?,lab_brand: freezed == lab_brand ? _self.lab_brand : lab_brand // ignore: cast_nullable_to_non_nullable
as String?,lab_package: freezed == lab_package ? _self.lab_package : lab_package // ignore: cast_nullable_to_non_nullable
as String?,lab_description: freezed == lab_description ? _self.lab_description : lab_description // ignore: cast_nullable_to_non_nullable
as String?,lab_specifications: freezed == lab_specifications ? _self.lab_specifications : lab_specifications // ignore: cast_nullable_to_non_nullable
as String?,lab_datasheet_url: freezed == lab_datasheet_url ? _self.lab_datasheet_url : lab_datasheet_url // ignore: cast_nullable_to_non_nullable
as String?,lab_source_url: freezed == lab_source_url ? _self.lab_source_url : lab_source_url // ignore: cast_nullable_to_non_nullable
as String?,categ_id: freezed == categ_id ? _self.categ_id : categ_id // ignore: cast_nullable_to_non_nullable
as List<dynamic>?,type: null == type ? _self.type : type // ignore: cast_nullable_to_non_nullable
as String,image_1920: freezed == image_1920 ? _self.image_1920 : image_1920 // ignore: cast_nullable_to_non_nullable
as String?,qty_available: null == qty_available ? _self.qty_available : qty_available // ignore: cast_nullable_to_non_nullable
as double,active: null == active ? _self.active : active // ignore: cast_nullable_to_non_nullable
as bool,create_date: freezed == create_date ? _self.create_date : create_date // ignore: cast_nullable_to_non_nullable
as DateTime?,write_date: freezed == write_date ? _self.write_date : write_date // ignore: cast_nullable_to_non_nullable
as DateTime?,
  ));
}

}


/// Adds pattern-matching-related methods to [Product].
extension ProductPatterns on Product {
/// A variant of `map` that fallback to returning `orElse`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeMap<TResult extends Object?>(TResult Function( _Product value)?  $default,{required TResult orElse(),}){
final _that = this;
switch (_that) {
case _Product() when $default != null:
return $default(_that);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// Callbacks receives the raw object, upcasted.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case final Subclass2 value:
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult map<TResult extends Object?>(TResult Function( _Product value)  $default,){
final _that = this;
switch (_that) {
case _Product():
return $default(_that);case _:
  throw StateError('Unexpected subclass');

}
}
/// A variant of `map` that fallback to returning `null`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? mapOrNull<TResult extends Object?>(TResult? Function( _Product value)?  $default,){
final _that = this;
switch (_that) {
case _Product() when $default != null:
return $default(_that);case _:
  return null;

}
}
/// A variant of `when` that fallback to an `orElse` callback.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeWhen<TResult extends Object?>(TResult Function( int id,  String name, @JsonKey(fromJson: odooString)  String default_code, @JsonKey(fromJson: odooString)  String lab_sn, @JsonKey(fromJson: odooStringOrNull)  String? lab_lcsc_code, @JsonKey(fromJson: odooStringOrNull)  String? lab_mpn, @JsonKey(fromJson: odooStringOrNull)  String? lab_brand, @JsonKey(fromJson: odooStringOrNull)  String? lab_package, @JsonKey(fromJson: odooStringOrNull)  String? lab_description, @JsonKey(fromJson: odooStringOrNull)  String? lab_specifications, @JsonKey(fromJson: odooStringOrNull)  String? lab_datasheet_url, @JsonKey(fromJson: odooStringOrNull)  String? lab_source_url, @JsonKey(fromJson: odooListOrNull)  List<dynamic>? categ_id,  String type, @JsonKey(fromJson: odooStringOrNull)  String? image_1920, @JsonKey(fromJson: odooDouble)  double qty_available, @JsonKey(fromJson: odooBool)  bool active, @JsonKey(fromJson: odooDateTimeOrNull)  DateTime? create_date, @JsonKey(fromJson: odooDateTimeOrNull)  DateTime? write_date)?  $default,{required TResult orElse(),}) {final _that = this;
switch (_that) {
case _Product() when $default != null:
return $default(_that.id,_that.name,_that.default_code,_that.lab_sn,_that.lab_lcsc_code,_that.lab_mpn,_that.lab_brand,_that.lab_package,_that.lab_description,_that.lab_specifications,_that.lab_datasheet_url,_that.lab_source_url,_that.categ_id,_that.type,_that.image_1920,_that.qty_available,_that.active,_that.create_date,_that.write_date);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// As opposed to `map`, this offers destructuring.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case Subclass2(:final field2):
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult when<TResult extends Object?>(TResult Function( int id,  String name, @JsonKey(fromJson: odooString)  String default_code, @JsonKey(fromJson: odooString)  String lab_sn, @JsonKey(fromJson: odooStringOrNull)  String? lab_lcsc_code, @JsonKey(fromJson: odooStringOrNull)  String? lab_mpn, @JsonKey(fromJson: odooStringOrNull)  String? lab_brand, @JsonKey(fromJson: odooStringOrNull)  String? lab_package, @JsonKey(fromJson: odooStringOrNull)  String? lab_description, @JsonKey(fromJson: odooStringOrNull)  String? lab_specifications, @JsonKey(fromJson: odooStringOrNull)  String? lab_datasheet_url, @JsonKey(fromJson: odooStringOrNull)  String? lab_source_url, @JsonKey(fromJson: odooListOrNull)  List<dynamic>? categ_id,  String type, @JsonKey(fromJson: odooStringOrNull)  String? image_1920, @JsonKey(fromJson: odooDouble)  double qty_available, @JsonKey(fromJson: odooBool)  bool active, @JsonKey(fromJson: odooDateTimeOrNull)  DateTime? create_date, @JsonKey(fromJson: odooDateTimeOrNull)  DateTime? write_date)  $default,) {final _that = this;
switch (_that) {
case _Product():
return $default(_that.id,_that.name,_that.default_code,_that.lab_sn,_that.lab_lcsc_code,_that.lab_mpn,_that.lab_brand,_that.lab_package,_that.lab_description,_that.lab_specifications,_that.lab_datasheet_url,_that.lab_source_url,_that.categ_id,_that.type,_that.image_1920,_that.qty_available,_that.active,_that.create_date,_that.write_date);case _:
  throw StateError('Unexpected subclass');

}
}
/// A variant of `when` that fallback to returning `null`
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? whenOrNull<TResult extends Object?>(TResult? Function( int id,  String name, @JsonKey(fromJson: odooString)  String default_code, @JsonKey(fromJson: odooString)  String lab_sn, @JsonKey(fromJson: odooStringOrNull)  String? lab_lcsc_code, @JsonKey(fromJson: odooStringOrNull)  String? lab_mpn, @JsonKey(fromJson: odooStringOrNull)  String? lab_brand, @JsonKey(fromJson: odooStringOrNull)  String? lab_package, @JsonKey(fromJson: odooStringOrNull)  String? lab_description, @JsonKey(fromJson: odooStringOrNull)  String? lab_specifications, @JsonKey(fromJson: odooStringOrNull)  String? lab_datasheet_url, @JsonKey(fromJson: odooStringOrNull)  String? lab_source_url, @JsonKey(fromJson: odooListOrNull)  List<dynamic>? categ_id,  String type, @JsonKey(fromJson: odooStringOrNull)  String? image_1920, @JsonKey(fromJson: odooDouble)  double qty_available, @JsonKey(fromJson: odooBool)  bool active, @JsonKey(fromJson: odooDateTimeOrNull)  DateTime? create_date, @JsonKey(fromJson: odooDateTimeOrNull)  DateTime? write_date)?  $default,) {final _that = this;
switch (_that) {
case _Product() when $default != null:
return $default(_that.id,_that.name,_that.default_code,_that.lab_sn,_that.lab_lcsc_code,_that.lab_mpn,_that.lab_brand,_that.lab_package,_that.lab_description,_that.lab_specifications,_that.lab_datasheet_url,_that.lab_source_url,_that.categ_id,_that.type,_that.image_1920,_that.qty_available,_that.active,_that.create_date,_that.write_date);case _:
  return null;

}
}

}

/// @nodoc
@JsonSerializable()

class _Product implements Product {
  const _Product({required this.id, required this.name, @JsonKey(fromJson: odooString) this.default_code = '', @JsonKey(fromJson: odooString) this.lab_sn = '', @JsonKey(fromJson: odooStringOrNull) this.lab_lcsc_code, @JsonKey(fromJson: odooStringOrNull) this.lab_mpn, @JsonKey(fromJson: odooStringOrNull) this.lab_brand, @JsonKey(fromJson: odooStringOrNull) this.lab_package, @JsonKey(fromJson: odooStringOrNull) this.lab_description, @JsonKey(fromJson: odooStringOrNull) this.lab_specifications, @JsonKey(fromJson: odooStringOrNull) this.lab_datasheet_url, @JsonKey(fromJson: odooStringOrNull) this.lab_source_url, @JsonKey(fromJson: odooListOrNull)  List<dynamic>? categ_id, this.type = 'consu', @JsonKey(fromJson: odooStringOrNull) this.image_1920, @JsonKey(fromJson: odooDouble) this.qty_available = 0.0, @JsonKey(fromJson: odooBool) this.active = true, @JsonKey(fromJson: odooDateTimeOrNull) this.create_date, @JsonKey(fromJson: odooDateTimeOrNull) this.write_date}): _categ_id = categ_id;
  factory _Product.fromJson(Map<String, dynamic> json) => _$ProductFromJson(json);

@override final  int id;
@override final  String name;
/// Internal reference code (Odoo `default_code`); empty when unset.
@override@JsonKey(fromJson: odooString) final  String default_code;
/// Laboratory SN code (LAB-XXXXXX). Empty when Odoo has none - it is not
/// guaranteed to exist on products created before the lab module landed.
@override@JsonKey(fromJson: odooString) final  String lab_sn;
/// LCSC C code (e.g. C123456); null for manual entries.
@override@JsonKey(fromJson: odooStringOrNull) final  String? lab_lcsc_code;
/// Manufacturer Part Number.
@override@JsonKey(fromJson: odooStringOrNull) final  String? lab_mpn;
/// Brand name.
@override@JsonKey(fromJson: odooStringOrNull) final  String? lab_brand;
/// Package type (e.g. 0805, SOP8).
@override@JsonKey(fromJson: odooStringOrNull) final  String? lab_package;
/// Component description.
@override@JsonKey(fromJson: odooStringOrNull) final  String? lab_description;
/// Specifications as a JSON string.
@override@JsonKey(fromJson: odooStringOrNull) final  String? lab_specifications;
/// Datasheet URL.
@override@JsonKey(fromJson: odooStringOrNull) final  String? lab_datasheet_url;
/// Source URL (e.g. the LCSC product page).
@override@JsonKey(fromJson: odooStringOrNull) final  String? lab_source_url;
/// Category as an Odoo Many2one `[id, displayName]`; `false` becomes null.
 final  List<dynamic>? _categ_id;
/// Category as an Odoo Many2one `[id, displayName]`; `false` becomes null.
@override@JsonKey(fromJson: odooListOrNull) List<dynamic>? get categ_id {
  final value = _categ_id;
  if (value == null) return null;
  if (_categ_id is EqualUnmodifiableListView) return _categ_id;
  // ignore: implicit_dynamic_type
  return EqualUnmodifiableListView(value);
}

/// Product type (consu, product, service).
@override@JsonKey() final  String type;
/// Base64 encoded image (Odoo `image_1920`).
@override@JsonKey(fromJson: odooStringOrNull) final  String? image_1920;
/// Quantity on hand (computed from `stock.quant`).
@override@JsonKey(fromJson: odooDouble) final  double qty_available;
/// Active status. `false` is a meaningful value here and is preserved -
/// see the note at the top of `odoo_json.dart`.
@override@JsonKey(fromJson: odooBool) final  bool active;
/// Created date.
@override@JsonKey(fromJson: odooDateTimeOrNull) final  DateTime? create_date;
/// Last write date.
@override@JsonKey(fromJson: odooDateTimeOrNull) final  DateTime? write_date;

/// Create a copy of Product
/// with the given fields replaced by the non-null parameter values.
@override @JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
_$ProductCopyWith<_Product> get copyWith => __$ProductCopyWithImpl<_Product>(this, _$identity);

@override
Map<String, dynamic> toJson() {
  return _$ProductToJson(this, );
}

@override
bool operator ==(Object other) {
    return identical(this, other) || (other.runtimeType == runtimeType&&other is _Product&&(identical(other.id, id) || other.id == id)&&(identical(other.name, name) || other.name == name)&&(identical(other.default_code, default_code) || other.default_code == default_code)&&(identical(other.lab_sn, lab_sn) || other.lab_sn == lab_sn)&&(identical(other.lab_lcsc_code, lab_lcsc_code) || other.lab_lcsc_code == lab_lcsc_code)&&(identical(other.lab_mpn, lab_mpn) || other.lab_mpn == lab_mpn)&&(identical(other.lab_brand, lab_brand) || other.lab_brand == lab_brand)&&(identical(other.lab_package, lab_package) || other.lab_package == lab_package)&&(identical(other.lab_description, lab_description) || other.lab_description == lab_description)&&(identical(other.lab_specifications, lab_specifications) || other.lab_specifications == lab_specifications)&&(identical(other.lab_datasheet_url, lab_datasheet_url) || other.lab_datasheet_url == lab_datasheet_url)&&(identical(other.lab_source_url, lab_source_url) || other.lab_source_url == lab_source_url)&&const DeepCollectionEquality().equals(other.categ_id, _categ_id)&&(identical(other.type, type) || other.type == type)&&(identical(other.image_1920, image_1920) || other.image_1920 == image_1920)&&(identical(other.qty_available, qty_available) || other.qty_available == qty_available)&&(identical(other.active, active) || other.active == active)&&(identical(other.create_date, create_date) || other.create_date == create_date)&&(identical(other.write_date, write_date) || other.write_date == write_date));
}

@JsonKey(includeFromJson: false, includeToJson: false)
@override
int get hashCode {
    return Object.hashAll([runtimeType,id,name,default_code,lab_sn,lab_lcsc_code,lab_mpn,lab_brand,lab_package,lab_description,lab_specifications,lab_datasheet_url,lab_source_url,const DeepCollectionEquality().hash(_categ_id),type,image_1920,qty_available,active,create_date,write_date]);
}

@override
String toString() {
    return 'Product(id: $id, name: $name, default_code: $default_code, lab_sn: $lab_sn, lab_lcsc_code: $lab_lcsc_code, lab_mpn: $lab_mpn, lab_brand: $lab_brand, lab_package: $lab_package, lab_description: $lab_description, lab_specifications: $lab_specifications, lab_datasheet_url: $lab_datasheet_url, lab_source_url: $lab_source_url, categ_id: $categ_id, type: $type, image_1920: $image_1920, qty_available: $qty_available, active: $active, create_date: $create_date, write_date: $write_date)';
}


}

/// @nodoc
abstract mixin class _$ProductCopyWith<$Res> implements $ProductCopyWith<$Res> {
  factory _$ProductCopyWith(_Product value, $Res Function(_Product) _then) = __$ProductCopyWithImpl;
@override @useResult
$Res call({
 int id, String name,@JsonKey(fromJson: odooString) String default_code,@JsonKey(fromJson: odooString) String lab_sn,@JsonKey(fromJson: odooStringOrNull) String? lab_lcsc_code,@JsonKey(fromJson: odooStringOrNull) String? lab_mpn,@JsonKey(fromJson: odooStringOrNull) String? lab_brand,@JsonKey(fromJson: odooStringOrNull) String? lab_package,@JsonKey(fromJson: odooStringOrNull) String? lab_description,@JsonKey(fromJson: odooStringOrNull) String? lab_specifications,@JsonKey(fromJson: odooStringOrNull) String? lab_datasheet_url,@JsonKey(fromJson: odooStringOrNull) String? lab_source_url,@JsonKey(fromJson: odooListOrNull) List<dynamic>? categ_id, String type,@JsonKey(fromJson: odooStringOrNull) String? image_1920,@JsonKey(fromJson: odooDouble) double qty_available,@JsonKey(fromJson: odooBool) bool active,@JsonKey(fromJson: odooDateTimeOrNull) DateTime? create_date,@JsonKey(fromJson: odooDateTimeOrNull) DateTime? write_date
});




}
/// @nodoc
class __$ProductCopyWithImpl<$Res>
    implements _$ProductCopyWith<$Res> {
  __$ProductCopyWithImpl(this._self, this._then);

  final _Product _self;
  final $Res Function(_Product) _then;

/// Create a copy of Product
/// with the given fields replaced by the non-null parameter values.
@override @pragma('vm:prefer-inline') $Res call({Object? id = null,Object? name = null,Object? default_code = null,Object? lab_sn = null,Object? lab_lcsc_code = freezed,Object? lab_mpn = freezed,Object? lab_brand = freezed,Object? lab_package = freezed,Object? lab_description = freezed,Object? lab_specifications = freezed,Object? lab_datasheet_url = freezed,Object? lab_source_url = freezed,Object? categ_id = freezed,Object? type = null,Object? image_1920 = freezed,Object? qty_available = null,Object? active = null,Object? create_date = freezed,Object? write_date = freezed,}) {
  return _then(_Product(
id: null == id ? _self.id : id // ignore: cast_nullable_to_non_nullable
as int,name: null == name ? _self.name : name // ignore: cast_nullable_to_non_nullable
as String,default_code: null == default_code ? _self.default_code : default_code // ignore: cast_nullable_to_non_nullable
as String,lab_sn: null == lab_sn ? _self.lab_sn : lab_sn // ignore: cast_nullable_to_non_nullable
as String,lab_lcsc_code: freezed == lab_lcsc_code ? _self.lab_lcsc_code : lab_lcsc_code // ignore: cast_nullable_to_non_nullable
as String?,lab_mpn: freezed == lab_mpn ? _self.lab_mpn : lab_mpn // ignore: cast_nullable_to_non_nullable
as String?,lab_brand: freezed == lab_brand ? _self.lab_brand : lab_brand // ignore: cast_nullable_to_non_nullable
as String?,lab_package: freezed == lab_package ? _self.lab_package : lab_package // ignore: cast_nullable_to_non_nullable
as String?,lab_description: freezed == lab_description ? _self.lab_description : lab_description // ignore: cast_nullable_to_non_nullable
as String?,lab_specifications: freezed == lab_specifications ? _self.lab_specifications : lab_specifications // ignore: cast_nullable_to_non_nullable
as String?,lab_datasheet_url: freezed == lab_datasheet_url ? _self.lab_datasheet_url : lab_datasheet_url // ignore: cast_nullable_to_non_nullable
as String?,lab_source_url: freezed == lab_source_url ? _self.lab_source_url : lab_source_url // ignore: cast_nullable_to_non_nullable
as String?,categ_id: freezed == categ_id ? _self._categ_id : categ_id // ignore: cast_nullable_to_non_nullable
as List<dynamic>?,type: null == type ? _self.type : type // ignore: cast_nullable_to_non_nullable
as String,image_1920: freezed == image_1920 ? _self.image_1920 : image_1920 // ignore: cast_nullable_to_non_nullable
as String?,qty_available: null == qty_available ? _self.qty_available : qty_available // ignore: cast_nullable_to_non_nullable
as double,active: null == active ? _self.active : active // ignore: cast_nullable_to_non_nullable
as bool,create_date: freezed == create_date ? _self.create_date : create_date // ignore: cast_nullable_to_non_nullable
as DateTime?,write_date: freezed == write_date ? _self.write_date : write_date // ignore: cast_nullable_to_non_nullable
as DateTime?,
  ));
}


}


/// @nodoc
mixin _$ProductSummary {

 int get id;@JsonKey(fromJson: odooString) String get name;@JsonKey(fromJson: odooString) String get lab_sn;@JsonKey(fromJson: odooStringOrNull) String? get lab_lcsc_code;@JsonKey(fromJson: odooStringOrNull) String? get lab_mpn;@JsonKey(fromJson: odooStringOrNull) String? get lab_package;@JsonKey(fromJson: odooDouble) double get qty_available;
/// Create a copy of ProductSummary
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$ProductSummaryCopyWith<ProductSummary> get copyWith => _$ProductSummaryCopyWithImpl<ProductSummary>(this as ProductSummary, _$identity);

  /// Serializes this ProductSummary to a JSON map.
  Map<String, dynamic> toJson();


@override
bool operator ==(Object other) {
  final _this = this as ProductSummary;
  return identical(this, other) || (other.runtimeType == runtimeType&&other is ProductSummary&&(identical(other.id, _this.id) || other.id == _this.id)&&(identical(other.name, _this.name) || other.name == _this.name)&&(identical(other.lab_sn, _this.lab_sn) || other.lab_sn == _this.lab_sn)&&(identical(other.lab_lcsc_code, _this.lab_lcsc_code) || other.lab_lcsc_code == _this.lab_lcsc_code)&&(identical(other.lab_mpn, _this.lab_mpn) || other.lab_mpn == _this.lab_mpn)&&(identical(other.lab_package, _this.lab_package) || other.lab_package == _this.lab_package)&&(identical(other.qty_available, _this.qty_available) || other.qty_available == _this.qty_available));
}

@JsonKey(includeFromJson: false, includeToJson: false)
@override
int get hashCode {
  final _this = this as ProductSummary;
  return Object.hash(runtimeType,_this.id,_this.name,_this.lab_sn,_this.lab_lcsc_code,_this.lab_mpn,_this.lab_package,_this.qty_available);
}

@override
String toString() {
  final _this = this as ProductSummary;
  return 'ProductSummary(id: ${_this.id}, name: ${_this.name}, lab_sn: ${_this.lab_sn}, lab_lcsc_code: ${_this.lab_lcsc_code}, lab_mpn: ${_this.lab_mpn}, lab_package: ${_this.lab_package}, qty_available: ${_this.qty_available})';
}


}

/// @nodoc
abstract mixin class $ProductSummaryCopyWith<$Res>  {
  factory $ProductSummaryCopyWith(ProductSummary value, $Res Function(ProductSummary) _then) = _$ProductSummaryCopyWithImpl;
@useResult
$Res call({
 int id,@JsonKey(fromJson: odooString) String name,@JsonKey(fromJson: odooString) String lab_sn,@JsonKey(fromJson: odooStringOrNull) String? lab_lcsc_code,@JsonKey(fromJson: odooStringOrNull) String? lab_mpn,@JsonKey(fromJson: odooStringOrNull) String? lab_package,@JsonKey(fromJson: odooDouble) double qty_available
});




}
/// @nodoc
class _$ProductSummaryCopyWithImpl<$Res>
    implements $ProductSummaryCopyWith<$Res> {
  _$ProductSummaryCopyWithImpl(this._self, this._then);

  final ProductSummary _self;
  final $Res Function(ProductSummary) _then;

/// Create a copy of ProductSummary
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') @override $Res call({Object? id = null,Object? name = null,Object? lab_sn = null,Object? lab_lcsc_code = freezed,Object? lab_mpn = freezed,Object? lab_package = freezed,Object? qty_available = null,}) {
  return _then(ProductSummary(
id: null == id ? _self.id : id // ignore: cast_nullable_to_non_nullable
as int,name: null == name ? _self.name : name // ignore: cast_nullable_to_non_nullable
as String,lab_sn: null == lab_sn ? _self.lab_sn : lab_sn // ignore: cast_nullable_to_non_nullable
as String,lab_lcsc_code: freezed == lab_lcsc_code ? _self.lab_lcsc_code : lab_lcsc_code // ignore: cast_nullable_to_non_nullable
as String?,lab_mpn: freezed == lab_mpn ? _self.lab_mpn : lab_mpn // ignore: cast_nullable_to_non_nullable
as String?,lab_package: freezed == lab_package ? _self.lab_package : lab_package // ignore: cast_nullable_to_non_nullable
as String?,qty_available: null == qty_available ? _self.qty_available : qty_available // ignore: cast_nullable_to_non_nullable
as double,
  ));
}

}


/// Adds pattern-matching-related methods to [ProductSummary].
extension ProductSummaryPatterns on ProductSummary {
/// A variant of `map` that fallback to returning `orElse`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeMap<TResult extends Object?>(TResult Function( _ProductSummary value)?  $default,{required TResult orElse(),}){
final _that = this;
switch (_that) {
case _ProductSummary() when $default != null:
return $default(_that);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// Callbacks receives the raw object, upcasted.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case final Subclass2 value:
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult map<TResult extends Object?>(TResult Function( _ProductSummary value)  $default,){
final _that = this;
switch (_that) {
case _ProductSummary():
return $default(_that);case _:
  throw StateError('Unexpected subclass');

}
}
/// A variant of `map` that fallback to returning `null`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? mapOrNull<TResult extends Object?>(TResult? Function( _ProductSummary value)?  $default,){
final _that = this;
switch (_that) {
case _ProductSummary() when $default != null:
return $default(_that);case _:
  return null;

}
}
/// A variant of `when` that fallback to an `orElse` callback.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeWhen<TResult extends Object?>(TResult Function( int id, @JsonKey(fromJson: odooString)  String name, @JsonKey(fromJson: odooString)  String lab_sn, @JsonKey(fromJson: odooStringOrNull)  String? lab_lcsc_code, @JsonKey(fromJson: odooStringOrNull)  String? lab_mpn, @JsonKey(fromJson: odooStringOrNull)  String? lab_package, @JsonKey(fromJson: odooDouble)  double qty_available)?  $default,{required TResult orElse(),}) {final _that = this;
switch (_that) {
case _ProductSummary() when $default != null:
return $default(_that.id,_that.name,_that.lab_sn,_that.lab_lcsc_code,_that.lab_mpn,_that.lab_package,_that.qty_available);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// As opposed to `map`, this offers destructuring.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case Subclass2(:final field2):
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult when<TResult extends Object?>(TResult Function( int id, @JsonKey(fromJson: odooString)  String name, @JsonKey(fromJson: odooString)  String lab_sn, @JsonKey(fromJson: odooStringOrNull)  String? lab_lcsc_code, @JsonKey(fromJson: odooStringOrNull)  String? lab_mpn, @JsonKey(fromJson: odooStringOrNull)  String? lab_package, @JsonKey(fromJson: odooDouble)  double qty_available)  $default,) {final _that = this;
switch (_that) {
case _ProductSummary():
return $default(_that.id,_that.name,_that.lab_sn,_that.lab_lcsc_code,_that.lab_mpn,_that.lab_package,_that.qty_available);case _:
  throw StateError('Unexpected subclass');

}
}
/// A variant of `when` that fallback to returning `null`
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? whenOrNull<TResult extends Object?>(TResult? Function( int id, @JsonKey(fromJson: odooString)  String name, @JsonKey(fromJson: odooString)  String lab_sn, @JsonKey(fromJson: odooStringOrNull)  String? lab_lcsc_code, @JsonKey(fromJson: odooStringOrNull)  String? lab_mpn, @JsonKey(fromJson: odooStringOrNull)  String? lab_package, @JsonKey(fromJson: odooDouble)  double qty_available)?  $default,) {final _that = this;
switch (_that) {
case _ProductSummary() when $default != null:
return $default(_that.id,_that.name,_that.lab_sn,_that.lab_lcsc_code,_that.lab_mpn,_that.lab_package,_that.qty_available);case _:
  return null;

}
}

}

/// @nodoc
@JsonSerializable()

class _ProductSummary implements ProductSummary {
  const _ProductSummary({required this.id, @JsonKey(fromJson: odooString) this.name = '', @JsonKey(fromJson: odooString) this.lab_sn = '', @JsonKey(fromJson: odooStringOrNull) this.lab_lcsc_code, @JsonKey(fromJson: odooStringOrNull) this.lab_mpn, @JsonKey(fromJson: odooStringOrNull) this.lab_package, @JsonKey(fromJson: odooDouble) this.qty_available = 0.0});
  factory _ProductSummary.fromJson(Map<String, dynamic> json) => _$ProductSummaryFromJson(json);

@override final  int id;
@override@JsonKey(fromJson: odooString) final  String name;
@override@JsonKey(fromJson: odooString) final  String lab_sn;
@override@JsonKey(fromJson: odooStringOrNull) final  String? lab_lcsc_code;
@override@JsonKey(fromJson: odooStringOrNull) final  String? lab_mpn;
@override@JsonKey(fromJson: odooStringOrNull) final  String? lab_package;
@override@JsonKey(fromJson: odooDouble) final  double qty_available;

/// Create a copy of ProductSummary
/// with the given fields replaced by the non-null parameter values.
@override @JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
_$ProductSummaryCopyWith<_ProductSummary> get copyWith => __$ProductSummaryCopyWithImpl<_ProductSummary>(this, _$identity);

@override
Map<String, dynamic> toJson() {
  return _$ProductSummaryToJson(this, );
}

@override
bool operator ==(Object other) {
    return identical(this, other) || (other.runtimeType == runtimeType&&other is _ProductSummary&&(identical(other.id, id) || other.id == id)&&(identical(other.name, name) || other.name == name)&&(identical(other.lab_sn, lab_sn) || other.lab_sn == lab_sn)&&(identical(other.lab_lcsc_code, lab_lcsc_code) || other.lab_lcsc_code == lab_lcsc_code)&&(identical(other.lab_mpn, lab_mpn) || other.lab_mpn == lab_mpn)&&(identical(other.lab_package, lab_package) || other.lab_package == lab_package)&&(identical(other.qty_available, qty_available) || other.qty_available == qty_available));
}

@JsonKey(includeFromJson: false, includeToJson: false)
@override
int get hashCode {
    return Object.hash(runtimeType,id,name,lab_sn,lab_lcsc_code,lab_mpn,lab_package,qty_available);
}

@override
String toString() {
    return 'ProductSummary(id: $id, name: $name, lab_sn: $lab_sn, lab_lcsc_code: $lab_lcsc_code, lab_mpn: $lab_mpn, lab_package: $lab_package, qty_available: $qty_available)';
}


}

/// @nodoc
abstract mixin class _$ProductSummaryCopyWith<$Res> implements $ProductSummaryCopyWith<$Res> {
  factory _$ProductSummaryCopyWith(_ProductSummary value, $Res Function(_ProductSummary) _then) = __$ProductSummaryCopyWithImpl;
@override @useResult
$Res call({
 int id,@JsonKey(fromJson: odooString) String name,@JsonKey(fromJson: odooString) String lab_sn,@JsonKey(fromJson: odooStringOrNull) String? lab_lcsc_code,@JsonKey(fromJson: odooStringOrNull) String? lab_mpn,@JsonKey(fromJson: odooStringOrNull) String? lab_package,@JsonKey(fromJson: odooDouble) double qty_available
});




}
/// @nodoc
class __$ProductSummaryCopyWithImpl<$Res>
    implements _$ProductSummaryCopyWith<$Res> {
  __$ProductSummaryCopyWithImpl(this._self, this._then);

  final _ProductSummary _self;
  final $Res Function(_ProductSummary) _then;

/// Create a copy of ProductSummary
/// with the given fields replaced by the non-null parameter values.
@override @pragma('vm:prefer-inline') $Res call({Object? id = null,Object? name = null,Object? lab_sn = null,Object? lab_lcsc_code = freezed,Object? lab_mpn = freezed,Object? lab_package = freezed,Object? qty_available = null,}) {
  return _then(_ProductSummary(
id: null == id ? _self.id : id // ignore: cast_nullable_to_non_nullable
as int,name: null == name ? _self.name : name // ignore: cast_nullable_to_non_nullable
as String,lab_sn: null == lab_sn ? _self.lab_sn : lab_sn // ignore: cast_nullable_to_non_nullable
as String,lab_lcsc_code: freezed == lab_lcsc_code ? _self.lab_lcsc_code : lab_lcsc_code // ignore: cast_nullable_to_non_nullable
as String?,lab_mpn: freezed == lab_mpn ? _self.lab_mpn : lab_mpn // ignore: cast_nullable_to_non_nullable
as String?,lab_package: freezed == lab_package ? _self.lab_package : lab_package // ignore: cast_nullable_to_non_nullable
as String?,qty_available: null == qty_available ? _self.qty_available : qty_available // ignore: cast_nullable_to_non_nullable
as double,
  ));
}


}

// dart format on
