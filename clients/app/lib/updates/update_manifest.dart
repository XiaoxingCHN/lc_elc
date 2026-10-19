import 'dart:convert';

import 'package:cryptography/cryptography.dart';

const updateTrustedKeys = <String, String>{
  'release-20261019': 'GqUJm3fIWXvV/X+Dla7QOENo76+t67RUGPoOhFTzONc=',
};
const updateAppId = 'com.example.lab_inventory_client';
const maxUpdateBytes = 512 * 1024 * 1024;
final _safeName = RegExp(r'^[A-Za-z0-9][A-Za-z0-9._+-]{0,100}$');

class UpdateManifest {
  UpdateManifest._(this.envelope, this.data);
  final Map<String, dynamic> envelope;
  final Map<String, dynamic> data;
  String get releaseId => data['release_id'] as String;
  String get filename => data['filename'] as String;
  String get version => data['version'] as String;
  String get platform => data['platform'] as String;
  String get arch => data['arch'] as String;
  String get digest => data['sha256'] as String;
  String get notes => data['notes'] as String? ?? '';
  int get size => data['size'] as int;
  int get build => data['build_number'] as int;
  int get sequence => data['release_sequence'] as int;
  String get assetPath => '/lab/client/updates/assets/$releaseId/$filename';

  static Future<UpdateManifest> verify(
    Map<String, dynamic> envelope, {
    Map<String, String> keys = updateTrustedKeys,
  }) async {
    if (utf8.encode(jsonEncode(envelope)).length > 65536) {
      throw const FormatException('更新清单过大');
    }
    final public = keys[envelope['key_id']];
    if (public == null) throw const FormatException('未知更新签名');
    final payload = base64Decode(envelope['payload'] as String);
    final signature = base64Decode(envelope['signature'] as String);
    if (signature.length != 64 ||
        !await Ed25519().verify(
          payload,
          signature: Signature(
            signature,
            publicKey: SimplePublicKey(
              base64Decode(public),
              type: KeyPairType.ed25519,
            ),
          ),
        )) {
      throw const FormatException('更新签名验证失败');
    }
    final d = jsonDecode(utf8.decode(payload)) as Map<String, dynamic>;
    if (d['schema'] != 1 ||
        d['app_id'] != updateAppId ||
        d['channel'] != 'stable') {
      throw const FormatException('不支持的更新清单');
    }
    for (final field in ['release_id', 'filename', 'platform', 'arch']) {
      if (d[field] is! String ||
          !_safeName.hasMatch(d[field] as String) ||
          d[field] == '..') {
        throw const FormatException('更新路径无效');
      }
    }
    for (final field in ['size', 'build_number', 'release_sequence']) {
      if (d[field] is! int || (d[field] as int) <= 0)
        throw const FormatException('版本号无效');
    }
    if ((d['size'] as int) > maxUpdateBytes ||
        d['sha256'] is! String ||
        !RegExp(r'^[0-9a-f]{64}$').hasMatch(d['sha256'] as String) ||
        d['version'] is! String ||
        !RegExp(r'^\d+\.\d+\.\d+([.-][A-Za-z0-9.-]+)?$')
            .hasMatch(d['version'] as String)) {
      throw const FormatException('更新完整性信息无效');
    }
    const formats = {'windows': 'zip', 'linux': 'tar.gz', 'android': 'apk'};
    final format = formats[d['platform']];
    if (format == null ||
        d['package_type'] != format ||
        !(d['filename'] as String).endsWith('.$format') ||
        !['x64', 'arm64', 'universal'].contains(d['arch']) ||
        d['api_min'] is! int ||
        d['api_max'] is! int ||
        (d['api_min'] as int) > 1 ||
        (d['api_max'] as int) < 1 ||
        (d['notes'] != null &&
            (d['notes'] is! String || (d['notes'] as String).length > 4000)) ||
        (d['requirements'] != null && d['requirements'] is! Map)) {
      throw const FormatException('安装包不兼容');
    }
    return UpdateManifest._(
      Map<String, dynamic>.unmodifiable(envelope),
      Map<String, dynamic>.unmodifiable(d),
    );
  }

  bool matches(
    String platform,
    String arch,
    int currentBuild,
    int highestSequence,
    Map<String, int> facts,
  ) {
    if (this.platform != platform ||
        this.arch != arch ||
        build <= currentBuild ||
        sequence < highestSequence ||
        currentBuild <= 0)
      return false;
    final required = data['requirements'] as Map? ?? const {};
    return required.entries.every(
      (e) =>
          e.value is int &&
          facts[e.key] != null &&
          facts[e.key]! >= (e.value as int),
    );
  }
}
