import 'json_read.dart';

/// Everything the unified library can filter by.
///
/// The parameter map is keyed by the catalog parameter code
/// (`param_11032_n`) and holds every selected value for that code. On the wire a
/// single value is sent as a string and several values as a list, which is the
/// only shape that stays readable for both the SQL filter and the FTS path.
class CatalogQuery {
  const CatalogQuery({
    this.text = '',
    this.categoryId,
    this.brands = const <String>{},
    this.packages = const <String>{},
    this.parameters = const <String, Set<String>>{},
    this.stockOnly = false,
  });

  /// Free text: C code / MPN / name / brand. Matched on the SERVER, never by
  /// filtering an already-loaded page on the client.
  final String text;

  final int? categoryId;
  final Set<String> brands;
  final Set<String> packages;
  final Map<String, Set<String>> parameters;

  /// Internal lab stock only (`stock_only`).
  final bool stockOnly;

  bool get isFiltered =>
      text.trim().isNotEmpty ||
      categoryId != null ||
      brands.isNotEmpty ||
      packages.isNotEmpty ||
      stockOnly ||
      parameters.values.any((values) => values.isNotEmpty);

  int get activeFilterCount {
    var count = 0;
    if (text.trim().isNotEmpty) count++;
    if (categoryId != null) count++;
    if (stockOnly) count++;
    count += brands.length + packages.length;
    for (final values in parameters.values) {
      count += values.isEmpty ? 0 : 1;
    }
    return count;
  }

  String get description {
    final parts = <String>[
      if (text.trim().isNotEmpty) '“${text.trim()}”',
      if (categoryId != null) '已选分类',
      if (stockOnly) '仅有库存',
      if (brands.isNotEmpty) '品牌 ${brands.length}',
      if (packages.isNotEmpty) '封装 ${packages.length}',
      for (final entry in parameters.entries)
        if (entry.value.isNotEmpty) '${entry.key}(${entry.value.length})',
    ];
    return parts.isEmpty ? '全部已采集资料' : parts.join(' · ');
  }

  CatalogQuery copyWith({
    String? text,
    Object? categoryId = _unset,
    Set<String>? brands,
    Set<String>? packages,
    Map<String, Set<String>>? parameters,
    bool? stockOnly,
  }) {
    return CatalogQuery(
      text: text ?? this.text,
      categoryId:
          identical(categoryId, _unset) ? this.categoryId : categoryId as int?,
      brands: brands ?? this.brands,
      packages: packages ?? this.packages,
      parameters: parameters ?? this.parameters,
      stockOnly: stockOnly ?? this.stockOnly,
    );
  }

  static const Object _unset = Object();

  /// Request body for `/lab/api/catalog/search`.
  Map<String, dynamic> toSearchParams({String? cursor, int limit = 50}) {
    return <String, dynamic>{
      'query': text,
      'category_id': categoryId,
      'brands': brands.toList(),
      'packages': packages.toList(),
      'parameters': parametersToJson(parameters),
      'stock_only': stockOnly,
      'cursor': cursor,
      'limit': limit,
    };
  }

  /// Request body for `/lab/api/catalog/facets` (no cursor/limit).
  Map<String, dynamic> toFacetParams() {
    return <String, dynamic>{
      'query': text,
      'category_id': categoryId,
      'brands': brands.toList(),
      'packages': packages.toList(),
      'parameters': parametersToJson(parameters),
    };
  }

  /// A single selected value is sent as a string, several as a list.
  static Map<String, dynamic> parametersToJson(
    Map<String, Set<String>> parameters,
  ) {
    final result = <String, dynamic>{};
    parameters.forEach((code, values) {
      final sorted = uniqueSorted(values);
      if (sorted.isEmpty) return;
      result[code] = sorted.length == 1 ? sorted.first : sorted;
    });
    return result;
  }

  /// Reads the wire shape back (used by tests and by deep links).
  static Map<String, Set<String>> parametersFromJson(Object? value) {
    if (value is! Map) return const <String, Set<String>>{};
    final result = <String, Set<String>>{};
    asMap(value).forEach((key, item) {
      if (item is List) {
        final values = uniqueSorted(asStringList(item));
        if (values.isNotEmpty) result[key] = values.toSet();
      } else {
        final single = asString(item);
        if (single != null) result[key] = <String>{single};
      }
    });
    return result;
  }
}
