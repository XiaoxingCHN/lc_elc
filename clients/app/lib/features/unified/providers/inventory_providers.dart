import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/lab_api_exception.dart';
import '../../../services/lab_api_client.dart';
import '../models/detail_models.dart';
import '../models/inventory.dart';
import '../services/scan_sources.dart';
import 'lab_errors.dart';
import 'unified_providers.dart';

export 'lab_errors.dart' show describeLabError, isOfflineFailure, isSessionExpired;

/// `/lab/api/inventory/bootstrap`, refreshed whenever stock changes.
///
/// Supplies the internal locations and - crucially - the system accounts the
/// operator may select as 领用人.
final inventoryBootstrapProvider = FutureProvider<InventoryBootstrap>((ref) async {
  ref.watch(dataRevisionProvider);
  ref.watch(effectiveSessionScopeProvider);
  final api = ref.watch(labApiProvider);
  return api.bootstrap();
});

/// Internal locations, re-read from the server after a write.
final inventoryLocationsProvider =
    FutureProvider<List<LabStockLocation>>((ref) async {
  ref.watch(dataRevisionProvider);
  ref.watch(effectiveSessionScopeProvider);
  final api = ref.watch(labApiProvider);
  return api.locations();
});

// -----------------------------------------------------------------------------
// Receipt (入库): scan / type a code, choose a location, confirm the quantity
// -----------------------------------------------------------------------------

/// Form + submission state of one receipt.
class ReceiptFormState {
  const ReceiptFormState({
    this.input = '',
    this.resolved,
    this.itemKey = '',
    this.itemName = '',
    this.templateId,
    this.sn = '',
    this.materials = const <LabMaterial>[],
    this.locationId,
    this.locationLabel = '',
    this.quantityText = '',
    this.supplierQr = '',
    this.note = '',
    this.resolving = false,
    this.submitting = false,
    this.error,
    this.errorCode,
    this.notice,
    this.result,
    this.succeeded = false,
    required this.requestKey,
  });

  /// The raw code as scanned / typed / pasted.
  final String input;
  final ResolvedCode? resolved;
  final String itemKey;
  final String itemName;

  /// The EXACT local archive (product.template) this receipt belongs to.
  ///
  /// A scan of an SN or of an existing bag carries the archive id; when the card
  /// has several archives the operator must choose one. It is never picked by
  /// position.
  final int? templateId;

  /// SN of the chosen archive (display / confirmation only).
  final String sn;

  /// Known archives of this card. More than one means a choice is mandatory.
  final List<LabMaterial> materials;

  final int? locationId;
  final String locationLabel;
  final String quantityText;

  /// Original supplier / trace payload stored on the receipt.
  final String supplierQr;

  final String note;
  final bool resolving;
  final bool submitting;
  final String? error;
  final String? errorCode;
  final String? notice;
  final ReceiptResult? result;
  final bool succeeded;

  /// Idempotency key of the CURRENT submission. It survives a failure on
  /// purpose: retrying the same receipt must not create a second bag.
  final String requestKey;

  double? get quantity => double.tryParse(quantityText.trim());

  bool get isBusy => resolving || submitting;

  /// True when this card has several archives and none is chosen.
  ///
  /// Submitting is blocked on purpose: the server would answer
  /// `AMBIGUOUS_MATERIAL`, and picking one at random on the client is exactly what
  /// root forbids.
  bool get needsTemplateChoice => templateId == null && materials.length > 1;

  bool get canSubmit =>
      !isBusy &&
      itemKey.trim().isNotEmpty &&
      locationId != null &&
      (quantity ?? 0) > 0 &&
      !needsTemplateChoice;

  /// What is still missing, as one actionable line.
  String get missingHint {
    final parts = <String>[];
    if (itemKey.trim().isEmpty) parts.add('要入库的器件');
    if (locationId == null) parts.add('入库库位');
    if ((quantity ?? 0) <= 0) parts.add('入库数量');
    if (needsTemplateChoice) parts.add('入库的本地档案 / SN');
    if (parts.isEmpty) return '';
    return '还需要：${parts.join('、')}';
  }

  ReceiptFormState copyWith({
    String? input,
    Object? resolved = _unset,
    String? itemKey,
    String? itemName,
    Object? templateId = _unset,
    String? sn,
    List<LabMaterial>? materials,
    Object? locationId = _unset,
    String? locationLabel,
    String? quantityText,
    String? supplierQr,
    String? note,
    bool? resolving,
    bool? submitting,
    Object? error = _unset,
    Object? errorCode = _unset,
    Object? notice = _unset,
    Object? result = _unset,
    bool? succeeded,
    String? requestKey,
  }) {
    return ReceiptFormState(
      input: input ?? this.input,
      resolved: identical(resolved, _unset) ? this.resolved : resolved as ResolvedCode?,
      itemKey: itemKey ?? this.itemKey,
      itemName: itemName ?? this.itemName,
      templateId:
          identical(templateId, _unset) ? this.templateId : templateId as int?,
      sn: sn ?? this.sn,
      materials: materials ?? this.materials,
      locationId:
          identical(locationId, _unset) ? this.locationId : locationId as int?,
      locationLabel: locationLabel ?? this.locationLabel,
      quantityText: quantityText ?? this.quantityText,
      supplierQr: supplierQr ?? this.supplierQr,
      note: note ?? this.note,
      resolving: resolving ?? this.resolving,
      submitting: submitting ?? this.submitting,
      error: identical(error, _unset) ? this.error : error as String?,
      errorCode: identical(errorCode, _unset) ? this.errorCode : errorCode as String?,
      notice: identical(notice, _unset) ? this.notice : notice as String?,
      result: identical(result, _unset) ? this.result : result as ReceiptResult?,
      succeeded: succeeded ?? this.succeeded,
      requestKey: requestKey ?? this.requestKey,
    );
  }

