import 'package:lab_inventory_client/widgets/lab_ui.dart';
import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

/// Phone camera scanner. Returns the raw scanned string via `Navigator.pop`.
///
/// This screen exists ONLY where `mobile_scanner` is implemented (Android/iOS)
/// and the UI only offers it there - Windows and Linux use the identical
/// business flow through a scanner gun or the clipboard, so no button on those
/// platforms can ever end in "not supported".
///
/// Cancelling (back, or the "手动输入" button) returns `null`, which means the
/// caller keeps its current input and writes nothing.
class CameraScanScreen extends StatefulWidget {
  const CameraScanScreen({super.key, this.title = '摄像头扫码'});

  final String title;

  @override
  State<CameraScanScreen> createState() => _CameraScanScreenState();
}

class _CameraScanScreenState extends State<CameraScanScreen> {
  final MobileScannerController _controller = MobileScannerController(
    // The label/bag codes this business uses are QR; the linear formats are
    // accepted so nothing on a supplier bag is silently ignored.
    formats: const <BarcodeFormat>[
      BarcodeFormat.qrCode,
      BarcodeFormat.code128,
      BarcodeFormat.code39,
      BarcodeFormat.dataMatrix,
    ],
    detectionSpeed: DetectionSpeed.noDuplicates,
  );

  bool _handled = false;
  String? _errorText;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _onDetect(BarcodeCapture capture) {
    if (_handled) return;
    for (final barcode in capture.barcodes) {
      final value = barcode.rawValue?.trim();
      if (value == null || value.isEmpty) continue;
      _handled = true;
      Navigator.of(context).pop(value);
      return;
    }
  }

  Future<void> _restart() async {
    setState(() {
      _handled = false;
      _errorText = null;
    });
    try {
      await _controller.start();
    } catch (error) {
      if (!mounted) return;
      setState(() => _errorText = _describe(error));
    }
  }

  String _describe(Object error) {
    if (error is MobileScannerException) {
      switch (error.errorCode) {
        case MobileScannerErrorCode.permissionDenied:
          return '没有摄像头权限。请在系统设置里允许本应用使用摄像头，然后点“重试”。';
        case MobileScannerErrorCode.unsupported:
          return '该设备的摄像头不支持扫码，请改用手动输入或扫码枪。';
        default:
          return '摄像头启动失败：${error.errorCode.message}。可点“重试”，或改用手动输入。';
      }
    }
    return '摄像头启动失败：$error。可改用手动输入。';
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      appBar: LabAppBar(fallbackLocation: '/catalog',title: Text(widget.title)),
      body: Column(
        children: <Widget>[
          Expanded(
            child: Stack(
              fit: StackFit.expand,
              children: <Widget>[
                MobileScanner(
                  controller: _controller,
                  onDetect: _onDetect,
                  onDetectError: (error, stackTrace) {
                    if (!mounted) return;
                    setState(() => _errorText = _describe(error));
                  },
                  errorBuilder: (context, error) => Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: <Widget>[
                          Icon(Icons.no_photography_outlined,
                              size: 48, color: theme.colorScheme.error),
                          const SizedBox(height: 12),
                          Text(_describe(error), textAlign: TextAlign.center),
                          const SizedBox(height: 12),
                          FilledButton.tonal(
                            onPressed: _restart,
                            child: const Text('重试'),
                          ),
                        ],
                      ),
                    ),
                  ),
                  placeholderBuilder: (context) => const Center(
                    child: CircularProgressIndicator(),
                  ),
                ),
                // Scan frame.
                IgnorePointer(
                  child: Center(
                    child: Container(
                      width: 240,
                      height: 240,
                      decoration: BoxDecoration(
                        border: Border.all(color: Colors.white70, width: 3),
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                  ),
                ),
                Align(
                  alignment: Alignment.bottomCenter,
                  child: Container(
                    width: double.infinity,
                    color: Colors.black54,
                    padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
                    child: Text(
                      '把二维码放进框内。单位：追溯袋码、库位码、立创来料码。',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: Colors.white),
                    ),
                  ),
                ),
              ],
            ),
          ),
          if (_errorText != null)
            Container(
              width: double.infinity,
              color: theme.colorScheme.errorContainer,
              padding: const EdgeInsets.all(12),
              child: Text(_errorText!, style: theme.textTheme.bodySmall),
            ),
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              child: Row(
                children: <Widget>[
                  IconButton(
                    tooltip: '手电筒',
                    onPressed: () async {
                      try {
                        await _controller.toggleTorch();
                      } catch (_) {
                        // A device without a torch is not an error worth a dialog.
                      }
                    },
                    icon: const Icon(Icons.flashlight_on_outlined),
                  ),
                  IconButton(
                    tooltip: '切换摄像头',
                    onPressed: () async {
                      try {
                        await _controller.switchCamera();
                      } catch (_) {
                        // Single-camera devices simply ignore this.
                      }
                    },
                    icon: const Icon(Icons.cameraswitch_outlined),
                  ),
                  const Spacer(),
                  TextButton.icon(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.keyboard_alt_outlined),
                    label: const Text('手动输入'),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
