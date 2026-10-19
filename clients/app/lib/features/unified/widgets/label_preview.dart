import 'package:lab_inventory_client/widgets/lab_ui.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:printing/printing.dart';

import '../models/labels.dart';
import '../providers/unified_providers.dart';
import '../services/pdf_output.dart';

/// Preview + real output actions for a generated label PDF.
///
/// Every button performs a real operation on the three platforms:
///   预览  - the in-app PDF renderer below (no plugin-specific viewer needed);
///   保存  - writes the file to the app documents directory, then opens it with
///           the system handler (desktop) or the share sheet (mobile);
///   打印  - opens the REAL system print dialog (hidden where the platform has
///           no printing support, instead of a button that fails);
///   分享  - platform share sheet (mobile).
///
/// Nothing in this dialog writes stock: printing or reprinting a label only
/// re-reads the same preview endpoint.
class LabelPdfDialog extends ConsumerStatefulWidget {
  const LabelPdfDialog({super.key, required this.pdf});

  final LabelPdfResult pdf;

  @override
  ConsumerState<LabelPdfDialog> createState() => _LabelPdfDialogState();
}

class _LabelPdfDialogState extends ConsumerState<LabelPdfDialog> {
  bool _busy = false;

  Future<void> _run(
    Future<PdfExportResult> Function() action, {
    bool openAfterSave = false,
  }) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      final result = await action();
      if (!mounted) return;
      if (openAfterSave && result.ok && result.path != null) {
        final opened = await ref.read(pdfOutputProvider).openSaved(result.path!);
        if (!mounted) return;
        _tell(opened.ok ? '${result.message}\n${opened.message}' : result.message);
        return;
      }
      _tell(result.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _tell(String message) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final service = ref.watch(pdfOutputProvider);
    final theme = Theme.of(context);

    return Dialog.fullscreen(
      child: Scaffold(
        appBar: LabAppBar(
          title: Text(widget.pdf.filename),
          actions: <Widget>[
            IconButton(
              tooltip: '关闭',
              onPressed: () => Navigator.of(context).pop(),
              icon: const Icon(Icons.close),
            ),
          ],
        ),
        body: Column(
          children: <Widget>[
            Container(
              width: double.infinity,
              color: theme.colorScheme.surfaceContainerHighest,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              child: Text(
                '${widget.pdf.summary} · 重新打印不会改变库存',
                style: theme.textTheme.labelSmall,
              ),
            ),
            Expanded(
              child: FutureBuilder<PdfCapabilities>(
                future: service.capabilities(),
                builder: (context, snapshot) {
                  final capabilities = snapshot.data;
                  return Column(
                    children: <Widget>[
                      Expanded(
                        child: PdfPreview(
                          build: (format) async => widget.pdf.bytes,
                          pdfFileName: widget.pdf.filename,
                          canChangePageFormat: false,
                          canChangeOrientation: false,
                          allowPrinting: false,
                          allowSharing: false,
                        ),
                      ),
                      SafeArea(
                        top: false,
                        child: Padding(
                          padding: const EdgeInsets.all(8),
                          child: Wrap(
                            alignment: WrapAlignment.center,
                            spacing: 8,
                            runSpacing: 8,
                            children: <Widget>[
                              FilledButton.tonalIcon(
                                onPressed: _busy
                                    ? null
                                    : () => _run(() => service.save(
                                          widget.pdf.bytes,
                                          widget.pdf.filename,
                                        )),
                                icon: const Icon(Icons.save_alt),
                                label: const Text('保存 PDF'),
                              ),
                              FilledButton.tonalIcon(
                                onPressed: _busy
                                    ? null
                                    : () => _run(
                                          () => service.save(
                                            widget.pdf.bytes,
                                            widget.pdf.filename,
                                          ),
                                          openAfterSave: true,
                                        ),
                                icon: const Icon(Icons.open_in_new),
                                label: const Text('保存并打开'),
                              ),
                              if (capabilities == null || capabilities.canPrint)
                                FilledButton.icon(
                                  onPressed: _busy
                                      ? null
                                      : () => _run(() => service.print(
                                            widget.pdf.bytes,
                                            widget.pdf.filename,
                                          )),
                                  icon: const Icon(Icons.print),
                                  label: const Text('系统打印'),
                                ),
                              if (capabilities != null && capabilities.canShare)
                                OutlinedButton.icon(
                                  onPressed: _busy
                                      ? null
                                      : () => _run(() => service.share(
                                            widget.pdf.bytes,
                                            widget.pdf.filename,
                                          )),
                                  icon: const Icon(Icons.share),
                                  label: const Text('分享'),
                                ),
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
        ),
      ),
    );
  }
}

/// Small A4 layout preview: shows how many labels fit per page.
///
/// This is a diagram of the CONFIGURED millimetres, not a fake render of the
/// server PDF - the real PDF is only ever shown from the server bytes.
class LabelLayoutPreview extends StatelessWidget {
  const LabelLayoutPreview({super.key, required this.layout, this.height = 180});

  final LabelLayout layout;
  final double height;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Container(
      height: height,
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      padding: EdgeInsets.all(layout.usableWidthMm <= 0 ? 4 : 4),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: <Widget>[
          for (var row = 0; row < layout.rows.clamp(0, 12); row++)
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: <Widget>[
                for (var column = 0; column < layout.columns.clamp(0, 8); column++)
                  Container(
                    width: 26,
                    height: 16,
                    margin: const EdgeInsets.all(1),
                    decoration: BoxDecoration(
                      border: Border.all(color: theme.colorScheme.primary),
                      color: theme.colorScheme.primary.withValues(alpha: 0.08),
                    ),
                  ),
              ],
            ),
          const SizedBox(height: 4),
          Text(
            layout.isValid
                ? '${layout.columns}×${layout.rows} / 页'
                : '布局不可用',
            style: theme.textTheme.labelSmall,
          ),
        ],
      ),
    );
  }
}