  static const Object _unset = Object();
}

/// Drives the receipt flow.
///
///   * `resolve_code` is consulted for every scanned / typed code, so a supplier
///     LCSC bag payload, this system's `LABB:` trace code, a `LABL:` location
///     code and a bare `C123456` all work through ONE entry point;
///   * nothing is written to stock until [submit] confirms - cancelling or
///     resolving never changes inventory;
///   * the request key is reused across retries of the same submission and
///     rotated only after a success;
///   * a failure keeps every typed value on screen.
class ReceiptController extends StateNotifier<ReceiptFormState> {
  ReceiptController({
    required LabApiClient api,
    required String Function() newRequestKey,
    void Function(String inventoryRevision)? onInventoryChanged,
  })  : _api = api,
        _newRequestKey = newRequestKey,
        _onInventoryChanged = onInventoryChanged,
        super(ReceiptFormState(requestKey: newRequestKey()));

  final LabApiClient _api;
  final String Function() _newRequestKey;
  final void Function(String inventoryRevision)? _onInventoryChanged;

  void setInput(String value) {
    state = state.copyWith(input: value, error: null);
  }

  void setQuantity(String value) {
    state = state.copyWith(quantityText: value, error: null);
  }

  void setSupplierQr(String value) {
    state = state.copyWith(supplierQr: value);
  }

  void setNote(String value) {
    state = state.copyWith(note: value);
  }

  void setItem({required String itemKey, String itemName = ''}) {
    state = state.copyWith(itemKey: itemKey, itemName: itemName, error: null);
  }

  void setLocation(int? locationId, {String label = ''}) {
    state = state.copyWith(locationId: locationId, locationLabel: label, error: null);
  }

  /// Records the local archives known for this card.
  ///
  /// One archive is selected automatically (there is nothing to choose); several
  /// require an explicit choice; none means the server will create one on demand.
  void setMaterials(List<LabMaterial> materials) {
    final picked = _pickArchive(
      materials: materials,
      currentTemplateId: state.templateId,
      currentSn: state.sn,
    );
    state = state.copyWith(
      materials: materials,
      templateId: picked.templateId,
      sn: picked.sn,
    );
  }

  /// The operator's explicit choice of the archive this bag belongs to.
  void setTemplate(int? templateId, {String sn = ''}) {
    state = state.copyWith(templateId: templateId, sn: sn, error: null);
  }

  /// Chooses the archive that a receipt must be bound to.
  ///
  /// Order of authority: the archive id carried by the SCAN, then a single
  /// candidate, then the operator's previous choice if it is still valid. Several
  /// candidates with no scan and no choice stays `null` - the UI then demands a
  /// selection and the server would answer AMBIGUOUS_MATERIAL.
  static ({int? templateId, String sn}) _pickArchive({
    required List<LabMaterial> materials,
    required int? currentTemplateId,
    required String currentSn,
    int? scannedTemplateId,
    String? scannedSn,
  }) {
    if (scannedTemplateId != null && scannedTemplateId > 0) {
      return (templateId: scannedTemplateId, sn: scannedSn ?? currentSn);
    }
    if (materials.length == 1) {
      final only = materials.first;
      return (templateId: only.templateId, sn: only.sn);
    }
    if (materials.isEmpty) {
      return (templateId: currentTemplateId, sn: currentSn);
    }
    if (currentTemplateId != null &&
        materials.any((material) => material.templateId == currentTemplateId)) {
      return (templateId: currentTemplateId, sn: currentSn);
    }
    return (templateId: null, sn: '');
  }

