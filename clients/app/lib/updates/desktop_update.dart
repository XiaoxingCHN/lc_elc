// Shared by the app and the standalone updater. No Flutter/platform plugins.
import 'dart:convert';
import 'dart:async';
import 'dart:io';
import 'dart:math';

import 'package:archive/archive_io.dart';
import 'package:path/path.dart' as p;

import 'update_manifest.dart';
import 'update_integrity.dart';

Future<void> markUpdateReady() async {
  final nonce = Platform.environment['LAB_UPDATE_NONCE'];
  if (nonce == null || !RegExp(r'^[a-zA-Z0-9_-]{32}$').hasMatch(nonce)) return;
  final root = File(Platform.resolvedExecutable).parent;
  try {
    await File(p.join(root.path, '.client-update-ready.json')).writeAsString(
      jsonEncode({
        'nonce': nonce,
        'build': const int.fromEnvironment('FLUTTER_BUILD_NUMBER'),
      }),
      flush: true,
    );
  } catch (_) {
    /* A read-only installation must fail the helper's ready check. */
  }
}

Future<Map<String, dynamic>> installationIdentity(Directory root) async {
  final marker = File(p.join(root.path, 'client-install.json'));
  if (await FileSystemEntity.isLink(marker.path) ||
      !await marker.exists() ||
      await marker.length() > 4096) {
    throw const FormatException('Missing installation identity');
  }
  final identity =
      jsonDecode(await marker.readAsString()) as Map<String, dynamic>;
  if (identity['app_id'] != updateAppId ||
      identity['layout'] != 1 ||
      identity['build'] is! int) {
    throw const FormatException('Invalid installation identity');
  }
  return identity;
}

Future<void> extractBundle(
  File package,
  Directory destination,
  String platform,
) async {
  if (await destination.exists())
    throw const FormatException('Destination already exists');
  final input = InputFileStream(package.path);
  File? tar;
  InputFileStream? tarInput;
  try {
    late Archive archive;
    if (platform == 'windows') {
      archive = ZipDecoder().decodeStream(input, verify: true);
    } else if (platform == 'linux') {
      tar = File('${destination.path}.tar');
      if (await tar.exists())
        throw const FormatException('Staging file exists');
      final output = OutputFileStream(tar.path);
      try {
        GZipDecoder().decodeStream(
          input,
          output,
          verify: true,
          maxOutputSize: 2 * 1024 * 1024 * 1024,
        );
      } finally {
        await output.close();
      }
      tarInput = InputFileStream(tar.path);
      archive = TarDecoder().decodeStream(tarInput);
    } else {
      throw const FormatException('Unsupported desktop package');
    }
    if (archive.length > 10000)
      throw const FormatException('Too many bundle entries');
    var total = 0;
    final names = <String>{};
    for (final entry in archive) {
      final name = entry.name;
      final parts = name.split('/').where((s) => s.isNotEmpty).toList();
      final type = entry.mode & 0xF000;
      if (name.contains('\\') ||
          name.contains(':') ||
          name.startsWith('/') ||
          parts.isEmpty ||
          parts.first != 'bundle' ||
          parts.any(
            (s) =>
                s == '.' ||
                s == '..' ||
                s.endsWith('.') ||
                s.endsWith(' ') ||
                RegExp(
                  r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)',
                  caseSensitive: false,
                ).hasMatch(s),
          ) ||
          entry.isSymbolicLink ||
          ![0, 0x8000, 0x4000].contains(type) ||
          !names.add(name.toLowerCase()) ||
          entry.size < 0 ||
          entry.size > maxUpdateBytes) {
        throw const FormatException('Unsafe bundle entry');
      }
      total += entry.size;
      if (total > 2 * 1024 * 1024 * 1024)
        throw const FormatException('Bundle too large');
    }
    await destination.create();
    for (final entry in archive) {
      final parts = entry.name
          .split('/')
          .where((s) => s.isNotEmpty)
          .skip(1)
          .toList();
      if (parts.isEmpty) continue;
      final outputPath = p.joinAll([destination.path, ...parts]);
      if (!p.isWithin(destination.path, outputPath))
        throw const FormatException('Bundle escaped');
      if (!entry.isFile) {
        await Directory(outputPath).create(recursive: true);
        continue;
      }
      await File(outputPath).parent.create(recursive: true);
      final output = OutputFileStream(outputPath);
      try {
        entry.writeContent(output);
      } finally {
        await output.close();
      }
      if (platform == 'linux') {
        // Never restore setuid/setgid or writable-by-everyone archive modes.
        final mode = (entry.mode & 0x49) != 0 ? '755' : '644';
        final result = await Process.run('chmod', [mode, '--', outputPath]);
        if (result.exitCode != 0)
          throw const FileSystemException('Cannot set executable permissions');
      }
    }
  } finally {
    await input.close();
    await tarInput?.close();
    if (tar != null && await tar.exists()) await tar.delete();
  }
}

