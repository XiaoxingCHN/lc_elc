import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import 'update_manifest.dart';
import 'update_transport.dart';

enum UpdatePhase {
  idle,
  checking,
  current,
  unavailable,
  available,
  downloading,
  ready,
  error,
}

class UpdateController extends ChangeNotifier {
  UpdateController({
    required this.transport,
    required this.platform,
    required this.arch,
    required this.build,
    required this.directory,
    required this.facts,
    required this.unmetered,
    required this.authenticated,
    required this.readSequence,
    required this.saveSequence,
    this.keys = updateTrustedKeys,
  });
  final UpdateTransport transport;
  final String platform, arch;
  final int build;
  final Future<Directory> Function() directory;
  final Future<Map<String, int>> Function() facts;
  final Future<bool> Function() unmetered;
  final bool Function() authenticated;
  final Future<int> Function() readSequence;
  final Future<void> Function(int) saveSequence;
  final Map<String, String> keys;
  UpdatePhase phase = UpdatePhase.idle;
  UpdateManifest? release;
  File? package;
  String message = '';
  int received = 0;
  CancelToken? _token;
  Timer? _retry;
  int _failures = 0;
  bool _disposed = false, _busy = false, _foreground = true;
  DateTime? _lastCheck;
  void resume() {
    _foreground = true;
    if (phase == UpdatePhase.available) {
      unawaited(autoDownload());
    } else if (phase != UpdatePhase.ready &&
        (_lastCheck == null ||
            DateTime.now().difference(_lastCheck!) >=
                const Duration(seconds: 10))) {
      unawaited(check());
    }
  }

  void pause() {
    _foreground = false;
    _retry?.cancel();
  }

  void connected() {
    if (phase == UpdatePhase.available && authenticated()) {
      unawaited(autoDownload());
      return;
    }
    if ((phase == UpdatePhase.error || phase == UpdatePhase.idle) &&
        (_lastCheck == null ||
            DateTime.now().difference(_lastCheck!) >
                const Duration(seconds: 10)))
      unawaited(check());
  }

  void _set(UpdatePhase next, String text) {
    if (_disposed) return;
    phase = next;
    message = text;
    notifyListeners();
  }

  Future<void> check() async {
    if (_disposed || _busy || !_foreground || build <= 0) return;
    _busy = true;
    _retry?.cancel();
    _token = CancelToken();
    _lastCheck = DateTime.now();
    _set(UpdatePhase.checking, '正在检查更新');
    try {
      final envelope = await transport.check(platform, arch, _token!);
      if (_disposed) return;
      if (envelope == null) {
        _failures = 0;
        release = null;
        _set(UpdatePhase.unavailable, '服务器尚未发布更新');
        return;
      }
      final candidate = await UpdateManifest.verify(envelope, keys: keys);
      final highest = await readSequence();
      final compatible = candidate.matches(
        platform,
        arch,
        build,
        highest,
        await facts(),
      );
      if (_disposed) return;
      if (candidate.sequence < highest) throw const FormatException('拒绝过期更新清单');
      await saveSequence(candidate.sequence);
      _failures = 0;
      if (!compatible) {
        release = null;
        _set(
          UpdatePhase.current,
          candidate.build <= build ? '当前已是最新版本' : '暂无适合此设备的更新',
        );
        return;
      }
      release = candidate;
      _set(UpdatePhase.available, authenticated() ? '发现新版本' : '发现新版本，登录后下载');
    } on UpdateEndpointUnavailable {
      if (!_disposed) {
        release = null;
        _set(UpdatePhase.unavailable, '服务器可连接，更新接口未就绪（404），请联系管理员');
      }
    } catch (_) {
      if (!_disposed) {
        _set(UpdatePhase.error, '暂时无法检查更新，可稍后重试');
        const delays = [30, 120, 300, 900];
        final delay = delays[_failures.clamp(0, delays.length - 1)];
        _failures++;
        if (_foreground) _retry = Timer(Duration(seconds: delay), check);
      }
    } finally {
      _busy = false;
    }
    if (!_disposed && phase == UpdatePhase.available) await autoDownload();
  }

  Future<void> autoDownload() async {
    if (!_disposed &&
        !_busy &&
        phase == UpdatePhase.available &&
        authenticated() &&
        await unmetered())
      await download();
  }

  Future<void> download() async {
    if (_disposed || _busy || release == null || !authenticated()) return;
    _busy = true;
    _retry?.cancel();
    _token = CancelToken();
    received = 0;
    final targetRelease = release!;
    File? temp;
    try {
      final root = await directory();
      if (_disposed) return;
      await root.create(recursive: true);
      final finalFile = File(
        '${root.path}/${targetRelease.releaseId}-${targetRelease.digest}.${targetRelease.platform == 'android' ? 'apk' : 'package'}',
      );
      if (await finalFile.exists()) {
        try {
          await verifyUpdateFile(finalFile, targetRelease);
        } catch (_) {
          await finalFile.delete();
          rethrow;
        }
      } else {
        temp = File(
          '${finalFile.path}.${DateTime.now().microsecondsSinceEpoch}.part',
        );
        _set(UpdatePhase.downloading, '正在下载更新');
        await transport.download(targetRelease, temp, _token!, (value) {
          if (!_disposed) {
            received = value;
            notifyListeners();
          }
        });
        if (_disposed) return;
        await verifyUpdateFile(temp, targetRelease);
        await temp.rename(finalFile.path);
      }
      if (_disposed) return;
      package = finalFile;
      _set(UpdatePhase.ready, '更新已就绪');
    } catch (_) {
      if (!_disposed) _set(UpdatePhase.available, '下载未完成，可重新下载');
    } finally {
      try {
        if (temp != null && await temp.exists()) await temp.delete();
      } on FileSystemException {
        /* A locked partial file must not crash the app. */
      }
      _busy = false;
    }
  }

  void cancelDownload() {
    _token?.cancel('user cancelled');
  }

  @override
  void dispose() {
    _disposed = true;
    _retry?.cancel();
    _token?.cancel('scope closed');
    super.dispose();
  }
}