  /// Resolves the current input against `/lab/api/inventory/resolve_code`.
  ///
  /// An unreadable code produces an actionable Chinese message and leaves the
  /// input untouched so the operator can correct it.
  Future<ResolvedCode?> resolve({String? rawOverride}) async {
    final raw = normalizeScanInput(rawOverride ?? state.input);
    if (raw.isEmpty) {
      state = state.copyWith(error: '请先输入或扫描编码。');
      return null;
    }

    state = state.copyWith(
      input: raw,
      resolving: true,
      error: null,
      notice: null,
      succeeded: false,
    );

    try {
      final resolved = await _api.resolveCode(raw);
      final itemKey = resolved.itemKey.isNotEmpty ? resolved.itemKey : state.itemKey;
      final locationId = resolved.impliedLocationId ?? state.locationId;
      final locationLabel = resolved.location != null
          ? resolved.location!.display
          : state.locationLabel;
      final supplierQr = resolved.supplierQr ?? state.supplierQr;

      // Bind the scanned code to the EXACT archive it named (an SN scan or an
      // existing bag); never fall back to the first archive of the card.
      final materials = resolved.materials.isNotEmpty
          ? resolved.materials
          : state.materials;
      final picked = _pickArchive(
        materials: materials,
        currentTemplateId: state.templateId,
        currentSn: state.sn,
        scannedTemplateId: resolved.productTemplateId,
        scannedSn: resolved.sn,
      );

      String? notice;
      String? error;
      if (resolved.isUnknown) {
        error = '未能识别该编码：$raw。\n'
            '可扫描本系统追溯袋码（LABB:）、库位码（LABL:）、原立创物料袋二维码，'
            '或输入 C 编号后从器件库选择器件。';
      } else if (resolved.isLocation && itemKey.isEmpty) {
        notice = '已识别库位「${resolved.location?.display ?? raw}」。'
            '请再扫描物料袋码，或从器件库选择要入库的器件。';
      } else {
        final target = resolved.bag?.display ??
            (itemKey.isNotEmpty ? itemKey : (resolved.location?.display ?? raw));
        notice = '已识别${resolved.displayKind}：$target';
      }

      state = state.copyWith(
        resolved: resolved,
        itemKey: itemKey,
        supplierQr: supplierQr,
        locationId: locationId,
        locationLabel: locationLabel,
        materials: materials,
        templateId: picked.templateId,
        sn: picked.sn,
        resolving: false,
        notice: notice,
        error: error,
        errorCode: error == null ? null : 'UNRESOLVED_CODE',
      );
      return resolved;
    } on LabApiException catch (error) {
      state = state.copyWith(
        resolving: false,
        error: error.message,
        errorCode: error.code,
      );
      return null;
    } catch (error) {
      state = state.copyWith(resolving: false, error: describeLabError(error));
      return null;
    }
  }

  /// Confirms the receipt. Only a `true` result means stock changed.
  Future<bool> submit() async {
    if (state.submitting) return false;

    final problems = <String>[];
    final itemKey = state.itemKey.trim();
    final locationId = state.locationId;
    final quantity = state.quantity;
    if (itemKey.isEmpty) problems.add('请选择或扫描要入库的器件。');
    if (locationId == null) problems.add('请选择入库的内部库位。');
    if (quantity == null || quantity <= 0) problems.add('请输入大于 0 的入库数量。');
    if (state.needsTemplateChoice) {
      problems.add('该编号下有 ${state.materials.length} 个本地档案，请先选择本次入库的 SN / 档案。');
    }
    if (problems.isNotEmpty) {
      state = state.copyWith(error: problems.join('\n'));
      return false;
    }

    final location = state.locationLabel;
    // Captured as non-null locals: the validation above guarantees them, and a
    // nested catch block would otherwise lose the type promotion.
    final locationIdValue = locationId!;
    final quantityValue = quantity!;
    final supplierQrValue =
        state.supplierQr.trim().isEmpty ? null : state.supplierQr.trim();
    final noteValue = state.note.trim();
    final templateIdValue = state.templateId;

    state = state.copyWith(submitting: true, error: null, notice: null);

    try {
      ReceiptResult result;
      String? autoCreatedSn;
      try {
        result = await _api.receipt(
          requestKey: state.requestKey,
          itemKey: itemKey,
          locationId: locationIdValue,
          quantity: quantityValue,
          productTemplateId: templateIdValue,
          supplierQr: supplierQrValue,
          note: noteValue,
        );
      } on LabApiException catch (error) {
        // The server refuses to guess between several archives. Surface its
        // candidates and let the operator choose - never pick one here.
        if (error.code == 'AMBIGUOUS_MATERIAL') {
          final candidates = LabMaterial.listFrom(
            error.fields['candidates'] ?? error.fields['materials'],
          );
          state = state.copyWith(
            submitting: false,
            materials: candidates.isNotEmpty ? candidates : state.materials,
            templateId: null,
            sn: '',
            error: candidates.isEmpty
                ? error.message
                : '${error.message}\n请选择本次入库的本地档案 / SN：'
                    '${candidates.map((material) => material.display).join('、')}',
            errorCode: error.code,
          );
          return false;
        }
        // A captured catalog row may have no local archive yet. Root's rule:
        // a first receipt must NOT fail with "material does not exist". Create
        // the archive once (the SERVER generates the SN) and retry the very
        // same submission with the very same request key, so the server-side
        // idempotency still holds. Where the workflow implements atomic
        // on-demand creation, this branch never runs.
        if (!_looksLikeMissingMaterial(error)) rethrow;
        final material = await _api.createMaterial(itemKey);
        autoCreatedSn = material.sn;
        result = await _api.receipt(
          requestKey: state.requestKey,
          itemKey: itemKey,
          locationId: locationIdValue,
          quantity: quantityValue,
          productTemplateId: material.productTemplateId ?? templateIdValue,
          supplierQr: supplierQrValue,
          note: noteValue,
        );
      }

      final quantityLabel = _format(quantityValue);
      final onHand = result.labQuantity;
      final archiveNote = state.sn.isNotEmpty
          ? '（本地档案 SN ${state.sn}）'
          : (templateIdValue != null ? '（本地档案 #$templateIdValue）' : '');
      final createdNote = autoCreatedSn == null
          ? archiveNote
          : (autoCreatedSn.isEmpty
              ? '（已自动创建本地物料档案）'
              : '（已自动创建本地物料档案 SN $autoCreatedSn）');
      state = state.copyWith(
        submitting: false,
        succeeded: true,
        result: result,
        notice: '入库成功：$quantityLabel 件 → ${location.isEmpty ? '库位#$locationId' : location}'
            '$createdNote'
            '${onHand == null ? '' : '，该器件内部库存 ${_format(onHand)}'}。',
        // A NEW submission gets a NEW key; the old one already did its job.
        requestKey: _newRequestKey(),
      );
      _onInventoryChanged?.call(result.inventoryRevision);
      return true;
    } on LabApiException catch (error) {
      // The key is kept: pressing 重试 again must not create a second bag.
      state = state.copyWith(
        submitting: false,
        error: error.message,
        errorCode: error.code,
      );
      return false;
    } catch (error) {
      state = state.copyWith(submitting: false, error: describeLabError(error));
      return false;
    }
  }

