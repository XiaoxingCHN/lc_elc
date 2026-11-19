import 'dart:io' show Platform;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/auth_provider.dart';
import '../providers/lan_acceleration_provider.dart';
import '../routes/app_router.dart';
import '../updates/update_ui.dart';

/// Opens "服务器与内网加速".
///
/// Reachable from the login screen, the signed-in app bar and the LAN hint -
/// the hint lives above the Navigator, so the ROOT navigator context is used
/// (same pattern as "关于与更新").
void showLanAcceleration(BuildContext context) {
  showModalBottomSheet<void>(
    context: rootNavigatorKey.currentContext ?? context,
    useSafeArea: true,
    isScrollControlled: true,
    builder: (context) => const LanAccelerationSheet(),
  );
}

/// Entry-point icon used in app bars (next to [ClientUpdateButton]).
class LanAccelerationButton extends StatelessWidget {
  const LanAccelerationButton({super.key});

  @override
  Widget build(BuildContext context) => IconButton(
        tooltip: '服务器与内网加速',
        icon: const Icon(Icons.speed),
        onPressed: () => showLanAcceleration(context),
      );
}

class LanAccelerationSheet extends ConsumerStatefulWidget {
  const LanAccelerationSheet({super.key});

  @override
  ConsumerState<LanAccelerationSheet> createState() =>
      _LanAccelerationSheetState();
}

class _LanAccelerationSheetState extends ConsumerState<LanAccelerationSheet> {
  late final TextEditingController _url;
  late final TextEditingController _ssid;
  late final TextEditingController _login;
  late final TextEditingController _password;
  bool _busy = false;
  String? _error;
  String? _notice;

  @override
  void initState() {
    super.initState();
    final lan = ref.read(lanSettingsProvider);
    final auth = ref.read(authProvider);
    _url = TextEditingController(
      text: lan.lanBaseUrl.isEmpty ? OdooConfig.buildLanBaseUrl : lan.lanBaseUrl,
    );
    _ssid = TextEditingController(text: lan.ssid);
    _login = TextEditingController(
      text: auth.activeLogin ?? auth.savedAccount?.login ?? OdooConfig.defaultLogin,
    );
    _password = TextEditingController();
  }

  @override
  void dispose() {
    _url.dispose();
    _ssid.dispose();
    _login.dispose();
    _password.dispose();
    super.dispose();
  }

  String get _database =>
      ref.read(authProvider).database?.trim().isNotEmpty == true
          ? ref.read(authProvider).database!.trim()
          : OdooConfig.fallbackDatabase;

  bool get _isAuthenticated => ref.read(authProvider).isAuthenticated;

  void _saveLanInput() {
    ref.read(lanSettingsProvider.notifier).configure(
          lanBaseUrl: _url.text,
          ssid: _ssid.text,
        );
  }

  String? _validateLan() {
    final url = OdooConfig.normalizeBaseUrl(_url.text);
    if (url.isEmpty) return '请填写内网服务器地址，例如 http://192.168.31.105:8069';
    if (!OdooConfig.isValidBaseUrl(url)) {
      return '内网地址必须以 http:// 或 https:// 开头';
    }
    if (!OdooConfig.isPrivateNetworkHost(Uri.tryParse(url)?.host ?? '')) {
      return '内网加速只支持局域网地址（例如 192.168.x.x）。';
    }
    return null;
  }

