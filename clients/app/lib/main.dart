import 'widgets/lab_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'config/odoo_config.dart';
import 'features/unified/providers/unified_providers.dart';
import 'providers/auth_provider.dart';
import 'routes/app_router.dart';
import 'services/odoo_client.dart';

void main() {
  // Bindings first: the secure-storage plugin (remembered login) is used from
  // the splash screen before the first frame completes.
  WidgetsFlutterBinding.ensureInitialized();

  // ONE OdooClient for the whole app.
  //
  // The login flow authenticates this instance, `callRoute` sends every business
  // call on its session cookie jar, and the unified UI caches captured images /
  // manuals through `fetchAssetBytes` on the SAME jar. Creating a second client
  // anywhere would mean a second, empty cookie jar and anonymous business calls.
  final client = OdooClient(
    baseUrl: OdooConfig.defaultBaseUrl,
    database: OdooConfig.defaultDatabase,
  );

  runApp(
    ProviderScope(
      overrides: [
        odooClientProvider.overrideWithValue(client),
        assetAuthenticatedFetcherProvider
            .overrideWithValue(client.fetchAssetBytes),
      ],
      child: const MyApp(),
    ),
  );
}

class MyApp extends ConsumerWidget {
  const MyApp({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(appRouterProvider);

    return MaterialApp.router(
      title: '实验室库存系统',
      theme: LabTheme.light,
      builder: (context, child) => DecoratedBox(decoration: LabTheme.background, child: child ?? const SizedBox.shrink()),
      routerConfig: router,
      debugShowCheckedModeBanner: false,
    );
  }
}
