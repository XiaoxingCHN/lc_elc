import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/auth_provider.dart';

/// Startup screen.
///
/// Shown while the remembered account is read and - when it is allowed - the
/// single automatic sign-in attempt runs. Keeping this as the initial route is
/// what prevents the login form from flashing before the app knows whether the
/// operator is already signed in.
class SplashScreen extends ConsumerStatefulWidget {
  const SplashScreen({super.key});

  @override
  ConsumerState<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends ConsumerState<SplashScreen> {
  @override
  void initState() {
    super.initState();
    // After the first frame: bootstrap() flips provider state, and mutating a
    // provider while the very first frame is building is not allowed.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      ref.read(authProvider.notifier).bootstrap();
    });
  }

  @override
  Widget build(BuildContext context) {
    final authState = ref.watch(authProvider);

    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                const Icon(Icons.inventory_2, size: 64, color: Colors.blue),
                const SizedBox(height: 24),
                const Text(
                  '实验室元器件库存系统',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold),
                ),
                const SizedBox(height: 24),
                const SizedBox(
                  width: 28,
                  height: 28,
                  child: CircularProgressIndicator(strokeWidth: 3),
                ),
                const SizedBox(height: 16),
                Text(
                  authState.status == AuthStatus.authenticating
                      ? '正在自动登录…'
                      : '正在读取本机保存的登录信息…',
                  style: const TextStyle(fontSize: 13, color: Colors.black54),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
