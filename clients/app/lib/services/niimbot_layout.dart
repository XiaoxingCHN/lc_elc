import 'dart:math' as math;

import '../features/unified/models/labels.dart';

/// Millimetres per typographic point (1 pt = 25.4 / 72 mm).
const double mmPerPoint = 25.4 / 72.0;

/// Smallest body text the design allows: 5.5 pt, the same floor the server's
/// A4 renderer uses (`MIN_BODY_FONT_PT` in `label_render.py`).
const double kThermalMinBodyFontMm = 5.5 * mmPerPoint;

/// Largest body text the thermal label uses (≈7.4 pt). Bigger than this and a
/// 3-line label no longer fits a 20 mm tall stock.
const double kThermalMaxBodyFontMm = 2.6;

/// Smallest title size. On a 40 × 20 mm label with three body lines the title
/// would otherwise shrink with the body to an unreadable ~5 pt; this floor
/// keeps the identifying line legible and lets the plan report truncation
/// instead of hiding the cost.
const double kThermalMinTitleFontMm = 2.2;

/// Title is slightly larger than the body, capped so it stays one line.
const double kThermalTitleScale = 1.18;
const double kThermalMaxTitleFontMm = 3.4;

/// Line box height as a multiple of the glyph size.
const double kThermalLineHeightFactor = 1.28;

/// The user's current stock is 40 × 20 mm.
///
/// The QR target is 11 mm rather than 13 mm: the text column is what the
/// operator reads, and 11 mm still leaves ~0.44 mm per module for an 18-character
/// `LABB:` payload (QR version 2 = 25 modules), which both phones and handheld
/// scanners resolve comfortably. Dropping to 11 mm buys 2 mm of text width and
/// is what lets all four content lines fit without an ellipsis.
const double kThermalDefaultWidthMm = 40.0;
const double kThermalDefaultHeightMm = 20.0;
const double kThermalQrTargetMm = 11.0;
/// The QR sits flush in the top-left corner: the operator sticks these labels
/// on bags by hand, and a corner-anchored code is easier to line up and to scan
/// without hunting. 1.0 mm is the smallest quiet zone that still prints cleanly
/// on this stock (the SDK draws the QR's own 4-module quiet zone inside the box).
const double kThermalQrLeftMarginMm = 1.0;
const double kThermalQrTextGapMm = 1.5;
const double kThermalTextRightMarginMm = 2.0;
const double kThermalVerticalMarginMm = 1.0;

/// At most four body lines on a 20 mm tall label.
///
/// The server sends labels with a Chinese field prefix ("名称：…"), which costs
/// roughly 5.8 mm of the 22 mm text column. Stripping the prefix (see
/// [stripLabelPrefix]) frees that space, so a 40 × 20 stock can carry the
/// identifier plus four content lines instead of three.
const int kThermalMaxBodyLines = 4;

/// The 库码 printed UNDER a location label's QR.
///
/// 6 pt: the QR column is only 11 mm wide, so this is the largest size at which
/// a `K000003`-style code still fits on one line under the code.
const double kThermalCaptionFontMm = 6.0 * mmPerPoint;

/// Largest font a location label's NAME may use (≈17 pt).
///
/// Much larger than [kThermalMaxTitleFontMm] because the two labels are read
/// from different distances: a bag label is picked up and read at arm's length,
/// a shelf label is read while walking past it. A shelf name is also short (one
/// or two words), so it can afford the size; the fit loop still shrinks it if
/// the name is long or the stock is short.
const double kThermalMaxLocationNameFontMm = 6.0;

/// A single source line may wrap to at most this many lines.
///
/// A 40 x 20 stock holds ~7 lines at the 5.5 pt floor. Letting one marketing
/// description take three of them pushes 型号 / 封装 / 参数 off the label, so
/// each source line is capped at two wrapped lines.
const int kThermalMaxWrapPerLine = 2;

/// One line of text to draw, in millimetre coordinates from the board's
/// top-left corner.
class ThermalTextLine {
  const ThermalTextLine({
    required this.text,
    required this.yMm,
    required this.heightMm,
    required this.fontMm,
    required this.isTitle,
    this.ellipsized = false,
  });

