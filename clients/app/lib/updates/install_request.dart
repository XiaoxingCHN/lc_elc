import 'dart:convert';
import 'dart:io';

import 'update_manifest.dart';

String encodeInstallRequest(
  File package,
  UpdateManifest release,
  File executable,
  int processId,
) => jsonEncode({
  'envelope': release.envelope,
  'package': package.absolute.path,
  'executable': executable.absolute.path,
  'pid': processId,
  'current_build': const int.fromEnvironment('FLUTTER_BUILD_NUMBER'),
});
