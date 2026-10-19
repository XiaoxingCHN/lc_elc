import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../providers/auth_provider.dart';
import '../routes/app_router.dart';
import 'update_controller.dart';
import 'update_platform.dart';
import 'update_transport.dart';

final updatePlatformProvider = Provider<UpdatePlatform>(
  (ref) => UpdatePlatform(),
);
final updateControllerProvider = ChangeNotifierProvider<UpdateController>((
  ref,
) {
  final client = ref.watch(odooClientProvider);
  final target = ref.watch(
    authProvider.select(
      (a) => (
        a.baseUrl ?? a.savedAccount?.scope.baseUrl ?? client.baseUrl,
        a.database ?? a.savedAccount?.scope.database ?? client.database,
        a.sessionIdentity,
      ),
    ),
  );
  final native = ref.watch(updatePlatformProvider);
  final scope = sha256
      .convert(utf8.encode('${target.$1}|${target.$2}'))
      .toString();
  final sequenceKey =
      'client_update.sequence.${native.platform}.${native.arch}';
  final controller = UpdateController(
    transport: ServerUpdateTransport(client, target.$1),
    platform: native.platform,
    arch: native.arch,
    build: native.build,
    directory: () async => Directory(
      '${(await getTemporaryDirectory()).path}/client-updates/$scope',
    ),
    facts: native.facts,
    unmetered: native.unmetered,
    authenticated: () =>
        client.isAuthenticated &&
        client.baseUrl == target.$1 &&
        client.database == target.$2,
    readSequence: () async =>
        (await SharedPreferences.getInstance()).getInt(sequenceKey) ?? 0,
    saveSequence: (value) async {
      await (await SharedPreferences.getInstance()).setInt(sequenceKey, value);
    },
  );
  final subscription = client.updateConnectionEvents.listen(
    (_) => controller.connected(),
  );
  ref.onDispose(subscription.cancel);
  if (native.build > 0 && target.$1.isNotEmpty)
    Future.microtask(controller.check);
  return controller;
});

class UpdateHost extends ConsumerStatefulWidget {
  const UpdateHost({super.key, required this.child});
  final Widget child;
  @override
  ConsumerState<UpdateHost> createState() => _UpdateHostState();
}

class _UpdateHostState extends ConsumerState<UpdateHost>
    with WidgetsBindingObserver {
  UpdateController? _current;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    _current?.pause();
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    final c = ref.read(updateControllerProvider);
    if (state == AppLifecycleState.resumed)
      c.resume();
    else
      c.pause();
  }

  @override
  Widget build(BuildContext context) {
    final c = ref.watch(updateControllerProvider);
    _current = c;
    final visible = [
      UpdatePhase.available,
      UpdatePhase.downloading,
      UpdatePhase.ready,
    ].contains(c.phase);
    return Column(
      children: [
        Expanded(child: widget.child),
        if (visible)
          Material(
            color: Theme.of(context).colorScheme.surfaceContainerHigh,
            child: SafeArea(
              top: false,
              child: ListTile(
                leading: const Icon(Icons.system_update_alt),
                title: Text(
                  '${c.message}${c.release == null ? '' : ' · ${c.release!.version}'}',
                ),
                subtitle: c.phase == UpdatePhase.downloading
                    ? LinearProgressIndicator(
                        value: c.release == null
                            ? null
                            : c.received / c.release!.size,
                      )
                    : null,
                onTap: () => showClientUpdates(context),
                trailing: const Icon(Icons.chevron_right),
              ),
            ),
          ),
      ],
    );
  }
}

class ClientUpdateButton extends StatelessWidget {
  const ClientUpdateButton({super.key});
  @override
  Widget build(BuildContext context) => IconButton(
    tooltip: '关于与更新',
    icon: const Icon(Icons.system_update_alt),
    onPressed: () => showClientUpdates(context),
  );
}

void showClientUpdates(BuildContext context) {
  showModalBottomSheet<void>(
    context: rootNavigatorKey.currentContext ?? context,
    useSafeArea: true,
    isScrollControlled: true,
    isDismissible: false,
    enableDrag: false,
    builder: (context) => const UpdateSheet(),
  );
}