  final String text;
  final double yMm;
  final double heightMm;

  /// Font height in millimetres (what `DrawLableText`'s `fontSize` receives).
  final double fontMm;
  final bool isTitle;

  /// True when the estimated width exceeds the text box, so the SDK's
  /// ellipsis line mode (3) will cut the end of this line.
  final bool ellipsized;

  double get fontPt => fontMm / mmPerPoint;
}

/// A complete, hardware-independent plan for one 40 × 20 mm label.
///
/// This is pure arithmetic so it can be unit-tested without a printer: the FFI
/// layer only converts these millimetre boxes into `DrawLableText` /
/// `DrawLableQrCode` calls.
class ThermalLabelPlan {
  const ThermalLabelPlan({
    required this.widthMm,
    required this.heightMm,
    required this.qrX,
    required this.qrY,
    required this.qrSizeMm,
    required this.payload,
    required this.textX,
    required this.textWidthMm,
    required this.lines,
    required this.truncated,
    required this.omittedLines,
    this.caption = const <ThermalTextLine>[],
  });

  final double widthMm;
  final double heightMm;

  /// The square QR's box, in millimetres from the board's top-left corner.
  final double qrX;
  final double qrY;
  final double qrSizeMm;

  /// The ONE QR value the server put on this label (`LABB:` / `LABL:`).
  final String payload;

  final double textX;
  final double textWidthMm;

  /// Lines printed UNDER the QR (a location label's 库码).
  ///
  /// Kept separate from [lines] because they use a different x/width box: the
  /// narrow column under the code, not the wide column beside it.
  final List<ThermalTextLine> caption;

  /// Title first (when present), then the body lines, in draw order.
  final List<ThermalTextLine> lines;

  /// True when something did not fit: a body line was dropped, or a line will
  /// be ellipsized by the SDK.
  final bool truncated;

  /// Body lines that were not drawn at all (beyond the three-line cap or the
  /// available height).
  final List<String> omittedLines;

  ThermalLabelPlan copyWith({List<String>? omittedLines}) {
    return ThermalLabelPlan(
      widthMm: widthMm,
      heightMm: heightMm,
      qrX: qrX,
      qrY: qrY,
      qrSizeMm: qrSizeMm,
      payload: payload,
      textX: textX,
      textWidthMm: textWidthMm,
      lines: lines,
      truncated: (omittedLines != null && omittedLines.isNotEmpty) || truncated,
      omittedLines: omittedLines ?? this.omittedLines,
      caption: caption,
    );
  }

  List<ThermalTextLine> get bodyLines =>
      lines.where((line) => !line.isTitle).toList();

  ThermalTextLine? get titleLine {
    for (final line in lines) {
      if (line.isTitle) return line;
    }
    return null;
  }

  double get bodyFontMm =>
      bodyLines.isEmpty ? kThermalMinBodyFontMm : bodyLines.first.fontMm;

  /// Compact human-readable description used in the print result.
  String get summary {
    final title = titleLine;
    final titlePt = title == null ? '-' : title.fontPt.toStringAsFixed(1);
    // A location label has no body; saying "正文 5.5 pt（0 行）" would describe a
    // stack that is not printed. It reports its caption instead.
    if (bodyLines.isEmpty && caption.isNotEmpty) {
      return '二维码 ${_mm(qrSizeMm)} mm @(${_mm(qrX)}, ${_mm(qrY)})；'
          '库码「${caption.first.text}」${caption.first.fontPt.toStringAsFixed(1)} pt；'
          '名称 $titlePt pt';
    }
    return '二维码 ${_mm(qrSizeMm)} mm @(${_mm(qrX)}, ${_mm(qrY)})；'
        '文字 x=${_mm(textX)} 宽 ${_mm(textWidthMm)} mm；'
        '标题 $titlePt pt，正文 ${bodyFontMm / mmPerPoint} pt'
        '（${bodyLines.length} 行）';
  }

