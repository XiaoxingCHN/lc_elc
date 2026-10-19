// Odoo JSON decoding helpers.
//
// Why this file exists:
// Odoo's ORM returns `false` - not `null` - for an empty field:
//
//   Char / Text / Selection / Html   -> false
//   Date / Datetime                  -> false
//   Many2one (e.g. categ_id)         -> false
//   Integer / Float (occasionally)   -> false
//
// Decoding that payload straight into a typed model throws a type error, so
// every non-boolean field that can be empty is funnelled through one of the
// converters below via `@JsonKey(fromJson: ...)` in `product.dart`.
//
// IMPORTANT: do NOT apply a blanket "false means null" pass over the whole
// JSON map. `false` is a legitimate value for Boolean fields (`active`), and
// rewriting it to null would silently turn archived products into active
// ones. Boolean fields must use [odooBool], which preserves `false`.

/// Char/Text/Selection/Date -> `String`; `false` and `null` become `''`.
String odooString(Object? value) {
  if (value == null || value == false) return '';
  if (value is String) return value;
  return value.toString();
}

/// Char/Text/Selection/Date -> `String?`; `false`, `null` and `''` become `null`.
String? odooStringOrNull(Object? value) {
  if (value == null || value == false) return null;
  if (value is String) return value.isEmpty ? null : value;
  final text = value.toString();
  return text.isEmpty ? null : text;
}

/// Boolean -> `bool`, preserving a real `false`.
///
/// Only `null`, `''` and unrecognised values fall back to [fallback].
bool odooBool(Object? value, {bool fallback = false}) {
  if (value is bool) return value;
  if (value == null || value == '') return fallback;
  if (value is num) return value != 0;
  if (value is String) {
    switch (value.toLowerCase()) {
      case 'true':
      case '1':
        return true;
      case 'false':
      case '0':
        return false;
    }
  }
  return fallback;
}

/// Numeric -> `double`; `false` and `null` become `0.0`.
double odooDouble(Object? value) {
  if (value == null || value == false) return 0.0;
  if (value is num) return value.toDouble();
  if (value is String) return double.tryParse(value) ?? 0.0;
  return 0.0;
}

/// Integer -> `int?`; `false` and `null` become `null`.
int? odooIntOrNull(Object? value) {
  if (value == null || value == false) return null;
  if (value is int) return value;
  if (value is num) return value.toInt();
  if (value is String) return int.tryParse(value);
  return null;
}

/// Odoo Date/Datetime string -> `DateTime?`.
///
/// Odoo serialises as `"2026-10-12 10:00:00"` (space separated). Dart's
/// `DateTime.parse` accepts the space separator, and the `T` variant is tried
/// as a fallback. `false`, `null`, `''` and unparsable values yield `null`
/// rather than throwing.
DateTime? odooDateTimeOrNull(Object? value) {
  if (value == null || value == false) return null;
  if (value is DateTime) return value;
  if (value is String) {
    final text = value.trim();
    if (text.isEmpty) return null;
    return DateTime.tryParse(text) ??
        DateTime.tryParse(text.replaceFirst(' ', 'T'));
  }
  return null;
}

/// Many2one / one2many payload -> `List<dynamic>?`.
///
/// Odoo returns `[id, displayName]` for a set Many2one and `false` for an
/// empty one, which is why this cannot be a plain `List<dynamic>?` cast.
List<dynamic>? odooListOrNull(Object? value) {
  if (value == null || value == false) return null;
  if (value is List) return value;
  return null;
}