  /// True when the server says the catalog row has no local archive yet.
  static bool _looksLikeMissingMaterial(LabApiException error) {
    const codes = <String>{
      'MATERIAL_NOT_FOUND',
      'MATERIAL_MISSING',
      'LOCAL_MATERIAL_REQUIRED',
      'TEMPLATE_NOT_FOUND',
      'PRODUCT_NOT_FOUND',
      'NOT_ARCHIVED',
      'NOT_FOUND',
    };
    if (codes.contains(error.code.toUpperCase())) return true;
    final message = error.message;
    final mentionsMaterial =
        message.contains('物料') || message.contains('档案') || message.contains('建档');
    final mentionsMissing = message.contains('不存在') ||
        message.contains('未建') ||
        message.contains('没有') ||
        message.contains('缺少');
    return mentionsMaterial && mentionsMissing;
  }

  /// Clears the form for the next receipt (new idempotency key).
  void reset() {
    state = ReceiptFormState(requestKey: _newRequestKey());
  }

  /// Keeps the scanned code but starts a fresh submission key.
  void startNewSubmission() {
    state = state.copyWith(
      requestKey: _newRequestKey(),
      succeeded: false,
      result: null,
      notice: null,
      error: null,
    );
  }

  static String _format(double value) {
    if (value == value.roundToDouble()) return value.toInt().toString();
    return value.toStringAsFixed(2);
  }
}

// -----------------------------------------------------------------------------
// Issue (领料): pick bags + quantities, a system-account borrower, a project
// -----------------------------------------------------------------------------

/// One bag line in the issue form.
class IssueBagLine {
  const IssueBagLine({
    required this.bagId,
    required this.label,
    required this.available,
    this.quantityText = '',
    this.locationLabel = '',
  });

  final int bagId;

  /// Bag trace code / display label.
  final String label;

  /// Quantity the bag currently holds (client-side pre-check; the server is
  /// still the authority).
  final double available;

  final String quantityText;

  /// Where the bag sits (the return default is the original location).
  final String locationLabel;

  double? get quantity => double.tryParse(quantityText.trim());

  bool get hasQuantity => (quantity ?? 0) > 0;

  bool get exceedsAvailable => (quantity ?? 0) > available + 0.000001;

  IssueBagLine copyWith({String? quantityText}) {
    return IssueBagLine(
      bagId: bagId,
      label: label,
      available: available,
      quantityText: quantityText ?? this.quantityText,
      locationLabel: locationLabel,
    );
  }

  String get availableLabel => available == available.roundToDouble()
      ? available.toInt().toString()
      : available.toStringAsFixed(2);
}

/// Form + submission state of one issue.
class IssueFormState {
  const IssueFormState({
    this.itemKey = '',
    this.itemName = '',
    this.lines = const <IssueBagLine>[],
    this.borrowerId,
    this.project = '',
    this.note = '',
    this.submitting = false,
    this.error,
    this.errorCode,
    this.notice,
    this.result,
    this.succeeded = false,
    required this.requestKey,
  });

  final String itemKey;
  final String itemName;
  final List<IssueBagLine> lines;

  /// Selected system account. NEVER free text - the contract makes it required.
  final int? borrowerId;

  final String project;
  final String note;
  final bool submitting;
  final String? error;
  final String? errorCode;
  final String? notice;
  final IssueResult? result;
  final bool succeeded;
  final String requestKey;

  double get totalQuantity =>
      lines.fold<double>(0, (sum, line) => sum + (line.quantity ?? 0));

  bool get hasLines => lines.isNotEmpty;

  bool get isBusy => submitting;

  bool get canSubmit =>
      !submitting && lines.isNotEmpty && borrowerId != null && project.trim().isNotEmpty;

  /// All blocking problems, in the order the operator should fix them.
  List<String> get problems {
    final result = <String>[];
    if (lines.isEmpty) result.add('请至少选择一个来源袋并填写数量。');
    if (lines.any((line) => !line.hasQuantity)) {
      result.add('每个来源袋的数量都要大于 0。');
    }
    if (lines.any((line) => line.exceedsAvailable)) {
      result.add('领用数量超过袋内可用数量，请调整。');
    }
    if (borrowerId == null) result.add('请选择领用人（必须是已建立的系统账号）。');
    if (project.trim().isEmpty) result.add('请填写项目。');
    return result;
  }