  static String _mm(double value) {
    if ((value - value.roundToDouble()).abs() < 0.001) {
      return value.round().toString();
    }
    return value.toStringAsFixed(1);
  }
}

/// Plans one thermal label from the server's structured content.
///
/// Layout for the current 40 × 20 mm stock:
///   * QR: 13 × 13 mm at x = 1.5 mm, vertically centred (y = 3.5 mm);
///   * text: x = 16 mm, width = 22 mm, 1 mm top/bottom margin;
///   * title one line, body at most three lines;
///   * the body font is the largest size (between 5.5 pt and ≈7.4 pt) at which
///     the title + body fit both the available height and the 22 mm width;
///   * if even the floor size cannot fit, body lines are dropped from the end
///     and [ThermalLabelPlan.truncated] is set.
///
/// Returns `null` when the requested geometry is too small for any legible
/// label, or when [LabelContent.payload] is empty (a label without its ONE QR
/// must never be printed as if it had one). The caller must refuse.
ThermalLabelPlan? planThermalLabel(
  LabelContent content, {
  double widthMm = kThermalDefaultWidthMm,
  double heightMm = kThermalDefaultHeightMm,
}) {
  if (widthMm < 20 || heightMm < 8) return null;
  // A label without a code must never be printed as if it had one.
  if (content.payload.trim().isEmpty) return null;

  // One geometry: an 11 mm QR in the top-left corner, text to its right.
  //
  // A CODE128 barcode was evaluated for the top edge and rejected: on a 40 x 20
  // stock the strip costs 3.5 mm of text height, which drops a whole field
  // (封装), and the long product name still needs two lines even at 38 mm. It
  // also breaks the "one QR per label" rule, and phones cannot read 1-D codes.
  const double codeX = kThermalQrLeftMarginMm;
  const double codeY = kThermalQrLeftMarginMm;
  final double codeHeight = math.min(
    kThermalQrTargetMm,
    math.min(heightMm - 2 * kThermalVerticalMarginMm, widthMm * 0.4),
  );
  final double textX = codeX + codeHeight + kThermalQrTextGapMm;
  final double textWidth = widthMm - textX - kThermalTextRightMarginMm;
  // Top-aligned with the QR: the first line's top edge sits on the code's top
  // edge. Centring it read as a misaligned label.
  final double textTop = math.max(kThermalVerticalMarginMm, codeY);
  if (codeHeight < 8 || textWidth < 8) return null;

  // Absolute bottom limit for the text stack (was previously passed as a
  // height, which made every fit check pass and text overflow the stock).
  final bottomLimit = heightMm - kThermalVerticalMarginMm;

  // ---------------------------------------------------------------------
  // Location labels use their own geometry.
  //
  // A shelf label is read from a metre away, so the NAME is the headline, not
  // the code: the operator asked for the code under the QR and the name large
  // beside it. A component bag label is the opposite (the trace code is the
  // identity and the fields are the detail), so the two must not share one
  // geometry.
  // ---------------------------------------------------------------------
  if (content.kind == 'location') {
    return _planLocationLabel(
      content,
      widthMm: widthMm,
      heightMm: heightMm,
      codeX: codeX,
      codeY: codeY,
      codeHeight: codeHeight,
      textX: textX,
      textWidth: textWidth,
      bottomLimit: bottomLimit,
    );
  }

  final title = content.title.trim();
  // Prefixes are stripped on the thermal path only: on a 22 mm column they
  // cost more than the value they introduce. The A4 PDF keeps them.
  final allBody = <String>[
    for (final line in content.lines)
      if (line.trim().isNotEmpty) stripLabelPrefix(line),
  ];
  // A title duplicated in the body would waste the one line that is always
  // drawn; the server already de-duplicates, this guards a stray alias.
  // Prefixes were already stripped above, so the comparison is value-to-value:
  // "型号：STM32F103C8T7TR" is now "STM32F103C8T7TR" and matches the title.
  final titleKey = title.replaceAll(RegExp(r'[：:]\s*$'), '').trim();
  if (titleKey.isNotEmpty) {
    allBody.removeWhere((line) => line.trim() == titleKey);
  }

  // Wrap, do not discard. A 40 x 20 stock has 18 mm of text height - seven
  // lines at the 5.5 pt floor - so a long product name can be carried in two
  // or three lines instead of being dropped or cut with an ellipsis.
  //
  // Wrapping happens at the body size actually used, so it is recomputed inside
  // [build] rather than fixed here; [wrappedBody] is a function of the font.
  //
  // TWO separate lists, because they have different lifetimes: a source line
  // beyond the four-line cap is dropped once and for all, while a line that a
  // given font size had to split too far is re-decided on every attempt (a
  // smaller font may fit it). Keeping them in one list meant the per-attempt
  // reset in [wrappedBody] silently erased the cap omissions, and the operator
  // was told a complete label had printed when a field was missing.
  final capOmitted = <String>[];
  final wrapOmitted = <String>[];

  // Source lines beyond the cap never reach the label, and are reported.
  final body = allBody.take(kThermalMaxBodyLines).toList();
  if (allBody.length > body.length) {
    capOmitted.addAll(allBody.sublist(body.length));
  }

  /// Splits [text] into lines that fit [widthMm] at [fontMm].
  ///
  /// Breaks after CJK characters (any position is a legal break) and at ASCII
  /// spaces / hyphens / slashes (never inside a token like `CL05B104KO5NNNC`
  /// unless a single token is itself too wide, which is then hard-split).
  List<String> wrapText(String text, double fontMm, double widthMm) {
    if (estimateTextWidthMm(text, fontMm) <= widthMm + 0.01) return <String>[text];
    final out = <String>[];
    var current = '';
    void flush() {
      if (current.trim().isNotEmpty) out.add(current.trim());
      current = '';
    }

    var i = 0;
    final runes = text.runes.toList();
    while (i < runes.length) {
      final rune = runes[i];
      final ch = String.fromCharCode(rune);
      final candidate = current + ch;
      if (estimateTextWidthMm(candidate, fontMm) <= widthMm + 0.01) {
        current = candidate;
        i++;
        continue;
      }
      // Does not fit: break before this rune.
      final isCjk = rune >= 0x2E80;
      final isSpace = rune == 0x20;
      if (isCjk || isSpace) {
        flush();
        if (!isSpace) current = ch;
        i++;
        continue;
      }
      // ASCII: prefer breaking at the last space/hyphen/slash in `current`.
      var cut = -1;
      for (var k = current.length - 1; k > 0; k--) {
        final c = current.codeUnitAt(k);
        if (c == 0x20 || c == 0x2D || c == 0x2F) {
          cut = k;
          break;
        }
      }
      if (cut > 0) {
        out.add(current.substring(0, cut).trim());
        current = current.substring(cut + 1);
        continue;
      }
      // One unbreakable token wider than the column: hard-split it.
      if (current.isNotEmpty) flush();
      current = ch;
      i++;
    }
    flush();
    return out.isEmpty ? <String>[text] : out;
  }

  // Each source line wrapped at the current body size; recomputed per attempt.
  List<String> wrappedBody(double fontMm) {
    final out = <String>[];
    final dropped = <String>[];
    for (final line in body) {
      final pieces = wrapText(line, fontMm, textWidth);
      if (pieces.length <= kThermalMaxWrapPerLine) {
        out.addAll(pieces);
        continue;
      }
      // A description that needs more than two lines would push every other
      // field off the stock. Keep the first two lines and report the rest - the
      // operator can read the full text in the app.
      out.addAll(pieces.take(kThermalMaxWrapPerLine));
      dropped.add(line);
    }
    // Record what THIS attempt dropped, replacing (not appending to) the list:
    // a smaller font may fit the line, and a stale entry would then claim text
    // is missing when it is printed. The cap omissions live in their own list
    // and are untouched here.
    wrapOmitted
      ..clear()
      ..addAll(dropped);
    return out;
  }

  ThermalLabelPlan build(double bodyFont) {
    final titleFont = math.max(
      kThermalMinTitleFontMm,
      math.min(kThermalMaxTitleFontMm, bodyFont * kThermalTitleScale),
    );
    // Wrap the body at THIS size, so a long name becomes several readable lines
    // instead of one ellipsized one. Lines that are still too wide after
    // wrapping are a single unbreakable token; the SDK's ellipsis marks them.
    final wrapped = wrappedBody(bodyFont);
    final titleHeight = title.isEmpty ? 0.0 : titleFont * kThermalLineHeightFactor;
    final bodyHeight = bodyFont * kThermalLineHeightFactor;

    final ellipsized = <String>{};
    if (title.isNotEmpty &&
        estimateTextWidthMm(title, titleFont) > textWidth + 0.01) {
      ellipsized.add(title);
    }
    for (final line in wrapped) {
      if (estimateTextWidthMm(line, bodyFont) > textWidth + 0.01) {
        ellipsized.add(line);
      }
    }

    // QR mode: the first text line's TOP edge sits on the QR's top edge (not
    // centred against it - that read as a misaligned label). Barcode mode: text
    // starts below the strip.
    final startY = textTop;

    final lines = <ThermalTextLine>[];
    var y = startY;
    if (title.isNotEmpty) {
      lines.add(
        ThermalTextLine(
          text: title,
          yMm: y,
          heightMm: titleHeight,
          fontMm: titleFont,
          isTitle: true,
          ellipsized: ellipsized.contains(title),
        ),
      );
      y += titleHeight;
    }
    for (final line in wrapped) {
      lines.add(
        ThermalTextLine(
          text: line,
          yMm: y,
          heightMm: bodyHeight,
          fontMm: bodyFont,
          isTitle: false,
          ellipsized: ellipsized.contains(line),
        ),
      );
      y += bodyHeight;
    }

    return ThermalLabelPlan(
      widthMm: widthMm,
      heightMm: heightMm,
      qrX: codeX,
      qrY: codeY,
      qrSizeMm: codeHeight,
      payload: content.payload,
      textX: textX,
      textWidthMm: textWidth,
      lines: lines,
      truncated: capOmitted.isNotEmpty ||
          wrapOmitted.isNotEmpty ||
          ellipsized.isNotEmpty,
      // Draw order: the cap omissions are the LAST source lines, so they come
      // after anything a too-narrow font had to drop.
      omittedLines: List<String>.unmodifiable(<String>[
        ...wrapOmitted,
        ...capOmitted,
      ]),
    );
  }

  // Pass 1: the largest body size that fits the stock AND loses no text.
  //
  // Size is worth less than completeness. A long description can need three
  // wrapped lines at the largest size (over the two-line cap, so the source
  // line is dropped) while fitting two at a slightly smaller one. Printing
  // 封装 at 7 pt is worth more to the operator than printing it at 7.4 pt and
  // dropping the description, so a size that would omit a field is skipped.
  for (var font = kThermalMaxBodyFontMm;
      font >= kThermalMinBodyFontMm - 0.001;
      font -= 0.05) {
    final plan = build(font);
    if (plan.omittedLines.isNotEmpty) continue;
    if (plan.lines.every((line) => !line.ellipsized) &&
        _fitsHeight(plan, bottomLimit)) {
      return plan;
    }
  }

  // Pass 2: no size keeps every source line. Take the largest that fits at
  // all and let the plan report what it had to drop.
  for (var font = kThermalMaxBodyFontMm;
      font >= kThermalMinBodyFontMm - 0.001;
      font -= 0.05) {
    final plan = build(font);
    if (plan.lines.every((line) => !line.ellipsized) &&
        _fitsHeight(plan, bottomLimit)) {
      return plan;
    }
  }

  // Floor size reached and the stack still overflows the stock. Wrapping has
  // already handled width, so the only remedy left is dropping whole SOURCE
  // lines from the end - and each drop must survive the next [build] call,
  // which recomputes [omitted] from scratch.
  final dropped = <String>[];
  while (body.isNotEmpty) {
    final plan = build(kThermalMinBodyFontMm);
    final recorded = List<String>.of(plan.omittedLines);
    if (_fitsHeight(plan, bottomLimit)) {
      return plan.copyWith(
        omittedLines: List<String>.unmodifiable([...dropped, ...recorded]),
      );
    }
    // Drop the last remaining source line and remember it.
    dropped.insert(0, body.removeLast());
  }
  // Nothing left to draw: return an empty-bodied plan so the caller can refuse.
  return build(kThermalMinBodyFontMm).copyWith(
    omittedLines: List<String>.unmodifiable(dropped),
  );
}

