import 'dart:convert';

import 'package:crypto/crypto.dart';

/// The identity of ONE logged-in session: which server, which database, which
/// user, and (when known) which company context.
///
/// Why this exists: the offline cache stores BUSINESS data (lab quantities, bags,
/// issue history) and same-origin authenticated files. Keying any of that only by
/// `item_key` would let the next operator see the previous operator's stock, or a
/// different server's `lab:42`. Every cached business artifact is therefore
/// addressed by [key] - a hash of this whole scope - and every provider that
/// reads business data watches this value, so switching server / database /
/// account / company tears the old state down instead of silently reusing it.
///
/// [company] is deliberately part of the key: one Odoo user may be allowed in
/// several companies, and stock/history differ per company. The login flow does
/// not know the active company, so the auth layer (or the inventory bootstrap)
/// can publish it through `companyScopeProvider`; an empty value simply means
/// "single-company / unknown", which is still isolated per server+db+user.
class LabSessionScope {
  const LabSessionScope({
    this.baseUrl = '',
    this.database = '',
    this.uid,
    this.company = '',
  });

  /// Normalized server URL (trailing slashes removed).
  final String baseUrl;

  final String database;

  /// Odoo user id, or `null` while signed out.
  final int? uid;

  /// Active company context, when the app knows it.
  final String company;

  /// Nothing is cached while signed out: an anonymous session has no business
  /// data to show, and a shared "anonymous" cache directory would leak.
  bool get isSignedIn => uid != null;

  bool get canPersistBusinessData => isSignedIn;

  static const LabSessionScope anonymous = LabSessionScope();

  LabSessionScope withCompany(String company) {
    if (company == this.company) return this;
    return LabSessionScope(
      baseUrl: baseUrl,
      database: database,
      uid: uid,
      company: company,
    );
  }

  LabSessionScope withUid(int? uid) => LabSessionScope(
        baseUrl: baseUrl,
        database: database,
        uid: uid,
        company: company,
      );

  /// Stable, filesystem-safe hash of the whole scope.
  ///
  /// Used as the directory name for business data and for the pin list, so two
  /// scopes can never read each other's files.
  String get key {
    final normalized = normalizeBaseUrl(baseUrl);
    final material = '$normalized\u0000$database\u0000${uid ?? ''}\u0000$company';
    return sha256.convert(utf8.encode(material)).toString().substring(0, 32);
  }

  /// Short human label for diagnostics ("数据库 · 服务器 · 用户").
  String get label => <String>[
        if (database.isNotEmpty) database,
        if (baseUrl.isNotEmpty) normalizeBaseUrl(baseUrl),
        if (uid != null) 'uid $uid',
        if (company.isNotEmpty) 'company $company',
      ].join(' · ');

  static String normalizeBaseUrl(String value) {
    var text = value.trim();
    while (text.endsWith('/')) {
      text = text.substring(0, text.length - 1);
    }
    return text;
  }

  @override
  bool operator ==(Object other) {
    return other is LabSessionScope &&
        normalizeBaseUrl(other.baseUrl) == normalizeBaseUrl(baseUrl) &&
        other.database == database &&
        other.uid == uid &&
        other.company == company;
  }

  @override
  int get hashCode => Object.hash(
        normalizeBaseUrl(baseUrl),
        database,
        uid,
        company,
      );

  @override
  String toString() => 'LabSessionScope($label)';
}
