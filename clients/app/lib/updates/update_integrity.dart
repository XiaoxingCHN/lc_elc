import 'dart:io';

import 'package:crypto/crypto.dart';

import 'update_manifest.dart';

Future<void> verifyUpdateFile(File file, UpdateManifest release) async {
  if (await file.length() != release.size ||
      (await sha256.bind(file.openRead()).first).toString() != release.digest) {
    throw const FormatException('安装包校验失败，请重新下载');
  }
}
