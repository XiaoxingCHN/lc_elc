import 'package:lab_inventory_client/widgets/lab_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../config/odoo_config.dart';
import '../updates/update_ui.dart';
import '../features/unified/unified_routes.dart';
import '../providers/auth_provider.dart';
import '../routes/offline_access.dart';
import '../services/login_memory_store.dart';

/// Login screen.
///
/// One switch only - "记住登录" - because the operator-facing promise is a
/// single one: *sign in here, and this machine will sign you in again for the
/// next 10 days*. Server address, database and user name are always remembered
/// after a successful login; the password is handed to the operating system key
/// store (Windows DPAPI, Android Keystore, Linux libsecret) and only after the
/// server accepted it. Nothing here is ever written to a plain file.
///
/// Server address, database and login name are pre-filled from the build-time
/// `--dart-define` values when those were supplied, and are always editable.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  late final TextEditingController _urlController;
  late final TextEditingController _dbController;
  late final TextEditingController _userController;
  late final TextEditingController _passwordController;

  bool _passwordVisible = false;
  String? _formError;
  String? _scopeChangedNotice;

  /// The single operator choice on this screen.
  bool _rememberLogin = OdooConfig.rememberLoginDefault;

  /// Set once the remembered account has been applied, so later rebuilds never
  /// overwrite what the operator is typing.
  /// True while the code (not the operator) edits the text fields.
  bool _programmaticEdit = false;

  /// Account the currently filled password belongs to. When the operator changes
  /// the server, database or user name this no longer matches and the password
  /// is dropped, so an old password can never be sent to a new address.
  LoginScope? _passwordScope;

  @override
  void initState() {
    super.initState();

    final authState = ref.read(authProvider);
    final saved = authState.savedAccount;

    _urlController = TextEditingController(
      text: saved?.baseUrl ?? OdooConfig.defaultBaseUrl,
    );
    _dbController = TextEditingController(
      text: saved?.database ?? OdooConfig.defaultDatabase,
    );
    _userController = TextEditingController(
      text: saved?.login ?? OdooConfig.defaultLogin,
    );
    _passwordController = TextEditingController();

    _rememberLogin = authState.rememberLogin;

    _urlController.addListener(_onIdentityFieldChanged);
    _dbController.addListener(_onIdentityFieldChanged);
    _userController.addListener(_onIdentityFieldChanged);

    if (saved != null) {
      // Pre-fill the password only when the operator asked to be remembered and
      // the stored credential is still inside the freshness window (this also
      // happens after a failed automatic attempt, e.g. a server that was down).
      WidgetsBinding.instance.addPostFrameCallback((_) => _prefillPassword());
    }
  }

  @override
  void dispose() {
    _urlController.dispose();
    _dbController.dispose();
    _userController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  LoginScope _currentScope() => LoginScope.fromInput(
        baseUrl: _urlController.text,
        database: _dbController.text,
        login: _userController.text,
      );

  /// The typed password belongs to the account captured in [_passwordScope].
  /// Any change of server/database/user invalidates it immediately.
  void _onIdentityFieldChanged() {
    if (_programmaticEdit) return;
    final watched = _passwordScope;
    if (watched == null || _currentScope() == watched) return;

    _programmaticEdit = true;
    _passwordController.clear();
    _passwordScope = null;
    _programmaticEdit = false;

    setState(() {
      _scopeChangedNotice = '服务器、数据库或用户名已修改，请重新输入该账号的密码。';
    });
  }

  Future<void> _prefillPassword() async {
    if (!mounted) return;

    final authState = ref.read(authProvider);
    final saved = authState.savedAccount;
    if (saved == null) return;

    final scope = saved.scope;
    final password = await ref.read(authProvider.notifier).revealRememberedPassword(
          baseUrl: scope.baseUrl,
          database: scope.database,
          login: scope.login,
        );

    if (!mounted || password == null || password.isEmpty) return;
    // The operator may have started typing while the key store was read.
    if (_passwordController.text.isNotEmpty) return;
    if (_currentScope() != scope) return;

    _programmaticEdit = true;
    _passwordController.text = password;
    _programmaticEdit = false;
    _passwordScope = scope;
    setState(() {});
  }

  String? _validate() {
    final url = OdooConfig.normalizeBaseUrl(_urlController.text);
    if (url.isEmpty) {
      return '请填写 Odoo 服务器地址，例如 http://192.168.31.105:8069';
    }
    if (!OdooConfig.isValidBaseUrl(url)) {
      return '服务器地址必须以 http:// 或 https:// 开头';
    }
    if (_dbController.text.trim().isEmpty) {
      return '请填写 Odoo 数据库名';
    }
    if (_userController.text.trim().isEmpty) {
      return '请填写登录用户名';
    }
    if (_passwordController.text.isEmpty) {
      return '请填写登录密码';
    }
    return null;
  }

  Future<void> _handleLogin() async {
    final error = _validate();
    if (error != null) {
      setState(() => _formError = error);
      return;
    }

    setState(() {
      _formError = null;
      _scopeChangedNotice = null;
    });

    final scope = _currentScope();
    final notifier = ref.read(authProvider.notifier);
    // Navigation on success and the error snack bar are handled by the
    // ref.listen callback below.
    await notifier.login(
      baseUrl: scope.baseUrl,
      database: scope.database,
      login: scope.login,
      password: _passwordController.text,
      rememberLogin: _rememberLogin,
    );
  }

  Future<void> _onRememberLoginChanged(bool value) async {
    setState(() => _rememberLogin = value);

    // Switching it off erases the stored password for this exact account right
    // away - it must not survive until the next login.
    await ref.read(authProvider.notifier).setRememberLoginPreference(
          baseUrl: _urlController.text,
          database: _dbController.text,
          login: _userController.text,
          value: value,
        );
  }

  Future<void> _clearSavedPassword() async {
    final confirmed = await _confirm(
      title: '清除本机保存的密码？',
      message: '只删除这台机器上为该账号保存的密码，服务器地址、数据库和用户名仍会保留。',
    );
    if (!confirmed || !mounted) return;

    await ref.read(authProvider.notifier).forgetSavedPassword(
          baseUrl: _urlController.text,
          database: _dbController.text,
          login: _userController.text,
        );

    if (!mounted) return;
    _programmaticEdit = true;
    _passwordController.clear();
    _programmaticEdit = false;
    _passwordScope = null;
    setState(() {
      _rememberLogin = false;
      _scopeChangedNotice = null;
    });
  }

  Future<void> _clearAllRemembered() async {
    final confirmed = await _confirm(
      title: '清除记住的全部账号？',
      message: '将删除这台机器上记住的所有服务器、数据库、用户名和密码。此操作不可撤销。',
    );
    if (!confirmed || !mounted) return;

    await ref.read(authProvider.notifier).forgetAllRememberedLogins();
    if (!mounted) return;

    _programmaticEdit = true;
    _urlController.text = OdooConfig.defaultBaseUrl;
    _dbController.text = OdooConfig.defaultDatabase;
    _userController.text = OdooConfig.defaultLogin;
    _passwordController.clear();
    _programmaticEdit = false;
    _passwordScope = null;
    setState(() {
      _rememberLogin = OdooConfig.rememberLoginDefault;
      _scopeChangedNotice = null;
      _formError = null;
    });
  }

  Future<bool> _confirm({required String title, required String message}) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(title),
        content: Text(message),
        actions: [
          const ClientUpdateButton(),
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('清除'),
          ),
        ],
      ),
    );
    return result ?? false;
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authProvider);

    ref.listen<AuthState>(authProvider, (previous, next) {
      if (next.isAuthenticated) {
        // The signed-in home is the unified library (/catalog), not a
        // dashboard: list and captured data live in the same screen.
        context.go(UnifiedRoutes.catalog);
      } else if (next.hasError && next.errorMessage != null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(next.errorMessage!),
            backgroundColor: Colors.red,
            duration: const Duration(seconds: 8),
          ),
        );
      }
    });

    // Safety net: the router keeps the splash screen up while initializing, so
    // this only happens if the screen is built directly.
    if (authState.isInitializing) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }

    final busy = authState.isLoading;
    final canRememberPassword = authState.canRememberPassword;

    return Scaffold(
      appBar: LabAppBar(
        title: const Text('实验室库存系统 - 登录'),
        centerTitle: true,
        actions: [
          PopupMenuButton<String>(
            tooltip: '登录记录',
            onSelected: (value) {
              if (value == 'password') {
                _clearSavedPassword();
              } else if (value == 'all') {
                _clearAllRemembered();
              }
            },
            itemBuilder: (context) => const [
              PopupMenuItem(
                value: 'password',
                child: Text('清除本机保存的密码'),
              ),
              PopupMenuItem(
                value: 'all',
                child: Text('清除记住的全部账号'),
              ),
            ],
          ),
        ],
      ),
      body: Center(
        child: SingleChildScrollView(
          child: Padding(
            padding: const EdgeInsets.all(24.0),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.inventory_2, size: 64, color: Colors.blue),
                  const SizedBox(height: 24),
                  const Text(
                    '实验室元器件库存系统',
                    style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 24),

                  // --- startup / auto-login outcome -------------------------
                  if (authState.noticeMessage != null) ...[
                    _Banner(
                      icon: Icons.info_outline,
                      color: Colors.amber,
                      text: authState.noticeMessage!,
                    ),
                    const SizedBox(height: 12),
                  ],
                  if (authState.errorMessage != null) ...[
                    _Banner(
                      icon: Icons.error_outline,
                      color: Colors.red,
                      text: authState.errorMessage!,
                    ),
                    const SizedBox(height: 12),
                  ],
                  if (_scopeChangedNotice != null) ...[
                    _Banner(
                      icon: Icons.sync_problem,
                      color: Colors.blueGrey,
                      text: _scopeChangedNotice!,
                    ),
                    const SizedBox(height: 12),
                  ],

                  TextField(
                    controller: _urlController,
                    enabled: !busy,
                    keyboardType: TextInputType.url,
                    autocorrect: false,
                    decoration: InputDecoration(
                      labelText: 'Odoo 服务器地址 *',
                      hintText: 'http://192.168.31.105:8069',
                      prefixIcon: const Icon(Icons.dns),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: _dbController,
                    enabled: !busy,
                    autocorrect: false,
                    decoration: InputDecoration(
                      labelText: '数据库名 *',
                      hintText: '例如 LcHardwareHouse',
                      prefixIcon: const Icon(Icons.storage),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: _userController,
                    enabled: !busy,
                    autocorrect: false,
                    decoration: InputDecoration(
                      labelText: '用户名 *',
                      prefixIcon: const Icon(Icons.person),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: _passwordController,
                    enabled: !busy,
                    obscureText: !_passwordVisible,
                    onSubmitted: (_) => busy ? null : _handleLogin(),
                    decoration: InputDecoration(
                      labelText: '密码 *',
                      prefixIcon: const Icon(Icons.lock),
                      suffixIcon: IconButton(
                        icon: Icon(
                          _passwordVisible
                              ? Icons.visibility
                              : Icons.visibility_off,
                        ),
                        onPressed: () {
                          setState(() => _passwordVisible = !_passwordVisible);
                        },
                      ),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(8),
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),

                  // --- the ONE switch the operator sees --------------------
                  // Material (not a decorated Container): a ListTile paints its
                  // background and ink splashes on the nearest Material, and a
                  // DecoratedBox in between would hide them.
                  Material(
                    color: canRememberPassword
                        ? Colors.blue.shade50
                        : Colors.orange.shade50,
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(8),
                      side: BorderSide(
                        color: canRememberPassword
                            ? Colors.blue.shade100
                            : Colors.orange.shade200,
                      ),
                    ),
                    child: SwitchListTile(
                      value: canRememberPassword && _rememberLogin,
                      onChanged: busy || !canRememberPassword
                          ? null
                          : _onRememberLoginChanged,
                      title: const Text(
                        '记住登录',
                        style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      subtitle: Text(
                        canRememberPassword
                            ? '10 天内再次打开自动登录，免输密码。'
                            : '当前系统无法安全保存密码，仍可直接登录。',
                        style: const TextStyle(fontSize: 11),
                      ),
                      secondary: Icon(
                        canRememberPassword ? Icons.key : Icons.key_off,
                        color: canRememberPassword
                            ? Colors.blue
                            : Colors.orange.shade800,
                      ),
                    ),
                  ),

                  if (_formError != null) ...[
                    const SizedBox(height: 16),
                    _Banner(
                      icon: Icons.warning_amber,
                      color: Colors.red,
                      text: _formError!,
                    ),
                  ],
                  const SizedBox(height: 24),
                  SizedBox(
                    width: double.infinity,
                    height: 48,
                    child: ElevatedButton(
                      onPressed: busy ? null : _handleLogin,
                      child: busy
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('登录'),
                    ),
                  ),
                  const SizedBox(height: 16),
                  Text(
                    '账号始终记住。连续 10 天未成功登录时，需要重新输入一次密码。',
                    style: TextStyle(fontSize: 11, color: Colors.grey.shade700),
                    textAlign: TextAlign.center,
                  ),
                  const SizedBox(height: 8),

                  // Read-only offline entry: the same unified library, showing
                  // only public catalog data that was cached while online. No
                  // sign-in, no inventory numbers, no stock operations.
                  TextButton.icon(
                    onPressed: busy
                        ? null
                        : () => context.go(OfflineAccess.catalogLocation()),
                    icon: const Icon(Icons.cloud_off, size: 18),
                    label: const Text('查看本机缓存资料'),
                  ),
                  Text(
                    '离线只读，不显示库存数量，不能入库/领料/打印。',
                    style: TextStyle(fontSize: 10, color: Colors.grey.shade600),
                    textAlign: TextAlign.center,
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

class _Banner extends StatelessWidget {
  const _Banner({
    required this.icon,
    required this.color,
    required this.text,
  });

  final IconData icon;
  final MaterialColor color;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: color.shade50,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.shade200),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: color.shade800),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              text,
              style: TextStyle(fontSize: 12, color: color.shade900),
            ),
          ),
        ],
      ),
    );
  }
}