typedef LaunchAndCheck = Future<bool> Function(
  Directory root,
  String nonce,
  int build,
);

Future<void> validatePreparedBundle(
  Directory next,
  UpdateManifest release,
) async {
  final identity = await installationIdentity(next);
  if (identity['build'] != release.build ||
      identity['platform'] != release.platform) {
    throw const FormatException(
      'Prepared bundle does not match signed release',
    );
  }
  for (final file in [
    release.platform == 'windows'
        ? 'lab_inventory_client.exe'
        : 'lab_inventory_client',
    'client_update_helper${release.platform == 'windows' ? '.exe' : ''}',
    release.platform == 'windows' ? 'flutter_windows.dll' : 'lib/libapp.so',
    'data/flutter_assets/NOTICES.Z',
  ]) {
    if (!await File(p.join(next.path, file)).exists())
      throw const FormatException('Incomplete application bundle');
  }
}

Future<bool> launchAndCheck(Directory root, String nonce, int build) async {
  final executable = p.join(
    root.path,
    Platform.isWindows ? 'lab_inventory_client.exe' : 'lab_inventory_client',
  );
  final process = await Process.start(
    executable,
    [],
    workingDirectory: root.path,
    environment: {'LAB_UPDATE_NONCE': nonce},
  );
  unawaited(process.stdout.drain<void>());
  unawaited(process.stderr.drain<void>());
  var exited = false;
  unawaited(
    process.exitCode.then((_) {
      exited = true;
    }),
  );
  for (var attempt = 0; attempt < 60; attempt++) {
    await Future<void>.delayed(const Duration(milliseconds: 500));
    if (exited) return false;
    final ready = File(p.join(root.path, '.client-update-ready.json'));
    if (await ready.exists()) {
      try {
        final report = jsonDecode(await ready.readAsString()) as Map;
        if (report['nonce'] == nonce && report['build'] == build) return true;
      } catch (_) {
        /* Ignore incomplete readiness writes. */
      }
    }
  }
  // PID is exclusively the child launched above. Never find/kill by app name.
  if (!exited) {
    process.kill();
    await process.exitCode.timeout(const Duration(seconds: 5));
  }
  return false;
}

Future<void> _renameDirectory(Directory from, String to) async {
  for (var attempt = 0; ; attempt++) {
    try {
      await from.rename(to);
      return;
    } on FileSystemException {
      if (!Platform.isWindows || attempt >= 4) rethrow;
      await Future<void>.delayed(Duration(milliseconds: 200 * (attempt + 1)));
    }
  }
}