  String get missingHint => problems.isEmpty ? '' : problems.first;

  IssueFormState copyWith({
    String? itemKey,
    String? itemName,
    List<IssueBagLine>? lines,
    Object? borrowerId = _unset,
    String? project,
    String? note,
    bool? submitting,
    Object? error = _unset,
    Object? errorCode = _unset,
    Object? notice = _unset,
    Object? result = _unset,
    bool? succeeded,
    String? requestKey,
  }) {
    return IssueFormState(
      itemKey: itemKey ?? this.itemKey,
      itemName: itemName ?? this.itemName,
      lines: lines ?? this.lines,
      borrowerId:
          identical(borrowerId, _unset) ? this.borrowerId : borrowerId as int?,
      project: project ?? this.project,
      note: note ?? this.note,
      submitting: submitting ?? this.submitting,
      error: identical(error, _unset) ? this.error : error as String?,
      errorCode: identical(errorCode, _unset) ? this.errorCode : errorCode as String?,
      notice: identical(notice, _unset) ? this.notice : notice as String?,
      result: identical(result, _unset) ? this.result : result as IssueResult?,
      succeeded: succeeded ?? this.succeeded,
      requestKey: requestKey ?? this.requestKey,
    );
  }

  static const Object _unset = Object();
}

/// Drives the issue flow.
///
/// The borrower rule is enforced twice: the UI only offers
/// [InventoryBootstrap.selectableBorrowers] (the operator's own account unless
/// the server granted "issue for others"), and the controller refuses to submit
/// without one. The ACTOR is never sent by the client at all - the server takes
/// it from the authenticated session, so a manager issuing on behalf of a
/// colleague cannot be recorded as that colleague.
class IssueController extends StateNotifier<IssueFormState> {
  IssueController({
    required LabApiClient api,
    required String Function() newRequestKey,
    void Function(String inventoryRevision)? onInventoryChanged,
  })  : _api = api,
        _newRequestKey = newRequestKey,
        _onInventoryChanged = onInventoryChanged,
        super(IssueFormState(requestKey: newRequestKey()));

  final LabApiClient _api;
  final String Function() _newRequestKey;
  final void Function(String inventoryRevision)? _onInventoryChanged;

  void setItem({required String itemKey, String itemName = ''}) {
    state = state.copyWith(itemKey: itemKey, itemName: itemName, error: null);
  }

  void setProject(String value) => state = state.copyWith(project: value, error: null);

  void setNote(String value) => state = state.copyWith(note: value);

  void setBorrower(int? borrowerId) {
    state = state.copyWith(borrowerId: borrowerId, error: null);
  }

  /// Adds a bag (ignored when it is already on the list).
  void addBag(LabBag bag) {
    final existing = state.lines.any((line) => line.bagId == bag.id);
    if (existing || !bag.hasId) return;
    state = state.copyWith(
      lines: <IssueBagLine>[
        ...state.lines,
        IssueBagLine(
          bagId: bag.id!,
          label: bag.display,
          available: bag.remaining,
          locationLabel: bag.locationCode.isNotEmpty ? bag.locationCode : bag.locationName,
        ),
      ],
      error: null,
    );
  }

  void removeBag(int bagId) {
    state = state.copyWith(
      lines: state.lines.where((line) => line.bagId != bagId).toList(),
    );
  }

  void updateQuantity(int bagId, String quantityText) {
    state = state.copyWith(
      lines: state.lines
          .map(
            (line) =>
                line.bagId == bagId ? line.copyWith(quantityText: quantityText) : line,
          )
          .toList(),
      error: null,
    );
  }

  /// Confirms the issue. Only a `true` result means stock left the lab.
  Future<bool> submit() async {
    if (state.submitting) return false;

    final problems = <String>[];
    final lines = <({int bagId, double quantity})>[];
    for (final line in state.lines) {
      final quantity = line.quantity;
      if (quantity == null || quantity <= 0) {
        problems.add('袋 ${line.label} 的数量要大于 0。');
        continue;
      }
      if (line.exceedsAvailable) {
        problems.add('袋 ${line.label} 只有 ${line.availableLabel}，不能领用 '
            '${quantity == quantity.roundToDouble() ? quantity.toInt() : quantity}。');
        continue;
      }
      lines.add((bagId: line.bagId, quantity: quantity));
    }
    if (lines.isEmpty) problems.add('请至少选择一个来源袋并填写数量。');
    final borrowerId = state.borrowerId;
    if (borrowerId == null) problems.add('请选择领用人（必须是已建立的系统账号）。');
    if (state.project.trim().isEmpty) problems.add('请填写项目。');

    if (problems.isNotEmpty) {
      state = state.copyWith(error: problems.join('\n'));
      return false;
    }

    final total = state.totalQuantity;
    final project = state.project.trim();
    state = state.copyWith(submitting: true, error: null, notice: null);

    try {
      final result = await _api.issue(
        requestKey: state.requestKey,
        borrowerId: borrowerId!,
        project: project,
        lines: lines,
        note: state.note.trim(),
      );

      state = state.copyWith(
        submitting: false,
        succeeded: true,
        result: result,
        notice: '领料成功：$total 件，项目「$project」。'
            '操作人由服务器按当前登录账号记录。',
        requestKey: _newRequestKey(),
      );
      _onInventoryChanged?.call(result.inventoryRevision);
      return true;
    } on LabApiException catch (error) {
      state = state.copyWith(
        submitting: false,
        error: error.message,
        errorCode: error.code,
      );
      return false;
    } catch (error) {
      state = state.copyWith(submitting: false, error: describeLabError(error));
      return false;
    }
  }

