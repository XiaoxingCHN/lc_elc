/// Tolerant readers for the `/lab/api/...` business payloads.
///
/// The Odoo addons that implement these routes (`lab_catalog`, `lab_workflow`)
/// are written in parallel with this client, so every reader here accepts the
/// names pinned in `lc_elc/docs/business_api_contract.json` *and* the aliases
/// Odoo naturally produces:
///
///   * `false` (not `null`) for an empty Char / Text / Date / Many2one;
///   * an `int` where the contract declares a float quantity;
///   * a numeric string where the contract declares a number.
///
/// An unknown key yields the empty default instead of throwing: one malformed
/// row must never blank out an entire page of 50 real components. Nothing here
/// invents a value - a missing field stays missing.
library;

/// Coerces [value] to a map. A `List` of pairs, `false` or `null` becomes `{}`.
Map<String, dynamic> asMap(Object? value) {
  if (value is Map<String, dynamic>) return value;
  if (value is Map) {
    return value.map((key, item) => MapEntry(key.toString(), item));
  }
  return const <String, dynamic>{};
}

/// Coerces [value] to a list. `null`/`false` becomes an empty list.
List<Object?> asList(Object? value) {
  if (value is List) return value;
  if (value == null || value == false) return const <Object?>[];
  return <Object?>[value];
}

/// Every map element of [value], skipping non-map elements.
List<Map<String, dynamic>> asMapList(Object? value) {
  final result = <Map<String, dynamic>>[];
  for (final entry in asList(value)) {
    if (entry is Map) result.add(asMap(entry));
  }
  return result;
}

/// Every string-ish element of [value] (`int` ids are allowed and stringified).
List<String> asStringList(Object? value) {
  final result = <String>[];
  for (final entry in asList(value)) {
    final text = asString(entry);
    if (text != null && text.isNotEmpty) result.add(text);
  }
  return result;
}

/// Odoo empties: `null`, `false`, `''`, and the literal strings Odoo sometimes
/// leaves behind in a Char field.
const _odooEmpties = <String>{'', 'false', 'null', 'none', 'n/a', '待补', '-'};

/// A non-empty string, or `null`. `bool` is never a string.
String? asString(Object? value) {
  if (value == null || value is bool) return null;
  if (value is String) {
    final trimmed = value.trim();
    if (trimmed.isEmpty) return null;
    if (_odooEmpties.contains(trimmed.toLowerCase())) return null;
    return trimmed;
  }
  if (value is num) return value.toString();
  if (value is List) {
    // Many2one `[id, display_name]` -> display name.
    if (value.length >= 2) return asString(value[1]);
    return null;
  }
  return null;
}

/// [asString] with a fallback, for required-but-not-really fields (names).
String asStringOr(Object? value, [String fallback = '']) =>
    asString(value) ?? fallback;

/// An HTTP(S) URL, or `null`. Anything else (a relative path, a `data:` URI, a
/// javascript: URL from a hostile payload) is refused: this client must never
/// be turned into an open fetcher or a proxy for arbitrary URLs.
String? asUrl(Object? value) {
  final text = asString(value);
  if (text == null) return null;
  final uri = Uri.tryParse(text);
  if (uri == null) return null;
  if (uri.scheme != 'http' && uri.scheme != 'https') return null;
  if (uri.host.isEmpty) return null;
  return uri.toString();
}