/// Geometry of a 库位 (shelf) label: QR top-left, 库码 under it, NAME large.
///
/// The operator reads this label standing in the aisle, so:
///   * the **name** is the biggest thing on the label, in the wide right-hand
///     column - it is what tells them "this is the resistor shelf";
///   * the **库码** sits directly UNDER the QR, in the narrow column, because
///     that is the value the code encodes and the two belong together;
///   * the code column is exactly as wide as the QR, so a misprint cannot push
///     the caption under the name column.
///
/// The name gets its own fit loop and is allowed to be far larger than a bag
/// label's body (a shelf has one line to say, not four), but it is still bounded
/// by [kThermalMaxTitleFontMm] so a long location name cannot overflow.
ThermalLabelPlan? _planLocationLabel(
  LabelContent content, {
  required double widthMm,
  required double heightMm,
  required double codeX,
  required double codeY,
  required double codeHeight,
  required double textX,
  required double textWidth,
  required double bottomLimit,
}) {
  // The server sends `title` = the 库码 for a location label (`lab_code or
  // name`), so the human name lives in the body lines ("名称：货架A"). Taking
  // `title` here would print the CODE at headline size and leave the name tiny.
  String name = '';
  for (final line in content.lines) {
    final trimmed = line.trim();
    if (trimmed.isEmpty) continue;
    final match = RegExp(r'^(名称|库位名称|name)[：:]\s*(.+)$').firstMatch(trimmed);
    if (match != null) {
      name = match.group(2)!.trim();
      break;
    }
  }
  if (name.isEmpty) {
    // No labelled name line: fall back to the first body value, then to the
    // title (which for a location without a code IS the name).
    final firstBody = content.lines
        .map((line) => stripLabelPrefix(line))
        .firstWhere((line) => line.isNotEmpty, orElse: () => '');
    name = firstBody.isNotEmpty ? firstBody : content.title.trim();
  }

  // The caption under the QR: the 库码 the payload encodes (`LABL:K000003` ->
  // `K000003`). The server also sends it as a body line, but taking it from the
  // payload is what guarantees the printed code and the scanned code are the
  // same string.
  final code = content.payload.contains(':')
      ? content.payload.split(':').last.trim()
      : content.payload.trim();

  const captionHeight = kThermalCaptionFontMm * kThermalLineHeightFactor;
  final captionFits = codeY + codeHeight + captionHeight <= bottomLimit;
  final caption = <ThermalTextLine>[
    if (code.isNotEmpty && captionFits)
      ThermalTextLine(
        text: code,
        yMm: codeY + codeHeight,
        heightMm: captionHeight,
        fontMm: kThermalCaptionFontMm,
        isTitle: false,
        ellipsized: estimateTextWidthMm(code, kThermalCaptionFontMm) >
            codeHeight + 0.01,
      ),
  ];

  // The name: the largest size that fits the right-hand column, one line if it
  // can be, wrapped to two if not.
  final nameLines = <ThermalTextLine>[];
  var nameFont = kThermalMaxLocationNameFontMm;
  List<String> wrapped = const <String>[];
  var ellipsized = false;
  for (; nameFont >= kThermalMinTitleFontMm - 0.001; nameFont -= 0.1) {
    if (name.isEmpty) break;
    wrapped = _wrapAt(name, nameFont, textWidth);
    final fits = wrapped.every(
      (line) => estimateTextWidthMm(line, nameFont) <= textWidth + 0.01,
    );
    final height = wrapped.length * nameFont * kThermalLineHeightFactor;
    if (fits && codeY + height <= bottomLimit) {
      ellipsized = false;
      break;
    }
    ellipsized = !fits;
  }
  if (name.isNotEmpty) {
    var y = math.max(kThermalVerticalMarginMm, codeY);
    for (final line in wrapped.isEmpty ? <String>[name] : wrapped) {
      nameLines.add(
        ThermalTextLine(
          text: line,
          yMm: y,
          heightMm: nameFont * kThermalLineHeightFactor,
          fontMm: nameFont,
          isTitle: true,
          ellipsized: ellipsized,
        ),
      );
      y += nameFont * kThermalLineHeightFactor;
    }
  }

  return ThermalLabelPlan(
    widthMm: widthMm,
    heightMm: heightMm,
    qrX: codeX,
    qrY: codeY,
    qrSizeMm: codeHeight,
    payload: content.payload,
    textX: textX,
    textWidthMm: textWidth,
    lines: nameLines,
    truncated: ellipsized,
    omittedLines: const <String>[],
    caption: List<ThermalTextLine>.unmodifiable(caption),
  );
}