  Future<void> _test() async {
    final error = _validateLan();
    if (error != null) {
      setState(() => _error = error);
      return;
    }
    if (_login.text.trim().isEmpty || _password.text.isEmpty) {
      setState(() => _error = '请填写用户名和密码后再测试连接。');
      return;
    }

    _saveLanInput();
    final notifier = ref.read(lanSettingsProvider.notifier)..beginTest();
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });

    final ok = await ref.read(authProvider.notifier).testConnection(
          baseUrl: _url.text,
          database: _database,
          login: _login.text,
          password: _password.text,
        );

    if (!mounted) return;
    notifier.finish(
      message: ok ? '连接成功：服务器接受了该账号。' : '连接失败：无法登录该内网服务器。',
      isError: !ok,
    );
    setState(() {
      _busy = false;
      _notice = ok ? '连接成功：服务器接受了该账号。' : null;
      _error = ok ? null : '连接失败：无法登录该内网服务器，请检查地址、用户名和密码。';
    });
  }

  Future<void> _switchToLan() async {
    final error = _validateLan();
    if (error != null) {
      setState(() => _error = error);
      return;
    }
    if (!_isAuthenticated) {
      setState(() => _error = '请先登录公网服务器，再切换到内网。');
      return;
    }
    if (_login.text.trim().isEmpty || _password.text.isEmpty) {
      setState(() => _error = '切换会重新验证账号，请填写用户名和密码。');
      return;
    }

    _saveLanInput();
    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });

    final ok = await ref.read(authProvider.notifier).switchServer(
          baseUrl: _url.text,
          database: _database,
          login: _login.text,
          password: _password.text,
        );

    if (!mounted) return;
    setState(() {
      _busy = false;
      if (ok) {
        _notice = '已切换到内网加速（仅本次运行有效，退出即清除）。';
        _password.clear();
        // A successful switch consumes the entered address/SSID: they are
        // cleared from memory as the task requires. The running session keeps
        // its connection; a later re-login re-adds the typed address.
        ref.read(lanSettingsProvider.notifier).clear();
      } else {
        _error = ref.read(authProvider).errorMessage ??
            '切换失败：当前仍连接原服务器，会话保持不变。';
      }
    });
  }

  Future<void> _switchToPublic() async {
    if (!_isAuthenticated) {
      setState(() => _error = '当前没有可切换的登录会话，请重新登录。');
      return;
    }
    if (_login.text.trim().isEmpty || _password.text.isEmpty) {
      setState(() => _error = '切回公网会重新验证账号，请填写用户名和密码。');
      return;
    }

    setState(() {
      _busy = true;
      _error = null;
      _notice = null;
    });

    final ok = await ref.read(authProvider.notifier).switchToPublic(
          baseUrl: OdooConfig.fallbackBaseUrl,
          database: _database,
          login: _login.text,
          password: _password.text,
        );

    if (!mounted) return;
    setState(() {
      _busy = false;
      if (ok) {
        _notice = '已切回公网服务器（${OdooConfig.fallbackBaseUrl}）。';
        _password.clear();
        ref.read(lanSettingsProvider.notifier).clear();
      } else {
        _error = ref.read(authProvider).errorMessage ??
            '切换失败：仍保持内网会话。';
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    final lan = ref.watch(lanSettingsProvider);
    final theme = Theme.of(context);
    final lanSession = auth.isAuthenticated &&
        (auth.baseUrl ?? '').startsWith('http://');
    final busy = _busy || auth.switching || lan.testing;

    return ConstrainedBox(
      constraints: BoxConstraints(
        maxHeight: MediaQuery.sizeOf(context).height * .9,
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
                        '服务器与内网加速',
                        style: theme.textTheme.headlineSmall,
                      ),
                    ),
                    IconButton(
                      tooltip: '关闭',
                      onPressed: busy ? null : () => Navigator.pop(context),
                      icon: const Icon(Icons.close),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  '当前服务器：${auth.baseUrl ?? '未登录'}',
                  style: theme.textTheme.bodySmall,
                ),
                const SizedBox(height: 12),

                // ---- memory-only warnings ---------------------------------
                const _Notice(
                  icon: Icons.memory,
                  text: '内网地址与 WiFi 名称仅本次运行有效，退出即清除，不写入本机记录。',
                ),
                const SizedBox(height: 8),
                const _Notice(
                  icon: Icons.warning_amber,
                  text: '内网为明文 HTTP，请仅在可信局域网使用；公网请使用 HTTPS。',
                  isWarning: true,
                ),
                // Android refuses cleartext at the OS level except for the
                // hosts baked into network_security_config.xml. Saying so here
                // is the difference between "切换失败" and an operator who knows
                // why: the app-level whitelist accepts any private address, the
                // platform does not.
                if (Platform.isAndroid) ...[
                  const SizedBox(height: 8),
                  const _Notice(
                    icon: Icons.android,
                    text: 'Android 系统只允许 ${OdooConfig.legacyLanHost} 使用明文 HTTP；'
                        '其它内网地址需要改用 HTTPS，否则连接会被系统拒绝。',
                    isWarning: true,
                  ),
                ],
                const SizedBox(height: 16),

                TextField(
                  controller: _url,
                  enabled: !busy,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: '内网服务器地址',
                    hintText: 'http://192.168.31.105:8069',
                    prefixIcon: Icon(Icons.dns),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _ssid,
                  enabled: !busy,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: 'WiFi 名称（可选）',
                    hintText: '实验室 WiFi 的 SSID',
                    prefixIcon: Icon(Icons.wifi),
                    helperText: '填写后，连接到该 WiFi 时会提示切换到内网加速。'
                        '有线接入时请留空：客户端会直接检测上面的内网地址是否可达。',
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _login,
                  enabled: !busy,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: '用户名',
                    prefixIcon: Icon(Icons.person),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _password,
                  enabled: !busy,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: '密码（切换时重新验证）',
                    prefixIcon: Icon(Icons.lock),
                  ),
                ),

                if (lan.lastDetectedSsid != null) ...[
                  const SizedBox(height: 8),
                  Text(
                    '当前 WiFi：${lan.lastDetectedSsid}',
                    style: theme.textTheme.bodySmall,
                  ),
                ],
                // No SSID (wired, or the platform cannot report one): show the
                // reachability probe instead, so the operator knows whether the
                // hint fired for a real reason.
                if ((lan.lastDetectedSsid ?? '').trim().isEmpty &&
                    lan.lanReachable != null) ...[
                  const SizedBox(height: 8),
                  Text(
                    lan.lanReachable!
                        ? '当前网络：未读到 WiFi 名称（多为有线接入），内网地址可达'
                        : '当前网络：未读到 WiFi 名称（多为有线接入），内网地址不可达',
                    style: theme.textTheme.bodySmall,
                  ),
                ],
                if (_error != null) ...[
                  const SizedBox(height: 12),
                  _Notice(
                    icon: Icons.error_outline,
                    text: _error!,
                    isWarning: true,
                  ),
                ],
                if (_notice != null) ...[
                  const SizedBox(height: 12),
                  _Notice(icon: Icons.check_circle_outline, text: _notice!),
                ],

                const SizedBox(height: 20),
                OutlinedButton.icon(
                  onPressed: busy ? null : _test,
                  icon: const Icon(Icons.network_check),
                  label: const Text('测试连接'),
                ),
                const SizedBox(height: 8),
                FilledButton.icon(
                  onPressed: busy || !auth.isAuthenticated ? null : _switchToLan,
                  icon: const Icon(Icons.speed),
                  label: const Text('切换到内网'),
                ),
                const SizedBox(height: 8),
                OutlinedButton.icon(
                  onPressed: busy || !lanSession ? null : _switchToPublic,
                  icon: const Icon(Icons.public),
                  label: const Text('切回公网'),
                ),
                const SizedBox(height: 12),
                Text(
                  '切换会在新服务器上重新验证账号；失败时保持当前会话与原账号不变。'
                  '内网加速会话不保留离线缓存。',
                  style: theme.textTheme.bodySmall,
                ),
                const SizedBox(height: 12),
                const Divider(),
                const SizedBox(height: 4),
                const ClientUpdateButton(),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Notice extends StatelessWidget {
  const _Notice({
    required this.icon,
    required this.text,
    this.isWarning = false,
  });

  final IconData icon;
  final String text;
  final bool isWarning;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final color = isWarning ? scheme.error : scheme.primary;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.4), width: 0.5),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: color),
          const SizedBox(width: 8),
          Expanded(
            child: Text(text, style: const TextStyle(fontSize: 12)),
          ),
        ],
      ),
    );
  }
}