/// An asset reference: either an absolute `http(s)` URL (an external CDN) or a
/// SAME-ORIGIN relative path such as `/lab/api/asset/data` returned by the
/// Odoo server itself.
///
/// Root's rule: an authenticated same-origin link must be fetched with the
/// session, while the session cookie must NEVER be sent to an external CDN.
/// Keeping the reference unresolved here is what lets [AssetCacheStore] apply
/// that rule at fetch time; `asUrl` alone would silently drop such an image.
String? asAssetReference(Object? value) {
  final text = asString(value);
  if (text == null) return null;

  final absolute = asUrl(text);
  if (absolute != null) return absolute;

  final uri = Uri.tryParse(text);
  if (uri == null || uri.scheme.isNotEmpty || uri.host.isNotEmpty) return null;
  // Guard against an embedded base64 blob being mistaken for a path: a real
  // asset path is short, and padding/whitespace never appears in one.
  if (text.length > 512) return null;
  if (text.contains(RegExp(r'\s'))) return null;
  if (text.contains('=') && !text.contains('?')) return null;
  // A rooted path, or a path with at least one separator (never a bare code).
  if (text.startsWith('/')) return text;
  if (text.contains('/') && !text.contains('\\')) return text;
  return null;
}

/// An int, or `null`. Accepts `12`, `12.0` and `"12"`.
int? asInt(Object? value) {
  if (value == null || value is bool) return null;
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value.trim());
  return null;
}

/// A double, or `null`. Quantities arrive as int, double or numeric string.
double? asDouble(Object? value) {
  if (value == null || value is bool) return null;
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value.trim());
  return null;
}

/// A bool. Accepts Odoo's `0/1` ints and `"true"`/`"false"`/`"1"`/`"0"`.
bool asBool(Object? value, {bool fallback = false}) {
  if (value == null) return fallback;
  if (value is bool) return value;
  if (value is num) return value != 0;
  if (value is String) {
    switch (value.trim().toLowerCase()) {
      case 'true':
      case '1':
      case 'yes':
      case 'on':
        return true;
      case 'false':
      case '0':
      case 'no':
      case 'off':
      case '':
        return false;
    }
  }
  return fallback;
}

/// Parses an ISO-8601 timestamp (Odoo writes `YYYY-MM-DD HH:MM:SS`).
DateTime? asDateTime(Object? value) {
  final text = asString(value);
  if (text == null) return null;
  return DateTime.tryParse(text.replaceFirst(' ', 'T'));
}

/// First key of [keys] present with a non-empty string value.
String? firstString(Map<String, dynamic> json, List<String> keys) {
  for (final key in keys) {
    final text = asString(json[key]);
    if (text != null) return text;
  }
  return null;
}

/// First key of [keys] present with a non-null value (raw).
Object? firstValue(Map<String, dynamic> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value != null && value != false) return value;
  }
  return null;
}

int? firstInt(Map<String, dynamic> json, List<String> keys) {
  for (final key in keys) {
    final value = asInt(json[key]);
    if (value != null) return value;
  }
  return null;
}

double? firstDouble(Map<String, dynamic> json, List<String> keys) {
  for (final key in keys) {
    final value = asDouble(json[key]);
    if (value != null) return value;
  }
  return null;
}

/// First key of [keys] that carries an explicit boolean, or `null`.
bool? firstBool(Map<String, dynamic> json, List<String> keys) {
  for (final key in keys) {
    final value = json[key];
    if (value is bool) return value;
    if (value is num) return value != 0;
  }
  return null;
}

/// A Many2one `[id, name]` / `{id, name}` / plain id, reduced to `(id, name)`.
({int? id, String? name}) asReference(Object? value) {
  if (value is List) {
    if (value.isEmpty) return (id: null, name: null);
    return (id: asInt(value.first), name: value.length > 1 ? asString(value[1]) : null);
  }
  if (value is Map) {
    final map = asMap(value);
    return (
      id: firstInt(map, const ['id', 'res_id']),
      name: firstString(map, const ['name', 'display_name', 'label']),
    );
  }
  return (id: asInt(value), name: null);
}

/// Sorted, de-duplicated copy of [values] (stable filter/UI output).
List<String> uniqueSorted(Iterable<String> values) {
  final set = <String>{};
  for (final value in values) {
    final trimmed = value.trim();
    if (trimmed.isNotEmpty) set.add(trimmed);
  }
  final list = set.toList()..sort();
  return list;
}
