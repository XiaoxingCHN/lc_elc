import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../models/catalog_query.dart';
import '../models/identity.dart';
import '../providers/offline_providers.dart';
import '../unified_routes.dart';
import '../widgets/item_card.dart';
import '../widgets/media_view.dart';
import '../widgets/status_views.dart';

/// The banner that must be visible in every offline view.
///
/// The user's rule: the offline browser is NOT a signed-in session and must never
/// look like one.
class OfflineBanner extends StatelessWidget {
  const OfflineBanner({super.key, this.entryCount, this.detail = false});

  final int? entryCount;
  final bool detail;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      width: double.infinity,
      color: theme.colorScheme.tertiaryContainer,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      child: Row(
        children: <Widget>[
          const Icon(Icons.cloud_off, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              detail
                  ? '离线只读缓存资料：未登录服务器，不含库存、SN、库位与追溯记录。'
                  : '离线只读缓存资料：未登录服务器，仅显示曾浏览过的公开器件资料'
                      '${entryCount == null ? '' : '（本机共 $entryCount 条）'}。库存相关操作不可用。',
              style: theme.textTheme.labelSmall,
            ),
          ),
        ],
      ),
    );
  }
}

/// Read-only offline library - the SAME unified library, without a session.
///
/// It reuses [ItemCard] and the same visual language, but:
///   * rows come from the public catalog cache, filtered locally (there is no
///     server to page through);
///   * no stock figure, SN, bag or history is displayed - the cache cannot contain
///     them, and the card is told to hide stock entirely;
///   * every stock action is absent (no receipt / issue / label buttons).
class OfflineCatalogView extends ConsumerStatefulWidget {
  const OfflineCatalogView({super.key});

  @override
  ConsumerState<OfflineCatalogView> createState() => _OfflineCatalogViewState();
}

class _OfflineCatalogViewState extends ConsumerState<OfflineCatalogView> {
  final TextEditingController _search = TextEditingController();
  Timer? _debounce;

  @override
  void initState() {
    super.initState();
    _search.text = ref.read(offlineCatalogQueryProvider).text;
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _search.dispose();
    super.dispose();
  }

  void _apply(CatalogQuery query) {
    ref.read(offlineCatalogQueryProvider.notifier).state = query;
  }

