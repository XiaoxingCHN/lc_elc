import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../providers/unified_providers.dart';
import '../screens/camera_scan_screen.dart';
import '../services/scan_sources.dart';

/// The ONE code entry point used by every stock flow.
///
/// It covers all three input devices with identical business behaviour:
///
///   * a hardware scanner gun (keyboard wedge - the Enter it sends submits);
///   * manual typing;
///   * clipboard paste (the code from the Odoo web UI, a supplier mail, ...);
///   * on Android only, the camera button - the Windows/Linux build has no
///     camera implementation, so no camera control is rendered there at all.
///
/// The raw payload is passed to the caller unchanged: only
/// `/lab/api/inventory/resolve_code` decides what a code means. A submitted code
/// NEVER writes stock by itself - the flow always shows what was recognised and
/// waits for an explicit confirmation.
class ScanInputField extends ConsumerStatefulWidget {
  const ScanInputField({
    super.key,
    required this.onSubmit,
    this.controller,
    this.label = '扫描 / 输入编码',
    this.hintText,
    this.autofocus = true,
    this.enabled = true,
    this.helperText,
  });

  final ValueChanged<String> onSubmit;
  final TextEditingController? controller;
  final String label;
  final String? hintText;
  final bool autofocus;
  final bool enabled;
  final String? helperText;

  @override
  ConsumerState<ScanInputField> createState() => _ScanInputFieldState();
}

class _ScanInputFieldState extends ConsumerState<ScanInputField> {
  late final TextEditingController _controller =
      widget.controller ?? TextEditingController();
  final FocusNode _focusNode = FocusNode();
  String? _clipboardNotice;

  @override
  void dispose() {
    if (widget.controller == null) _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  void _submit(String raw) {
    final code = normalizeScanInput(raw);
    if (code.isEmpty) return;
    _controller.text = code;
    _controller.selection = TextSelection.collapsed(offset: code.length);
    _focusNode.requestFocus();
    widget.onSubmit(code);
  }

  Future<void> _pasteAndSubmit() async {
    try {
      final code = await readClipboardCode();
      if (!mounted) return;
      if (code == null) {
        setState(() => _clipboardNotice = '剪贴板里没有可用文本。');
        return;
      }
      setState(() => _clipboardNotice = null);
      _submit(code);
    } catch (error) {
      if (!mounted) return;
      setState(() => _clipboardNotice = '读取剪贴板失败：$error');
    }
  }

  Future<void> _openCamera() async {
    final code = await Navigator.of(context).push<String>(
      MaterialPageRoute<String>(builder: (context) => const CameraScanScreen()),
    );
    if (!mounted || code == null) return;
    _submit(code);
  }

  @override
  Widget build(BuildContext context) {
    final capabilities = ref.watch(scannerCapabilitiesProvider);
    final theme = Theme.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: <Widget>[
        TextField(
          controller: _controller,
          focusNode: _focusNode,
          autofocus: widget.autofocus,
          enabled: widget.enabled,
          textInputAction: TextInputAction.done,
          onSubmitted: _submit,
          onChanged: (_) => setState(() {}),
          decoration: InputDecoration(
            labelText: widget.label,
            hintText: widget.hintText ?? '例如 LABB:TRACE000001 / LABL:K000001 / C123456',
            prefixIcon: const Icon(Icons.qr_code_scanner),
            border: const OutlineInputBorder(),
            suffixIcon: Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                if (_controller.text.isNotEmpty)
                  IconButton(
                    tooltip: '清空',
                    icon: const Icon(Icons.clear),
                    onPressed: () {
                      _controller.clear();
                      setState(() {});
                    },
                  ),
                IconButton(
                  tooltip: '粘贴编码',
                  icon: const Icon(Icons.content_paste),
                  onPressed: widget.enabled ? _pasteAndSubmit : null,
                ),
                // Only rendered where a camera exists.
                if (capabilities.camera)
                  IconButton(
                    tooltip: '用摄像头扫码',
                    icon: const Icon(Icons.photo_camera_outlined),
                    onPressed: widget.enabled ? _openCamera : null,
                  ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 4),
        Text(
          widget.helperText ?? capabilities.hint,
          style: theme.textTheme.labelSmall
              ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
        ),
        if (_clipboardNotice != null) ...<Widget>[
          const SizedBox(height: 4),
          Text(
            _clipboardNotice!,
            style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.error),
          ),
        ],
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerLeft,
          child: FilledButton.tonalIcon(
            onPressed: widget.enabled ? () => _submit(_controller.text) : null,
            icon: const Icon(Icons.play_arrow),
            label: const Text('识别编码'),
          ),
        ),
      ],
    );
  }
}