  void reset() {
    state = IssueFormState(requestKey: _newRequestKey());
  }
}

// -----------------------------------------------------------------------------
// Return (归还): against the ORIGINAL issue line, never above its outstanding
// -----------------------------------------------------------------------------

/// Form + submission state of one return.
class ReturnFormState {
  const ReturnFormState({
    this.issues = const <IssueRecord>[],
    this.loadingIssues = false,
    this.issuesError,
    this.outstandingOnly = true,
    this.selectedIssue,
    this.selectedLine,
    this.quantityText = '',
    this.note = '',
    this.submitting = false,
    this.error,
    this.errorCode,
    this.notice,
    this.result,
    this.succeeded = false,
    required this.requestKey,
  });

  final List<IssueRecord> issues;
  final bool loadingIssues;
  final String? issuesError;
  final bool outstandingOnly;
  final IssueRecord? selectedIssue;
  final IssueLineRecord? selectedLine;
  final String quantityText;
  final String note;
  final bool submitting;
  final String? error;
  final String? errorCode;
  final String? notice;
  final ReturnResult? result;
  final bool succeeded;
  final String requestKey;

  double? get quantity => double.tryParse(quantityText.trim());

  /// Unreturned quantity of the selected line: the upper bound of this return.
  double get outstanding => selectedLine?.outstanding ?? 0;

  bool get isBusy => submitting || loadingIssues;

  bool get canSubmit =>
      !isBusy && selectedLine != null && (quantity ?? 0) > 0 && (quantity ?? 0) <= outstanding + 0.000001;

  ReturnFormState copyWith({
    List<IssueRecord>? issues,
    bool? loadingIssues,
    Object? issuesError = _unset,
    bool? outstandingOnly,
    Object? selectedIssue = _unset,
    Object? selectedLine = _unset,
    String? quantityText,
    String? note,
    bool? submitting,
    Object? error = _unset,
    Object? errorCode = _unset,
    Object? notice = _unset,
    Object? result = _unset,
    bool? succeeded,
    String? requestKey,
  }) {
    return ReturnFormState(
      issues: issues ?? this.issues,
      loadingIssues: loadingIssues ?? this.loadingIssues,
      issuesError:
          identical(issuesError, _unset) ? this.issuesError : issuesError as String?,
      outstandingOnly: outstandingOnly ?? this.outstandingOnly,
      selectedIssue: identical(selectedIssue, _unset)
          ? this.selectedIssue
          : selectedIssue as IssueRecord?,
      selectedLine:
          identical(selectedLine, _unset) ? this.selectedLine : selectedLine as IssueLineRecord?,
      quantityText: quantityText ?? this.quantityText,
      note: note ?? this.note,
      submitting: submitting ?? this.submitting,
      error: identical(error, _unset) ? this.error : error as String?,
      errorCode: identical(errorCode, _unset) ? this.errorCode : errorCode as String?,
      notice: identical(notice, _unset) ? this.notice : notice as String?,
      result: identical(result, _unset) ? this.result : result as ReturnResult?,
      succeeded: succeeded ?? this.succeeded,
      requestKey: requestKey ?? this.requestKey,
    );
  }

  static const Object _unset = Object();
}

/// Drives the return flow.
///
/// The operator must pick an EXISTING issue record and one of its lines; the
/// quantity is capped by that line's outstanding amount. The server re-checks
/// the bound and defaults the destination back to the original bag/location -
/// the client never chooses a different destination on its own.
class ReturnController extends StateNotifier<ReturnFormState> {
  ReturnController({
    required LabApiClient api,
    required String Function() newRequestKey,
    void Function(String inventoryRevision)? onInventoryChanged,
  })  : _api = api,
        _newRequestKey = newRequestKey,
        _onInventoryChanged = onInventoryChanged,
        super(ReturnFormState(requestKey: newRequestKey()));

  final LabApiClient _api;
  final String Function() _newRequestKey;
  final void Function(String inventoryRevision)? _onInventoryChanged;

  /// Loads the returns candidates.
  Future<void> loadIssues({String query = '', bool? outstandingOnly}) async {
    final only = outstandingOnly ?? state.outstandingOnly;
    state = state.copyWith(
      loadingIssues: true,
      issuesError: null,
      outstandingOnly: only,
    );
    try {
      final page = await _api.issues(query: query, outstandingOnly: only);
      state = state.copyWith(
        issues: page.issues,
        loadingIssues: false,
        issuesError: null,
      );
    } catch (error) {
      state = state.copyWith(
        loadingIssues: false,
        issues: const <IssueRecord>[],
        issuesError: describeLabError(error),
      );
    }
  }

  void selectIssue(IssueRecord? issue) {
    state = state.copyWith(
      selectedIssue: issue,
      selectedLine: issue != null && issue.lines.length == 1 ? issue.lines.first : null,
      error: null,
      notice: null,
      succeeded: false,
    );
  }

