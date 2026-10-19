import 'package:flutter/material.dart';

import '../models/identity.dart';
import '../models/unified_item.dart';
import 'media_view.dart';

/// One card = one canonical identity.
///
/// The badge row makes the two quantities impossible to confuse:
///   * `内部库存` is the laboratory's own stock, aggregated over every permitted
///     local archive bound to this card, and is what the server's ordering uses;
///   * `立创商城现货` is MALL stock, marked as reference only.
///
/// Layout rules (pinned by `test/features/unified/ui_layout_test.dart`): the body
/// is scrollable inside the fixed grid cell and the action buttons wrap, so a
/// 320 px phone with six-digit quantities and long Chinese names cannot produce a
/// RenderFlex overflow.
class ItemCard extends StatelessWidget {
  const ItemCard({
    super.key,
    required this.item,
    required this.onTap,
    this.onReceipt,
    this.onIssue,
    this.imageHeight = 96,
    this.offline = false,
  });

  final UnifiedItem item;
  final VoidCallback onTap;
  final VoidCallback? onReceipt;
  final VoidCallback? onIssue;
  final double imageHeight;

  /// True in the public offline browser: no stock figures are shown at all (the
  /// cache cannot contain them, and "0" would be a lie), and no stock action is
  /// offered.
  final bool offline;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hasStock = item.hasStock;

    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            SizedBox(
              height: imageHeight,
              child: CachedMediaImage(
                url: item.imageUrl,
                alternateUrl: item.imageAlternateUrl,
                height: imageHeight,
                fit: BoxFit.contain,
                // A small thumbnail cannot hold the explanatory placeholder
                // text; the icon alone is the honest signal there.
                compactPlaceholder: imageHeight < 96,
              ),
            ),
            Expanded(
              child: SingleChildScrollView(
                padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      item.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodyMedium
                          ?.copyWith(fontWeight: FontWeight.w600),
                    ),
                    if (item.subtitle.isNotEmpty) ...<Widget>[
                      const SizedBox(height: 2),
                      Text(
                        item.subtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.labelSmall
                            ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      ),
                    ],
                    const SizedBox(height: 6),
                    Wrap(
                      spacing: 4,
                      runSpacing: 4,
                      children: <Widget>[
                        if (item.catalogCode.isNotEmpty)
                          _Tag(
                            text: displayCatalogCode(item.catalogCode),
                            tone: _TagTone.catalog,
                          ),
                        if (item.isLocalCard)
                          const _Tag(text: '本地物料', tone: _TagTone.local),
                        if (item.labTemplateIds.length > 1)
                          _Tag(
                            text: '本地档案 ${item.labTemplateIds.length}',
                            tone: _TagTone.local,
                          ),
                        if (item.snCodes.isNotEmpty)
                          _Tag(text: 'SN ${item.snCodes.length}', tone: _TagTone.local),
                      ],
                    ),
                    const SizedBox(height: 6),
                    if (offline)
                      Text(
                        '离线缓存资料 · 不含库存数量',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.labelSmall
                            ?.copyWith(color: theme.colorScheme.outline),
                      )
                    else ...<Widget>[
                      Row(
                        children: <Widget>[
                          Icon(
                            hasStock ? Icons.inventory_2 : Icons.inventory_2_outlined,
                            size: 14,
                            color: hasStock
                                ? theme.colorScheme.primary
                                : theme.colorScheme.outline,
                          ),
                          const SizedBox(width: 4),
                          Expanded(
                            child: Text(
                              hasStock ? '内部库存 ${item.labQuantityLabel}' : '内部无库存',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: theme.textTheme.labelMedium?.copyWith(
                                color: hasStock
                                    ? theme.colorScheme.primary
                                    : theme.colorScheme.outline,
                                fontWeight:
                                    hasStock ? FontWeight.w700 : FontWeight.w400,
                              ),
                            ),
                          ),
                        ],
                      ),
                      Text(
                        item.catalogStockLabel,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.labelSmall
                            ?.copyWith(color: theme.colorScheme.outline),
                      ),
                    ],
                    if (!offline && (onReceipt != null || onIssue != null)) ...<Widget>[
                      const SizedBox(height: 2),
                      Wrap(
                        spacing: 2,
                        children: <Widget>[
                          if (onReceipt != null)
                            TextButton.icon(
                              onPressed: onReceipt,
                              icon: const Icon(Icons.add_box_outlined, size: 16),
                              label: const Text('入库'),
                              style: TextButton.styleFrom(
                                padding: const EdgeInsets.symmetric(horizontal: 6),
                                minimumSize: const Size(0, 28),
                                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                              ),
                            ),
                          if (onIssue != null)
                            TextButton.icon(
                              onPressed: onIssue,
                              icon: const Icon(Icons.outbox_outlined, size: 16),
                              label: const Text('领料'),
                              style: TextButton.styleFrom(
                                padding: const EdgeInsets.symmetric(horizontal: 6),
                                minimumSize: const Size(0, 28),
                                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                              ),
                            ),
                        ],
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Compact list variant (used when the operator switches to list mode).
class ItemListTile extends StatelessWidget {
  const ItemListTile({
    super.key,
    required this.item,
    required this.onTap,
    this.onReceipt,
    this.onIssue,
  });

  final UnifiedItem item;
  final VoidCallback onTap;
  final VoidCallback? onReceipt;
  final VoidCallback? onIssue;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(8),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              CachedMediaImage(
                url: item.imageUrl,
                alternateUrl: item.imageAlternateUrl,
                width: 56,
                height: 56,
                decodeWidth: 112,
                compactPlaceholder: true,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text(
                      item.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodyMedium
                          ?.copyWith(fontWeight: FontWeight.w600),
                    ),
                    if (item.subtitle.isNotEmpty)
                      Text(
                        item.subtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: theme.textTheme.labelSmall
                            ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                      ),
                    const SizedBox(height: 4),
                    // One ellipsized line instead of a Wrap: a single long CJK
                    // brand inside a Wrap would overflow a 320 px screen.
                    Text(
                      <String>[
                        if (item.catalogCode.isNotEmpty)
                          displayCatalogCode(item.catalogCode),
                        item.hasStock ? '内部 ${item.labQuantityLabel}' : '内部无库存',
                        item.catalogStockLabel,
                      ].join(' · '),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.labelMedium?.copyWith(
                        color: item.hasStock
                            ? theme.colorScheme.primary
                            : theme.colorScheme.outline,
                      ),
                    ),
                  ],
                ),
              ),
              if (onReceipt != null)
                IconButton(
                  tooltip: '入库',
                  onPressed: onReceipt,
                  icon: const Icon(Icons.add_box_outlined),
                ),
              if (onIssue != null)
                IconButton(
                  tooltip: '领料',
                  onPressed: onIssue,
                  icon: const Icon(Icons.outbox_outlined),
                ),
              const Icon(Icons.chevron_right),
            ],
          ),
        ),
      ),
    );
  }
}

enum _TagTone { catalog, local }

class _Tag extends StatelessWidget {
  const _Tag({required this.text, required this.tone});

  final String text;
  final _TagTone tone;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = tone == _TagTone.catalog
        ? theme.colorScheme.tertiary
        : theme.colorScheme.secondary;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(4),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(
        text,
        style: theme.textTheme.labelSmall?.copyWith(color: color, fontSize: 10),
      ),
    );
  }
}
