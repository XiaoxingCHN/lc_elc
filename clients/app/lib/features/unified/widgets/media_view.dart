import 'package:lab_inventory_client/widgets/lab_ui.dart';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:printing/printing.dart';

import '../../../models/lab_api_exception.dart';
import '../models/detail_models.dart';
import '../providers/offline_providers.dart';
import '../services/asset_cache.dart';
import 'status_views.dart';

/// Why a media slot shows a placeholder instead of a picture.
enum MediaPlaceholderReason {
  /// The captured data has no image for this component.
  noSource,

  /// There is a URL but it could not be fetched and nothing is cached.
  loadFailed,
}

/// The explicit "no real photo" placeholder.
///
/// The user's rule: only some captured rows carry a real image, so an absent
/// image must be shown as a clearly-labelled placeholder - a generated or
/// decorative "component photo" would be a fake. This widget never draws a
/// component; it states the situation and its source.
class MediaPlaceholder extends StatelessWidget {
  const MediaPlaceholder({
    super.key,
    this.reason = MediaPlaceholderReason.noSource,
    this.width,
    this.height,
    this.title,
    this.onRetry,
    this.compact = false,
  });

  final MediaPlaceholderReason reason;
  final double? width;
  final double? height;
  final String? title;
  final VoidCallback? onRetry;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isMissingSource = reason == MediaPlaceholderReason.noSource;

    final content = Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: <Widget>[
        Icon(
          isMissingSource ? Icons.image_not_supported_outlined : Icons.cloud_off_outlined,
          size: compact ? 22 : 30,
          color: theme.colorScheme.outline,
        ),
        if (!compact) ...<Widget>[
          const SizedBox(height: 6),
          Text(
            title ?? (isMissingSource ? '暂无真实图片' : '图片暂不可用'),
            textAlign: TextAlign.center,
            style: theme.textTheme.labelSmall,
          ),
          const SizedBox(height: 2),
          Text(
            isMissingSource ? '来源：已采集资料未提供图片' : '本机无缓存且网络不可用',
            textAlign: TextAlign.center,
            style: theme.textTheme.labelSmall
                ?.copyWith(color: theme.colorScheme.outline, fontSize: 9),
          ),
          if (!isMissingSource && onRetry != null) ...<Widget>[
            const SizedBox(height: 2),
            InkWell(
              onTap: onRetry,
              child: Text(
                '重试',
                style: theme.textTheme.labelSmall
                    ?.copyWith(color: theme.colorScheme.primary),
              ),
            ),
          ],
        ],
      ],
    );

    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        color: theme.colorScheme.surfaceContainerHighest.withValues(alpha: 0.5),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      padding: const EdgeInsets.all(4),
      child: content,
    );
  }
}

/// An image loaded through the FILE cache, so a viewed item stays visible
/// offline.
///
/// Behaviour:
///   * no real URL -> [MediaPlaceholderReason.noSource] placeholder;
///   * cached on disk -> decoded straight from those bytes, no request;
///   * not cached -> fetched, written to disk, then decoded;
///   * fetch failed -> [MediaPlaceholderReason.loadFailed] with a retry.
class CachedMediaImage extends ConsumerStatefulWidget {
  const CachedMediaImage({
    super.key,
    required this.url,
    this.alternateUrl,
    this.width,
    this.height,
    this.fit = BoxFit.contain,
    this.kind = MediaKind.image,
    this.decodeWidth,
    this.compactPlaceholder = false,
  });

  final String? url;

  /// Fallback reference (e.g. the public original URL when the primary one is a
  /// same-origin authenticated link).
  final String? alternateUrl;

  final double? width;
  final double? height;
  final BoxFit fit;
  final MediaKind kind;

  /// Decode hint for list thumbnails (keeps memory low).
  final int? decodeWidth;

  /// Only the icon is shown (for small thumbnails).
  final bool compactPlaceholder;

  @override
  ConsumerState<CachedMediaImage> createState() => _CachedMediaImageState();
}

class _CachedMediaImageState extends ConsumerState<CachedMediaImage> {
  Future<Uint8List>? _pending;

  @override
  void initState() {
    super.initState();
    _start();
  }