  void _onSearchChanged(String value) {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 300), () {
      if (!mounted) return;
      _apply(ref.read(offlineCatalogQueryProvider).copyWith(text: value));
    });
  }

  @override
  Widget build(BuildContext context) {
    final query = ref.watch(offlineCatalogQueryProvider);
    final pageAsync = ref.watch(offlineCatalogProvider);
    final facetsAsync = ref.watch(offlineCatalogFacetsProvider);
    final theme = Theme.of(context);

    return Column(
      children: <Widget>[
        OfflineBanner(entryCount: pageAsync.valueOrNull?.totalAvailable),
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: TextField(
            controller: _search,
            textInputAction: TextInputAction.search,
            onChanged: _onSearchChanged,
            onSubmitted: (value) => _apply(query.copyWith(text: value)),
            decoration: InputDecoration(
              isDense: true,
              labelText: '在本机缓存资料中搜索',
              hintText: 'C 编号 / 型号 / 名称 / 品牌',
              prefixIcon: const Icon(Icons.search),
              suffixIcon: _search.text.isEmpty
                  ? null
                  : IconButton(
                      tooltip: '清空',
                      icon: const Icon(Icons.clear),
                      onPressed: () {
                        _search.clear();
                        _apply(const CatalogQuery());
                      },
                    ),
              border: const OutlineInputBorder(),
            ),
          ),
        ),
        facetsAsync.maybeWhen(
          data: (facets) => facets.isEmpty
              ? const SizedBox.shrink()
              : SizedBox(
                  height: 40,
                  child: ListView(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.symmetric(horizontal: 12),
                    children: <Widget>[
                      for (final option in facets.brands.take(12))
                        Padding(
                          padding: const EdgeInsets.only(right: 6),
                          child: FilterChip(
                            label: Text(option.display,
                                style: const TextStyle(fontSize: 11)),
                            selected: query.brands.contains(option.value),
                            onSelected: (selected) {
                              final brands = Set<String>.of(query.brands);
                              if (selected) {
                                brands.add(option.value);
                              } else {
                                brands.remove(option.value);
                              }
                              _apply(query.copyWith(brands: brands));
                            },
                          ),
                        ),
                      for (final option in facets.packages.take(12))
                        Padding(
                          padding: const EdgeInsets.only(right: 6),
                          child: FilterChip(
                            label: Text(option.display,
                                style: const TextStyle(fontSize: 11)),
                            selected: query.packages.contains(option.value),
                            onSelected: (selected) {
                              final packages = Set<String>.of(query.packages);
                              if (selected) {
                                packages.add(option.value);
                              } else {
                                packages.remove(option.value);
                              }
                              _apply(query.copyWith(packages: packages));
                            },
                          ),
                        ),
                    ],
                  ),
                ),
          orElse: () => const SizedBox.shrink(),
        ),
        Expanded(
          child: pageAsync.when(
            loading: () => const LoadingView(label: '正在读取本机缓存资料…'),
            error: (error, _) => ErrorView(
              message: '读取本机缓存失败：$error',
              onRetry: () => ref.invalidate(offlineCatalogEntriesProvider),
            ),
            data: (page) {
              if (page.totalAvailable == 0) {
                return const EmptyView(
                  title: '本机还没有缓存资料',
                  subtitle: '联网登录并浏览过器件后，本机会保存公开的器件资料'
                      '（图片、参数、手册），之后离线也能查看。',
                  icon: Icons.cloud_off_outlined,
                );
              }
              if (page.isEmpty) {
                return EmptyView(
                  title: '缓存里没有匹配的器件',
                  subtitle: '本机共缓存 ${page.totalAvailable} 条，可换个关键词。',
                  action: TextButton(
                    onPressed: () {
                      _search.clear();
                      _apply(const CatalogQuery());
                    },
                    child: const Text('清空搜索'),
                  ),
                );
              }
              return Column(
                children: <Widget>[
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
                    child: Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        '缓存命中 ${page.items.length} 条 / 本机共 ${page.totalAvailable} 条',
                        style: theme.textTheme.labelSmall,
                      ),
                    ),
                  ),
                  Expanded(
                    child: GridView.builder(
                      padding: const EdgeInsets.all(8),
                      gridDelegate:
                          const SliverGridDelegateWithMaxCrossAxisExtent(
                        maxCrossAxisExtent: 240,
                        mainAxisSpacing: 8,
                        crossAxisSpacing: 8,
                        mainAxisExtent: 236,
                      ),
                      itemCount: page.items.length,
                      itemBuilder: (context, index) {
                        final item = page.items[index];
                        return ItemCard(
                          item: item,
                          offline: true,
                          imageHeight: 72,
                          onTap: () => context.push(
                            UnifiedRoutes.offlineItemDetail(item.itemKey),
                          ),
                        );
                      },
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ],
    );
  }
}

/// Read-only offline detail: public parameters + manuals ONLY.
///
/// The stock section, local archives, bags and history are not merely hidden - they
/// are not part of the data this view reads.
class OfflineItemDetailView extends ConsumerWidget {
  const OfflineItemDetailView({super.key, required this.itemKey});

  final String itemKey;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(offlineCatalogDetailProvider(itemKey));
    final theme = Theme.of(context);

    return Column(
      children: <Widget>[
        const OfflineBanner(detail: true),
        Expanded(
          child: async.when(
            loading: () => const LoadingView(label: '正在读取本机缓存资料…'),
            error: (error, _) => ErrorView(
              message: '读取本机缓存失败：$error',
              onRetry: () => ref.invalidate(offlineCatalogDetailProvider(itemKey)),
            ),
            data: (detail) {
              final item = detail.item;
              if (item == null) {
                return const EmptyView(
                  title: '本机没有该器件的缓存资料',
                  subtitle: '联网登录并打开过该器件后，才能离线查看。',
                  icon: Icons.cloud_off_outlined,
                );
              }
              return ListView(
                padding: const EdgeInsets.all(12),
                children: <Widget>[
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          CachedMediaImage(
                            url: item.imageUrl,
                            alternateUrl: item.imageAlternateUrl,
                            width: 110,
                            height: 110,
                            decodeWidth: 320,
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: <Widget>[
                                Text(item.title, style: theme.textTheme.titleMedium),
                                if (item.subtitle.isNotEmpty)
                                  Text(item.subtitle,
                                      style: theme.textTheme.bodySmall),
                                const SizedBox(height: 6),
                                Wrap(
                                  spacing: 6,
                                  runSpacing: 4,
                                  children: <Widget>[
                                    if (item.catalogCode.isNotEmpty)
                                      Chip(
                                        label: Text(
                                          displayCatalogCode(item.catalogCode),
                                        ),
                                        visualDensity: VisualDensity.compact,
                                      ),
                                    const Chip(
                                      label: Text('离线缓存'),
                                      visualDensity: VisualDensity.compact,
                                    ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          Text('参数', style: theme.textTheme.titleSmall),
                          const SizedBox(height: 6),
                          if (item.parameters.isEmpty)
                            const Text('缓存中没有参数记录。')
                          else
                            for (final parameter in item.parameters)
                              Padding(
                                padding: const EdgeInsets.symmetric(vertical: 2),
                                child: Row(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: <Widget>[
                                    SizedBox(
                                      width: 110,
                                      child: Text(
                                        parameter.label,
                                        style: theme.textTheme.bodySmall?.copyWith(
                                          color: theme.colorScheme.onSurfaceVariant,
                                        ),
                                      ),
                                    ),
                                    Expanded(child: Text(parameter.value)),
                                  ],
                                ),
                              ),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          Text('手册 / 数据表', style: theme.textTheme.titleSmall),
                          const SizedBox(height: 6),
                          ManualList(files: detail.files),
                        ],
                      ),
                    ),
                  ),
                ],
              );
            },
          ),
        ),
      ],
    );
  }
}