class UpdateSheet extends ConsumerStatefulWidget {
  const UpdateSheet({super.key});
  @override
  ConsumerState<UpdateSheet> createState() => _UpdateSheetState();
}

class _UpdateSheetState extends ConsumerState<UpdateSheet> {
  bool _installing = false;
  String? _error;
  Future<void> _install(UpdateController c) async {
    final client = ref.read(odooClientProvider);
    bool idle() =>
        !client.hasActiveRequests &&
        ['/catalog', '/login'].contains(
          ref.read(appRouterProvider).routeInformationProvider.value.uri.path,
        );
    if (!idle()) {
      setState(() => _error = '请先完成当前操作，返回仓库或登录页后安装。');
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('安装更新？'),
        content: const Text('应用将关闭并安装新版本。账号和已有数据会保留。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('稍后'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('安装'),
          ),
        ],
      ),
    );
    if (!mounted ||
        confirmed != true ||
        !identical(ref.read(updateControllerProvider), c))
      return;
    if (!idle()) {
      setState(() => _error = '仍有操作进行中，请稍后安装。');
      return;
    }
    setState(() {
      _installing = true;
      _error = null;
    });
    try {
      final file = c.package!;
      await verifyUpdateFile(file, c.release!);
      if (!idle() || !client.beginClientInstall()) throw StateError('仍有操作进行中');
      await ref
          .read(updatePlatformProvider)
          .install(file, c.release!, file.parent);
    } catch (_) {
      if (mounted) setState(() => _error = '安装未开始，请检查安装权限或重新下载完整包。');
    } finally {
      client.endClientInstall();
      if (mounted) setState(() => _installing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = ref.watch(updateControllerProvider);
    final native = ref.watch(updatePlatformProvider);
    final release = c.release;
    final busy =
        c.phase == UpdatePhase.checking ||
        c.phase == UpdatePhase.downloading ||
        _installing;
    final authenticated = ref.watch(
      authProvider.select((s) => s.isAuthenticated),
    );
    return PopScope(
      canPop: !_installing,
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.sizeOf(context).height * .85,
        ),
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 560),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          '关于与更新',
                          style: Theme.of(context).textTheme.headlineSmall,
                        ),
                      ),
                      IconButton(
                        tooltip: '关闭',
                        onPressed: _installing
                            ? null
                            : () => Navigator.pop(context),
                        icon: const Icon(Icons.close),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  Text('当前版本 ${native.version}（${native.build}）'),
                  if (c.transport is ServerUpdateTransport) ...[
                    const SizedBox(height: 8),
                    Text(
                      '更新服务器：${Uri.parse((c.transport as ServerUpdateTransport).server).origin}',
                    ),
                  ],
                  const SizedBox(height: 12),
                  Text(c.message.isEmpty ? '联网后自动检查，非计费网络后台下载。' : c.message),
                  if (release != null) ...[
                    const SizedBox(height: 16),
                    Text(
                      '新版本 ${release.version} · ${(release.size / 1048576).toStringAsFixed(1)} MB',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    if (release.notes.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        child: Text(release.notes),
                      ),
                  ],
                  if (c.phase == UpdatePhase.downloading) ...[
                    const SizedBox(height: 16),
                    LinearProgressIndicator(value: c.received / release!.size),
                    TextButton(
                      onPressed: c.cancelDownload,
                      child: const Text('取消下载'),
                    ),
                  ],
                  if (_error != null)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 12),
                      child: Text(
                        _error!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ),
                  const SizedBox(height: 20),
                  if (c.phase == UpdatePhase.ready)
                    FilledButton(
                      onPressed: busy ? null : () => _install(c),
                      child: const Text('安装更新'),
                    )
                  else if (c.phase == UpdatePhase.available)
                    FilledButton(
                      onPressed: busy || !authenticated ? null : c.download,
                      child: Text(authenticated ? '下载更新（可能产生流量）' : '请先登录后下载'),
                    )
                  else
                    OutlinedButton(
                      onPressed: busy || native.build <= 0 ? null : c.check,
                      child: const Text('检查更新'),
                    ),
                  const SizedBox(height: 8),
                  Text(
                    _installing ? '正在准备安装，请稍候。' : '更新不会中断当前库存操作。',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