/// Greedy wrap for the shelf label (CJK anywhere, ASCII at spaces/hyphens).
List<String> _wrapAt(String text, double fontMm, double widthMm) {
  if (estimateTextWidthMm(text, fontMm) <= widthMm + 0.01) {
    return <String>[text];
  }
  final out = <String>[];
  var current = '';
  for (final rune in text.runes) {
    final ch = String.fromCharCode(rune);
    if (estimateTextWidthMm(current + ch, fontMm) <= widthMm + 0.01) {
      current += ch;
      continue;
    }
    if (current.isNotEmpty) out.add(current);
    current = ch;
  }
  if (current.isNotEmpty) out.add(current);
  return out;
}

bool _fitsHeight(ThermalLabelPlan plan, double bottomLimitMm) {
  final last = plan.lines.isEmpty ? null : plan.lines.last;
  if (last == null) return true;
  return last.yMm + last.heightMm <= bottomLimitMm + 0.01;
}

/// Removes a leading Chinese field label such as `名称：` / `型号：` / `封装：`.
///
/// The 40 × 20 mm text column is only 22 mm wide. A four-character prefix costs
/// about 5.8 mm at the 5.5 pt floor - enough to ellipsize the actual value
/// (`名称：0.1uF 0402 50V X7R` needs 23.7 mm, the value alone needs 17.8 mm).
/// The prefix carries no information the position does not already convey, so
/// the thermal path drops it; the A4 PDF keeps the full text.
///
/// Only a short label at the very start is removed, and never when the rest
/// would become empty (`封装：` alone would leave nothing to print).
String stripLabelPrefix(String text) {
  final trimmed = text.trim();
  final match = RegExp(r'^([^：:]{1,6})[：:]\s*(.+)$').firstMatch(trimmed);
  if (match == null) return trimmed;
  final label = match.group(1)!.trim();
  final value = match.group(2)!.trim();
  if (value.isEmpty) return trimmed;
  // A value that is itself a code-like token keeps its label only when the
  // label is the whole meaning (e.g. "C编号：C2054912" -> "C2054912" is fine).
  if (label.isEmpty) return trimmed;
  return value;
}

/// Rough advance width of [text] at [fontMm], in millimetres.
///
/// This never needs to be exact: it only decides when to shrink or mark a line
/// as ellipsized. CJK/full-width runes are square, ASCII averages a little over
/// half an em in the SDK's ZT001 font.
double estimateTextWidthMm(String text, double fontMm) {
  var width = 0.0;
  for (final rune in text.runes) {
    if (rune >= 0x2E80) {
      // CJK and full-width punctuation are square.
      width += fontMm;
    } else if (rune == 0x20) {
      width += fontMm * 0.30;
    } else if (_isNarrowAscii(rune)) {
      width += fontMm * 0.45;
    } else {
      width += fontMm * 0.56;
    }
  }
  return width;
}

bool _isNarrowAscii(int rune) {
  if (rune < 0x21 || rune > 0x7E) return false;
  // i, l, j, t, f, r and punctuation take less than an average digit.
  const narrow = 'ijl.,:;!|/\\\'"`()[]{}ftr';
  return narrow.codeUnits.contains(rune);
}