Future<void> replaceInstallation({
  required Directory root,
  required Directory next,
  required UpdateManifest release,
  LaunchAndCheck launch = launchAndCheck,
}) async {
  final resolved = await root.resolveSymbolicLinks();
  if (p.normalize(root.absolute.path) != p.normalize(resolved) ||
      p.dirname(resolved) == resolved ||
      await FileSystemEntity.isLink(next.path) ||
      p.dirname(next.absolute.path) != p.dirname(root.absolute.path)) {
    throw const FormatException('Unsafe installation boundary');
  }
  final old = await installationIdentity(root);
  final identity = await installationIdentity(next);
  if (old['build'] >= release.build ||
      identity['build'] != release.build ||
      identity['platform'] != release.platform ||
      old['platform'] != release.platform) {
    throw const FormatException('Bundle identity/version mismatch');
  }
  final executable = release.platform == 'windows'
      ? 'lab_inventory_client.exe'
      : 'lab_inventory_client';
  for (final file in [
    executable,
    'client_update_helper${release.platform == 'windows' ? '.exe' : ''}',
    release.platform == 'windows' ? 'flutter_windows.dll' : 'lib/libapp.so',
    'data/flutter_assets/NOTICES.Z',
  ]) {
    if (!await File(p.join(next.path, file)).exists())
      throw const FormatException('Incomplete application bundle');
  }
  final backup = Directory(
    p.join(
      root.parent.path,
      '.lab-client-previous-${old['build']}-${release.releaseId}',
    ),
  );
  final failed = Directory(
    p.join(root.parent.path, '.lab-client-failed-${release.releaseId}'),
  );
  if (await backup.exists() || await failed.exists())
    throw const FormatException('Retained version already exists');
  final state = File(
    p.join(root.parent.path, '.lab-client-update-${release.releaseId}.json'),
  );
  if (await state.exists())
    throw const FormatException('Unresolved install transaction');
  await state.writeAsString(
    jsonEncode({
      'phase': 'prepared',
      'root': root.path,
      'backup': backup.path,
      'next': next.path,
      'release_id': release.releaseId,
    }),
    flush: true,
  );
  await _renameDirectory(root, backup.path);
  try {
    await _renameDirectory(next, root.path);
    final nonce = base64UrlEncode(
      List.generate(24, (_) => Random.secure().nextInt(256)),
    );
    if (!await launch(root, nonce, release.build))
      throw const FormatException('New application did not become ready');
    await state.writeAsString(
      jsonEncode({
        'phase': 'complete',
        'root': root.path,
        'backup': backup.path,
        'release_id': release.releaseId,
      }),
      flush: true,
    );
  } catch (_) {
    if (await root.exists()) await _renameDirectory(root, failed.path);
    await _renameDirectory(backup, root.path);
    await state.writeAsString(
      jsonEncode({
        'phase': 'rolled_back',
        'root': root.path,
        'failed': failed.path,
        'release_id': release.releaseId,
      }),
      flush: true,
    );
    // Restart the old app; never delete either retained bundle or user data.
    if (identical(launch, launchAndCheck)) {
      await Process.start(
        p.join(root.path, executable),
        [],
        mode: ProcessStartMode.detached,
      );
    }
    rethrow;
  }
}

Future<void> runDesktopUpdate(File request) async {
  if (await request.length() > 131072)
    throw const FormatException('Install request too large');
  final args = jsonDecode(await request.readAsString()) as Map<String, dynamic>;
  final release = await UpdateManifest.verify(
    Map<String, dynamic>.from(args['envelope'] as Map),
  );
  if (release.platform != Platform.operatingSystem ||
      args['current_build'] is! int ||
      release.build <= (args['current_build'] as int) ||
      args['pid'] is! int)
    throw const FormatException('Invalid install request');
  final package = File(args['package'] as String).absolute;
  if (!p.isWithin(request.parent.absolute.path, package.path) ||
      await FileSystemEntity.isLink(package.path)) {
    throw const FormatException('Package outside update cache');
  }
  await verifyUpdateFile(package, release);
  final executable = File(args['executable'] as String).absolute;
  if (p.basename(executable.path) !=
      (Platform.isWindows
          ? 'lab_inventory_client.exe'
          : 'lab_inventory_client')) {
    throw const FormatException('Invalid application executable');
  }
  final root = executable.parent;
  final next = Directory(
    p.join(root.parent.path, '.lab-client-next-${release.releaseId}'),
  );
  final current = await installationIdentity(root);
  if (current['build'] != args['current_build'] ||
      release.build <= (current['build'] as int)) {
    throw const FormatException('Current installation version mismatch');
  }
  await extractBundle(package, next, release.platform);
  await validatePreparedBundle(next, release);
  await File('${request.path}.prepared')
      .writeAsString(release.releaseId, flush: true);
  // Wait for exactly the invoking process. Abort if another process holds files.
  for (var attempt = 0; attempt < 120; attempt++) {
    bool running;
    if (Platform.isWindows) {
      final result = await Process.run('tasklist', [
        '/FI',
        'PID eq ${args['pid']}',
        '/FO',
        'CSV',
        '/NH',
      ]);
      running = RegExp('"${args['pid']}"').hasMatch('${result.stdout}');
    } else {
      running = await Directory('/proc/${args['pid']}').exists();
    }
    if (!running && await File('${request.path}.continue').exists()) {
      await replaceInstallation(root: root, next: next, release: release);
      return;
    }
    await Future<void>.delayed(const Duration(milliseconds: 500));
  }
  throw const FormatException(
    'Application still running; retained staged bundle',
  );
}