  void selectLine(IssueLineRecord? line) {
    state = state.copyWith(selectedLine: line, error: null);
  }

  void setQuantity(String value) => state = state.copyWith(quantityText: value, error: null);

  void setNote(String value) => state = state.copyWith(note: value);

  /// Confirms the return. Only a `true` result means stock came back.
  Future<bool> submit() async {
    if (state.submitting) return false;

    final line = state.selectedLine;
    final problems = <String>[];
    if (line == null) problems.add('请选择原领料记录中的一行。');
    final quantity = state.quantity;
    if (quantity == null || quantity <= 0) {
      problems.add('请输入大于 0 的归还数量。');
    } else if (line != null && quantity > line.outstanding + 0.000001) {
      problems.add(
        '归还数量不能超过尚未归还数量 ${_format(line.outstanding)}。',
      );
    }
    if (problems.isNotEmpty) {
      state = state.copyWith(error: problems.join('\n'));
      return false;
    }

    state = state.copyWith(submitting: true, error: null, notice: null);
    try {
      final result = await _api.returnQuantity(
        requestKey: state.requestKey,
        issueLineId: line!.id!,
        quantity: quantity!,
        note: state.note.trim(),
      );

      final remaining = result.outstandingQuantity ?? (line.outstanding - quantity);
      state = state.copyWith(
        submitting: false,
        succeeded: true,
        result: result,
        notice: '归还成功：${_format(quantity)} 件，该行尚未归还 ${_format(remaining <= 0 ? 0 : remaining)}。',
        requestKey: _newRequestKey(),
      );
      _onInventoryChanged?.call(result.inventoryRevision);
      // Reload the candidate list so the outstanding figure is fresh.
      unawaited(loadIssues());
      return true;
    } on LabApiException catch (error) {
      state = state.copyWith(
        submitting: false,
        error: error.message,
        errorCode: error.code,
      );
      return false;
    } catch (error) {
      state = state.copyWith(submitting: false, error: describeLabError(error));
      return false;
    }
  }

  void reset() {
    state = ReturnFormState(requestKey: _newRequestKey());
  }

  static String _format(double value) {
    if (value == value.roundToDouble()) return value.toInt().toString();
    return value.toStringAsFixed(2);
  }
}

// -----------------------------------------------------------------------------
// History (历史追溯)
// -----------------------------------------------------------------------------

/// Paged state of the immutable operation feed.
class HistoryState {
  const HistoryState({
    this.operations = const <LabOperation>[],
    this.nextCursor,
    this.loading = false,
    this.loadingMore = false,
    this.error,
    this.errorCode,
    this.itemKey,
    this.bagId,
  });

  final List<LabOperation> operations;
  final String? nextCursor;
  final bool loading;
  final bool loadingMore;
  final String? error;
  final String? errorCode;
  final String? itemKey;
  final int? bagId;

  bool get hasMore => nextCursor != null && nextCursor!.isNotEmpty;

  bool get isEmpty => operations.isEmpty && !loading && error == null;

  HistoryState copyWith({
    List<LabOperation>? operations,
    Object? nextCursor = _unset,
    bool? loading,
    bool? loadingMore,
    Object? error = _unset,
    Object? errorCode = _unset,
    Object? itemKey = _unset,
    Object? bagId = _unset,
  }) {
    return HistoryState(
      operations: operations ?? this.operations,
      nextCursor:
          identical(nextCursor, _unset) ? this.nextCursor : nextCursor as String?,
      loading: loading ?? this.loading,
      loadingMore: loadingMore ?? this.loadingMore,
      error: identical(error, _unset) ? this.error : error as String?,
      errorCode: identical(errorCode, _unset) ? this.errorCode : errorCode as String?,
      itemKey: identical(itemKey, _unset) ? this.itemKey : itemKey as String?,
      bagId: identical(bagId, _unset) ? this.bagId : bagId as int?,
    );
  }

  static const Object _unset = Object();
}

/// Paged history with optional item / bag filters.
class HistoryNotifier extends StateNotifier<HistoryState> {
  HistoryNotifier({
    required LabApiClient api,
    String? itemKey,
    int? bagId,
    int pageSize = LabApiClient.defaultPageSize,
  })  : _api = api,
        _pageSize = pageSize.clamp(1, LabApiClient.maxPageSize),
        super(HistoryState(itemKey: itemKey, bagId: bagId));

  final LabApiClient _api;
  final int _pageSize;

  Future<void> setFilters({String? itemKey, int? bagId}) async {
    state = state.copyWith(
      itemKey: itemKey,
      bagId: bagId,
      operations: const <LabOperation>[],
      nextCursor: null,
      loading: true,
      error: null,
    );
    await _loadFirstPage();
  }

  Future<void> refresh() async {
    state = state.copyWith(
      operations: const <LabOperation>[],
      nextCursor: null,
      loading: true,
      error: null,
    );
    await _loadFirstPage();
  }

