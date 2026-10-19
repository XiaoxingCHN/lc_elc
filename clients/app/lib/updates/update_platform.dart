import 'dart:ffi';
import 'dart:io';

import 'package:flutter/services.dart';

import 'update_manifest.dart';
import 'install_request.dart';

const updateChannel = MethodChannel('lab/client_update');

class UpdatePlatform {
  String get platform => Platform.operatingSystem;
  String get arch => Platform.isAndroid
      ? 'universal'
      : ([Abi.windowsArm64, Abi.linuxArm64].contains(Abi.current())
            ? 'arm64'
            : 'x64');
  int get build => const int.fromEnvironment('FLUTTER_BUILD_NUMBER');
  String get version =>
      const String.fromEnvironment('FLUTTER_BUILD_NAME', defaultValue: '开发版本');
  Future<Map<String, int>> facts() async {
    if (Platform.isAndroid || Platform.isWindows) {
      final data = await updateChannel.invokeMapMethod<String, dynamic>(
        'facts',
      );
      return {
        for (final e in (data ?? {}).entries)
          if (e.value is int) e.key: e.value as int,
      };
    }
    final result = await Process.run('getconf', [
      'GNU_LIBC_VERSION',
    ]).timeout(const Duration(seconds: 2));
    final match = RegExp(r'(\d+)\.(\d+)').firstMatch('${result.stdout}');
    return match == null
        ? {}
        : {'glibc': int.parse(match[1]!) * 1000 + int.parse(match[2]!)};
  }

  Future<bool> unmetered() async {
    try {
      if (!Platform.isLinux)
        return await updateChannel.invokeMethod<bool>('unmetered') ?? false;
      final result = await Process.run('gdbus', [
        'call',
        '--system',
        '--dest',
        'org.freedesktop.NetworkManager',
        '--object-path',
        '/org/freedesktop/NetworkManager',
        '--method',
        'org.freedesktop.DBus.Properties.Get',
        'org.freedesktop.NetworkManager',
        'Metered',
      ]).timeout(const Duration(seconds: 2));
      return result.exitCode == 0 &&
          RegExp(r'uint32 (2|4)\b').hasMatch('${result.stdout}');
    } catch (_) {
      return false;
    }
  }

  Future<void> install(
    File file,
    UpdateManifest manifest,
    Directory cache,
  ) async {
    if (Platform.isAndroid) {
      await updateChannel.invokeMethod<void>('install', {
        'path': file.path,
        'build': manifest.build,
        'sha256': manifest.digest,
        'size': manifest.size,
      });
      return;
    }
    final executable = File(Platform.resolvedExecutable).absolute;
    final helper = File(
      '${executable.parent.path}/client_update_helper${Platform.isWindows ? '.exe' : ''}',
    );
    if (!await helper.exists()) throw StateError('此安装包缺少更新助手，请安装完整客户端包');
    final request = File(
      '${cache.path}/install-${manifest.releaseId}-${DateTime.now().microsecondsSinceEpoch}.json',
    );
    await request.writeAsString(
      encodeInstallRequest(file, manifest, executable, pid),
    );
    final stagedHelper = await helper.copy(
      '${cache.path}/update-helper-$pid-${DateTime.now().microsecondsSinceEpoch}${Platform.isWindows ? '.exe' : ''}',
    );
    if (Platform.isLinux) {
      final chmod = await Process.run('chmod', [
        '700',
        '--',
        stagedHelper.path,
      ]);
      if (chmod.exitCode != 0) throw StateError('更新助手不可执行');
    }
    await Process.start(stagedHelper.path, [
      request.path,
    ], mode: ProcessStartMode.detached);
    for (var attempt = 0; attempt < 240; attempt++) {
      if (await File('${request.path}.prepared').exists()) {
        await File('${request.path}.continue')
            .writeAsString(manifest.releaseId, flush: true);
        exit(0);
      }
      if (await File('${request.path}.result').exists())
        throw StateError('更新助手准备失败');
      await Future<void>.delayed(const Duration(milliseconds: 500));
    }
    throw StateError('更新助手准备超时，保留当前版本');
  }
}
