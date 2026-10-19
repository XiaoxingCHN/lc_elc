import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../providers/offline_providers.dart';
import '../unified_routes.dart';

/// The "查看本机缓存资料" entry for the LOGIN screen.
///
/// Why it must exist: at a cold start the server may be unreachable, automatic
/// login fails, and the router keeps the operator on the login screen. Without
/// this entry a previously cached manual/image would be unreachable even though it
/// is on disk. It opens the SAME unified library in read-only offline mode.
///
/// Integration (owned by the auth worker - this widget only builds UI):
///
/// ```dart
/// // lib/screens/login_screen.dart, e.g. under the form:
/// const OfflineCatalogEntryButton(),
/// ```
///
/// And the router must let an UNAUTHENTICATED operator reach `/catalog?offline=1`
/// while keeping every other route behind the login gate. Nothing else changes:
/// this entry touches no credential and writes no login state, so the 10-day rule
/// and the stored secret are unaffected.
class OfflineCatalogEntryButton extends ConsumerWidget {
  const OfflineCatalogEntryButton({super.key, this.margin});

  final EdgeInsetsGeometry? margin;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final entries = ref.watch(offlineCatalogEntriesProvider);
    final count = entries.valueOrNull?.length;
    final theme = Theme.of(context);

    return Padding(
      padding: margin ?? const EdgeInsets.only(top: 12),
      child: OutlinedButton.icon(
        onPressed: () => context.go(UnifiedRoutes.offlineCatalog),
        icon: const Icon(Icons.cloud_off_outlined, size: 18),
        label: Text(
          count == null
              ? '查看本机缓存资料'
              : (count == 0 ? '本机暂无缓存资料' : '查看本机缓存资料（$count 条）'),
          style: theme.textTheme.bodyMedium,
        ),
      ),
    );
  }
}

/// Short, honest note shown next to the entry.
const String offlineEntryNotice = '无需登录：只显示本机缓存的公开器件资料'
    '（图片、参数、手册），不含库存、SN、库位与追溯记录，也不能进行任何库存操作。';
