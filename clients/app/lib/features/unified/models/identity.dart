/// Canonical identity of one visible card in the UNIFIED component library.
///
/// `lc_elc/docs/business_api_contract.json` (v1.0, root-approved) fixes the two
/// legal shapes:
///
///   * `lcsc:C123` - a catalog row, with or without local templates bound to
///     it. ONE catalog code is ONE card, aggregating EVERY local template the
///     operator is allowed to see; the individual templates and their SNs stay
///     separate inside the detail view.
///   * `lab:42`    - a local template with no usable catalog binding.
///
/// Rules implemented here (all of them are asserted by
/// `test/features/unified/identity_test.dart`):
///
///   * normalization is full-width -> half-width, trim, upper-case (the NFKC
///     subset that matters for a `C<digits>` code);
///   * a usable code is `C` followed by positive decimal digits - a 4-digit
///     minimum is deliberately NOT required, and `C0`/`C00` are rejected
///     because the digits must form a positive number;
///   * `null`, `''`, `'-'`, `'N/A'`, `'待补'` and any other unusable value is
///     UNBOUND: it never merges anything;
///   * the client never invents an identity. When the server omits `item_key`
///     and no usable code can be derived, callers must keep the row unmerged.
library;

import 'json_read.dart';

/// Prefix of a catalog-or-bound identity.
const String kCatalogKeyPrefix = 'lcsc:';

/// Prefix of an unbound local identity.
const String kLabKeyPrefix = 'lab:';

/// Identity kind of a card.
enum IdentityKind {
  /// Catalog row (bound or not) - `lcsc:<code>`.
  catalog,

  /// Local template without a usable catalog binding - `lab:<id>`.
  lab,

  /// The server row could not be identified: keep it visible, never merge it.
  unknown,
}

/// Converts full-width ASCII (U+FF01..U+FF5E) and the ideographic space to
/// their half-width equivalents. This is the NFKC subset that a `C123456` code
/// can actually be typed in - `Ｃ１２３` and `C123` must normalize identically.
String toHalfWidth(String input) {
  final buffer = StringBuffer();
  for (final rune in input.runes) {
    if (rune == 0x3000) {
      buffer.write(' ');
    } else if (rune >= 0xFF01 && rune <= 0xFF5E) {
      buffer.writeCharCode(rune - 0xFEE0);
    } else {
      buffer.writeCharCode(rune);
    }
  }
  return buffer.toString();
}

/// Normalizes a catalog code: half-width, trimmed, upper-cased, with an
/// optional `lcsc:` / `LCSC` prefix removed. Returns `''` for an empty input.
///
/// This does NOT validate; use [isUsableCatalogCode] for that. Keeping the two
/// apart means an invalid code still prints exactly as the operator typed it.
String normalizeCatalogCode(Object? raw) {
  final text = asString(raw);
  if (text == null) return '';
  var value = toHalfWidth(text).trim().toUpperCase();
  if (value.startsWith('LCSC:')) value = value.substring(5).trim();
  if (value.startsWith('LCSC')) value = value.substring(4).trim();
  return value;
}

/// True when [raw] normalizes to `C` followed by positive decimal digits.
bool isUsableCatalogCode(Object? raw) {
  final code = normalizeCatalogCode(raw);
  final match = RegExp(r'^C([0-9]+)$').firstMatch(code);
  if (match == null) return false;
  final digits = match.group(1)!;
  final value = int.tryParse(digits);
  return value != null && value > 0;
}

/// `lcsc:C123` for a usable code, otherwise `null` (never a fabricated key).
String? catalogItemKey(Object? raw) {
  if (!isUsableCatalogCode(raw)) return null;
  return '$kCatalogKeyPrefix${normalizeCatalogCode(raw)}';
}

/// `lab:42` for a positive template id, otherwise `null`.
String? labItemKey(Object? id) {
  final value = asInt(id);
  if (value == null || value <= 0) return null;
  return '$kLabKeyPrefix$value';
}

/// Reads an `item_key` the server already sent (it wins over anything derived).
String? explicitItemKey(Object? raw) {
  final text = asString(raw);
  if (text == null) return null;
  final key = text.trim();
  if (key.isEmpty) return null;
  if (key.startsWith(kCatalogKeyPrefix)) {
    return catalogItemKey(key.substring(kCatalogKeyPrefix.length));
  }
  if (key.startsWith(kLabKeyPrefix)) {
    return labItemKey(key.substring(kLabKeyPrefix.length));
  }
  // A bare `C123` is still a catalog identity.
  return catalogItemKey(key);
}

/// Identity kind of an already-normalized `item_key`.
IdentityKind identityKindOf(String itemKey) {
  if (itemKey.startsWith(kCatalogKeyPrefix)) return IdentityKind.catalog;
  if (itemKey.startsWith(kLabKeyPrefix)) return IdentityKind.lab;
  return IdentityKind.unknown;
}

/// Derives the identity of one `/lab/api/catalog/search` row.
///
/// Order: the server's `item_key`, then `catalog_code` (or `code`), then the
/// first local template id. Returns `null` when none of them is usable - the
/// caller then shows the row under a synthetic, non-mergeable key.
String? deriveItemKey(Map<String, dynamic> json) {
  final explicit = explicitItemKey(json['item_key']);
  if (explicit != null) return explicit;

  for (final key in const ['catalog_code', 'lcsc_code', 'code', 'part_number']) {
    final derived = catalogItemKey(json[key]);
    if (derived != null) return derived;
  }

  final templateIds = asList(json['lab_template_ids']);
  for (final id in templateIds) {
    final derived = labItemKey(id);
    if (derived != null) return derived;
  }
  // A payload that only names one local record (bag / issue line).
  for (final key in const ['product_template_id', 'template_id', 'product_id']) {
    final derived = labItemKey(json[key]);
    if (derived != null) return derived;
  }
  return null;
}

/// The HUMAN code of a card: `C225521`.
///
/// `catalog_code` is already stored WITH its `C` in the captured data, so
/// `'C${...}'` everywhere would print `CC225521`. This function guarantees exactly
/// one leading `C` no matter which shape the server sent.
String displayCatalogCode(Object? raw) {
  final code = normalizeCatalogCode(raw);
  if (code.isEmpty) return '';
  if (code.startsWith('C')) return code;
  return 'C$code';
}

/// A human-readable label for an internal `item_key`.
///
/// The UI must never show the internal key (`lcsc:C123` / `lab:42`): the operator
/// identifies a material by its C code, its SN or its name. This maps the key onto
/// that vocabulary and falls back to the item name for a local archive.
String humanItemLabel(String itemKey, {String name = '', String sn = ''}) {
  final key = itemKey.trim();
  if (key.startsWith(kCatalogKeyPrefix)) {
    return displayCatalogCode(key.substring(kCatalogKeyPrefix.length));
  }
  if (key.startsWith(kLabKeyPrefix)) {
    if (sn.isNotEmpty) return sn;
    if (name.isNotEmpty) return name;
    return '本地物料';
  }
  return name.isNotEmpty ? name : key;
}

/// One physical bag/batch trace payload, as printed on a bag label.
String bagPayload(String traceCode) => 'LABB:${traceCode.trim()}';

/// One location payload, as printed on a location label.
String locationPayload(String locationCode) => 'LABL:${locationCode.trim()}';

/// The raw string behind a `LABB:` / `LABL:` payload, or the input unchanged.
String unwrapPayload(String raw) {
  final text = raw.trim();
  if (text.toUpperCase().startsWith('LABB:')) return text.substring(5).trim();
  if (text.toUpperCase().startsWith('LABL:')) return text.substring(5).trim();
  return text;
}