  Future<void> _loadFirstPage() async {
    try {
      final page = await _api.history(
        itemKey: state.itemKey,
        bagId: state.bagId,
        limit: _pageSize,
      );
      state = state.copyWith(
        operations: page.operations,
        nextCursor: page.nextCursor,
        loading: false,
        loadingMore: false,
        error: null,
        errorCode: null,
      );
    } catch (error) {
      state = state.copyWith(
        loading: false,
        loadingMore: false,
        operations: const <LabOperation>[],
        error: describeLabError(error),
        errorCode: error is LabApiException ? error.code : null,
      );
    }
  }

  Future<void> loadMore() async {
    if (state.loading || state.loadingMore || !state.hasMore) return;
    state = state.copyWith(loadingMore: true, error: null);
    try {
      final page = await _api.history(
        itemKey: state.itemKey,
        bagId: state.bagId,
        cursor: state.nextCursor,
        limit: _pageSize,
      );
      state = state.copyWith(
        operations: <LabOperation>[...state.operations, ...page.operations],
        nextCursor: page.nextCursor,
        loadingMore: false,
      );
    } catch (error) {
      state = state.copyWith(loadingMore: false, error: describeLabError(error));
    }
  }
}

/// Creates a new internal location (库位) with its own 库码.
class LocationCreateState {
  const LocationCreateState({
    this.submitting = false,
    this.error,
    this.created,
  });

  final bool submitting;
  final String? error;
  final LabStockLocation? created;

  LocationCreateState copyWith({
    bool? submitting,
    Object? error = _unset,
    Object? created = _unset,
  }) {
    return LocationCreateState(
      submitting: submitting ?? this.submitting,
      error: identical(error, _unset) ? this.error : error as String?,
      created: identical(created, _unset) ? this.created : created as LabStockLocation?,
    );
  }

  static const Object _unset = Object();
}

class LocationCreateController extends StateNotifier<LocationCreateState> {
  LocationCreateController({
    required LabApiClient api,
    void Function(String inventoryRevision)? onInventoryChanged,
  })  : _api = api,
        _onInventoryChanged = onInventoryChanged,
        super(const LocationCreateState());

  final LabApiClient _api;
  final void Function(String inventoryRevision)? _onInventoryChanged;

  Future<LabStockLocation?> create({required String name, int? parentId}) async {
    final trimmed = name.trim();
    if (trimmed.isEmpty) {
      state = state.copyWith(error: '请输入库位名称。');
      return null;
    }
    state = state.copyWith(submitting: true, error: null);
    try {
      final location = await _api.createLocation(name: trimmed, parentId: parentId);
      state = LocationCreateState(created: location);
      _onInventoryChanged?.call('');
      return location;
    } on LabApiException catch (error) {
      state = state.copyWith(submitting: false, error: error.message);
      return null;
    } catch (error) {
      state = state.copyWith(submitting: false, error: describeLabError(error));
      return null;
    }
  }
}

// -----------------------------------------------------------------------------
// Wiring
// -----------------------------------------------------------------------------

final receiptControllerProvider =
    StateNotifierProvider<ReceiptController, ReceiptFormState>((ref) {
  // A scope change rebuilds the controller: a new idempotency key, cleared
  // inputs, and no leftover "succeeded" state from the previous session.
  ref.watch(effectiveSessionScopeProvider);
  return ReceiptController(
    api: ref.watch(labApiProvider),
    newRequestKey: ref.watch(requestKeyFactoryProvider),
    onInventoryChanged: (revision) =>
        ref.read(dataRevisionProvider.notifier).bump(inventory: revision),
  );
});

final issueControllerProvider =
    StateNotifierProvider<IssueController, IssueFormState>((ref) {
  ref.watch(effectiveSessionScopeProvider);
  return IssueController(
    api: ref.watch(labApiProvider),
    newRequestKey: ref.watch(requestKeyFactoryProvider),
    onInventoryChanged: (revision) =>
        ref.read(dataRevisionProvider.notifier).bump(inventory: revision),
  );
});

final returnControllerProvider =
    StateNotifierProvider<ReturnController, ReturnFormState>((ref) {
  ref.watch(effectiveSessionScopeProvider);
  return ReturnController(
    api: ref.watch(labApiProvider),
    newRequestKey: ref.watch(requestKeyFactoryProvider),
    onInventoryChanged: (revision) =>
        ref.read(dataRevisionProvider.notifier).bump(inventory: revision),
  );
});

/// History for the whole library, or for one item when opened from its detail.
final historyProvider = StateNotifierProvider.family<HistoryNotifier, HistoryState, String>(
  (ref, scope) {
    ref.watch(effectiveSessionScopeProvider);
    final api = ref.watch(labApiProvider);
    // A write must refresh the trace feed: the operation the operator just
    // performed has to appear without a manual reload.
    final notifier = HistoryNotifier(
      api: api,
      itemKey: scope.isEmpty ? null : scope,
    );
    ref.listen<DataRevision>(dataRevisionProvider, (previous, next) {
      if (previous?.sequence == next.sequence) return;
      unawaited(notifier.refresh());
    });
    return notifier;
  },
);

final locationCreateProvider =
    StateNotifierProvider<LocationCreateController, LocationCreateState>((ref) {
  ref.watch(effectiveSessionScopeProvider);
  return LocationCreateController(
    api: ref.watch(labApiProvider),
    onInventoryChanged: (revision) =>
        ref.read(dataRevisionProvider.notifier).bump(inventory: revision),
  );
});
