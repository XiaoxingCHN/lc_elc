import 'dart:convert';
import 'dart:io';

import 'package:lab_inventory_client/updates/desktop_update.dart';

Future<void> main(List<String> args) async {
  if (args.length != 1) exit(2);
  final request = File(args.single).absolute;
  try {
    await runDesktopUpdate(request);
  } catch (_) {
    // Paths/errors can contain user data; only a fixed status is persisted.
    await File('${request.path}.result').writeAsString(
      jsonEncode({'status': 'failed', 'old_version_retained': true}),
    );
    exitCode = 1;
  }
}