  @override
  void didUpdateWidget(CachedMediaImage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.url != widget.url || oldWidget.alternateUrl != widget.alternateUrl) {
      _start();
    }
  }

  void _start() {
    final references = <String>[
      if (widget.url != null && widget.url!.isNotEmpty) widget.url!,
      if (widget.alternateUrl != null && widget.alternateUrl!.isNotEmpty)
        widget.alternateUrl!,
    ];
    if (references.isEmpty) {
      _pending = null;
      return;
    }
    _pending = ref
        .read(effectiveAssetCacheProvider)
        .readPreferred(references, kind: widget.kind);
  }

  void _retry() {
    setState(_start);
  }

  @override
  Widget build(BuildContext context) {
    final hasReference = (widget.url != null && widget.url!.isNotEmpty) ||
        (widget.alternateUrl != null && widget.alternateUrl!.isNotEmpty);
    if (!hasReference) {
      return MediaPlaceholder(
        width: widget.width,
        height: widget.height,
        compact: widget.compactPlaceholder,
      );
    }

    return FutureBuilder<Uint8List>(
      future: _pending,
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return SizedBox(
            width: widget.width,
            height: widget.height,
            child: const Center(
              child: SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
            ),
          );
        }
        if (snapshot.hasError || !snapshot.hasData || snapshot.data!.isEmpty) {
          return MediaPlaceholder(
            reason: MediaPlaceholderReason.loadFailed,
            width: widget.width,
            height: widget.height,
            onRetry: _retry,
            compact: widget.compactPlaceholder,
          );
        }
        return Image.memory(
          snapshot.data!,
          width: widget.width,
          height: widget.height,
          fit: widget.fit,
          gaplessPlayback: true,
          cacheWidth: widget.decodeWidth,
          errorBuilder: (context, error, stackTrace) => MediaPlaceholder(
            reason: MediaPlaceholderReason.loadFailed,
            width: widget.width,
            height: widget.height,
            onRetry: _retry,
            compact: widget.compactPlaceholder,
          ),
        );
      },
    );
  }
}

/// Datasheet / manual list with a real preview (offline from cache).
class ManualList extends ConsumerWidget {
  const ManualList({super.key, required this.files, this.dense = false});

  final List<LabFile> files;
  final bool dense;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (files.isEmpty) {
      return Text(
        '已采集资料中没有手册/数据表文件。',
        style: Theme.of(context).textTheme.bodySmall,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        for (final file in files)
          ListTile(
            dense: dense,
            contentPadding: EdgeInsets.zero,
            leading: Icon(
              file.isPdf ? Icons.picture_as_pdf_outlined : Icons.insert_drive_file_outlined,
            ),
            title: Text(file.displayName, maxLines: 2, overflow: TextOverflow.ellipsis),
            subtitle: Text(
              file.isPdf ? 'PDF 手册 · 查看后缓存，可离线打开' : '${file.type.isEmpty ? '资料文件' : file.type} · 查看后缓存',
              style: Theme.of(context).textTheme.labelSmall,
            ),
            trailing: const Icon(Icons.chevron_right),
            onTap: () => showDialog<void>(
              context: context,
              builder: (context) => ManualViewerDialog(file: file),
            ),
          ),
      ],
    );
  }
}

/// Full-screen preview of one manual.
///
/// The bytes come from the file cache: on the first open they are downloaded and
/// written to disk, afterwards the same dialog works with no network at all.
class ManualViewerDialog extends ConsumerStatefulWidget {
  const ManualViewerDialog({super.key, required this.file});

  final LabFile file;

  @override
  ConsumerState<ManualViewerDialog> createState() => _ManualViewerDialogState();
}

class _ManualViewerDialogState extends ConsumerState<ManualViewerDialog> {
  Future<Uint8List>? _pending;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    setState(() {
      _pending = ref
          .read(effectiveAssetCacheProvider)
          .read(widget.file.url, kind: MediaKind.manual);
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Dialog.fullscreen(
      child: Scaffold(
        appBar: LabAppBar(
          title: Text(widget.file.displayName, maxLines: 1, overflow: TextOverflow.ellipsis),
          actions: <Widget>[
            IconButton(
              tooltip: '重新加载',
              onPressed: _load,
              icon: const Icon(Icons.refresh),
            ),
            IconButton(
              tooltip: '关闭',
              onPressed: () => Navigator.of(context).pop(),
              icon: const Icon(Icons.close),
            ),
          ],
        ),
        body: FutureBuilder<Uint8List>(
          future: _pending,
          builder: (context, snapshot) {
            if (snapshot.connectionState == ConnectionState.waiting) {
              return const LoadingView(label: '正在读取手册…');
            }
            if (snapshot.hasError || !snapshot.hasData || snapshot.data!.isEmpty) {
              final error = snapshot.error;
              final message = error is LabApiException
                  ? error.message
                  : error is AssetCacheException
                      ? error.message
                      : '手册读取失败。';
              return ErrorView(
                message: '$message\n（首次查看需要联网，之后本机会缓存该文件，可离线打开。）',
                onRetry: _load,
              );
            }

            final bytes = snapshot.data!;
            if (!widget.file.isPdf) {
              return Center(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: <Widget>[
                      const Icon(Icons.insert_drive_file_outlined, size: 48),
                      const SizedBox(height: 12),
                      Text('该文件不是 PDF，已缓存到本机（${(bytes.length / 1024).toStringAsFixed(1)} KB）。',
                          textAlign: TextAlign.center),
                      const SizedBox(height: 8),
                      Text(
                        '可通过“保存”按钮导出后在系统中打开。',
                        style: theme.textTheme.bodySmall,
                      ),
                    ],
                  ),
                ),
              );
            }

            return PdfPreview(
              build: (format) async => bytes,
              pdfFileName: widget.file.displayName,
              canChangePageFormat: false,
              canChangeOrientation: false,
              allowPrinting: true,
              allowSharing: true,
            );
          },
        ),
      ),
    );
  }
}
