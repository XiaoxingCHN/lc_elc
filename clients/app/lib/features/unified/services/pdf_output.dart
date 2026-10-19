import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';
import 'package:printing/printing.dart';
import 'package:url_launcher/url_launcher.dart';

/// What happened to one exported PDF.
class PdfExportResult {
  const PdfExportResult({
    required this.ok,
    required this.message,
    this.path,
  });

  final bool ok;

  /// Operator-facing Chinese text - success or the reason it failed.
  final String message;

  /// Real file path when it was written to disk.
  final String? path;

  const PdfExportResult.failure(String message)
      : this(ok: false, message: message);
}

/// What the current platform can actually do with a generated PDF.
///
/// The UI reads this so it never shows an action that cannot work: on a desktop
/// without any printer service the print button is hidden rather than failing
/// when tapped.
class PdfCapabilities {
  const PdfCapabilities({
    required this.canPrint,
    required this.canShare,
    required this.hasPreview,
  });

  /// A system print dialog is available.
  final bool canPrint;

  /// A share sheet is available (mobile).
  final bool canShare;

  /// The in-app PDF preview widget is always available (pure Dart rendering).
  final bool hasPreview;

  static const PdfCapabilities offline = PdfCapabilities(
    canPrint: false,
    canShare: false,
    hasPreview: true,
  );

  factory PdfCapabilities.fromPrinting(PrintingInfo info) => PdfCapabilities(
        canPrint: info.canPrint,
        canShare: info.canShare,
        hasPreview: true,
      );
}

/// Real PDF output for the three platforms: save, system print, share.
///
/// The user's rule: a label PDF must support preview + save + system print on
/// Windows, Android and Linux. A button that only downloads a file without
/// being able to preview, open or print it is explicitly not acceptable, so
/// every action below performs a real operation and reports what actually
/// happened:
///
///   * [save] writes the bytes to the app documents directory (`实验室标签/`);
///   * [openSaved] hands the file to the operating system (desktop) or to the
///     system share sheet (mobile, where a `file://` intent is not permitted);
///   * [print] opens the REAL system print dialog through `printing`;
///   * [share] uses the platform share sheet.
///
/// Capability is queried through [capabilities]; the UI hides an action the
/// platform cannot perform instead of showing a button that fails when tapped.
/// Nothing here changes stock.
class PdfOutputService {
  PdfOutputService({Future<Directory> Function()? documentsDirectory})
      : _documentsDirectory = documentsDirectory ?? getApplicationDocumentsDirectory;

  final Future<Directory> Function() _documentsDirectory;

  Directory? _cachedDirectory;

  /// Where generated PDFs are written.
  Future<Directory> outputDirectory() async {
    final cached = _cachedDirectory;
    if (cached != null) return cached;
    final base = await _documentsDirectory();
    final dir = Directory('${base.path}/实验室标签');
    if (!dir.existsSync()) {
      await dir.create(recursive: true);
    }
    _cachedDirectory = dir;
    return dir;
  }

  /// Platform capabilities of the printing plugin (no dead buttons).
  Future<PdfCapabilities> capabilities() async {
    try {
      return PdfCapabilities.fromPrinting(await Printing.info());
    } catch (_) {
      return PdfCapabilities.offline;
    }
  }

  /// Writes [bytes] to a real file and returns its path.
  Future<PdfExportResult> save(Uint8List bytes, String filename) async {
    if (bytes.isEmpty) {
      return const PdfExportResult.failure('没有可保存的 PDF 内容（生成结果为空）。');
    }
    try {
      final dir = await outputDirectory();
      final file = File('${dir.path}/${sanitizeFileName(filename)}');
      await file.writeAsBytes(bytes, flush: true);
      return PdfExportResult(
        ok: true,
        message: '已保存到 ${file.path}',
        path: file.path,
      );
    } on FileSystemException catch (error) {
      return PdfExportResult.failure('保存失败：${error.message}');
    }
  }

  /// Opens a previously saved PDF with the operating system.
  ///
  /// On Android a `file://` URI cannot be handed to another app without a
  /// FileProvider, so the platform share sheet is used instead - the file is
  /// still real and the operator can open it from there.
  Future<PdfExportResult> openSaved(String path) async {
    final file = File(path);
    if (!file.existsSync()) {
      return const PdfExportResult.failure('文件不存在，可能已被移动或删除。');
    }

    if (!kIsWeb && (defaultTargetPlatform == TargetPlatform.android ||
        defaultTargetPlatform == TargetPlatform.iOS)) {
      try {
        final bytes = await file.readAsBytes();
        final shared = await Printing.sharePdf(
          bytes: bytes,
          filename: file.uri.pathSegments.last,
        );
        return PdfExportResult(
          ok: shared,
          message: shared ? '已打开系统分享/打开方式。' : '系统没有可用的打开方式。',
          path: path,
        );
      } catch (error) {
        return PdfExportResult.failure('打开失败：$error');
      }
    }

    try {
      final opened = await launchUrl(Uri.file(path));
      return PdfExportResult(
        ok: opened,
        message: opened ? '已用系统默认程序打开。' : '系统没有可打开 PDF 的程序。',
        path: path,
      );
    } catch (error) {
      return PdfExportResult.failure('打开失败：$error');
    }
  }

  /// Opens the REAL system print dialog.
  Future<PdfExportResult> print(Uint8List bytes, String filename) async {
    if (bytes.isEmpty) {
      return const PdfExportResult.failure('没有可打印的 PDF 内容（生成结果为空）。');
    }
    try {
      final done = await Printing.layoutPdf(
        name: sanitizeFileName(filename),
        onLayout: (format) async => bytes,
      );
      return PdfExportResult(
        ok: done,
        message: done ? '已提交系统打印。' : '打印已取消。',
      );
    } catch (error) {
      return PdfExportResult.failure('调起系统打印失败：$error');
    }
  }

  /// Platform share sheet (save to Files / Drive / mail from the phone).
  Future<PdfExportResult> share(Uint8List bytes, String filename) async {
    if (bytes.isEmpty) {
      return const PdfExportResult.failure('没有可分享的 PDF 内容（生成结果为空）。');
    }
    try {
      final shared = await Printing.sharePdf(
        bytes: bytes,
        filename: sanitizeFileName(filename),
      );
      return PdfExportResult(
        ok: shared,
        message: shared ? '已打开系统分享。' : '已取消分享。',
      );
    } catch (error) {
      return PdfExportResult.failure('分享失败：$error');
    }
  }

  /// Removes characters a Windows/Linux filesystem would refuse.
  static String sanitizeFileName(String name) {
    final trimmed = name.trim().isEmpty ? 'labels.pdf' : name.trim();
    final safe = trimmed.replaceAll(RegExp(r'[\\/:*?"<>|\x00-\x1f]'), '_');
    if (safe.toLowerCase().endsWith('.pdf')) return safe;
    return '$safe.pdf';
  }
}
