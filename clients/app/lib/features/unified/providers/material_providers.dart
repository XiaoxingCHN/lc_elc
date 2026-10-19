import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../models/lab_api_exception.dart';
import '../../../services/lab_api_client.dart';
import '../models/inventory.dart';
import 'inventory_providers.dart';
import 'unified_providers.dart';

/// State of the two catalog write actions available on a catalog-only card.
class MaterialActionState {
  const MaterialActionState({
    this.running = false,
    this.error,
    this.notice,
    this.created,
    this.bound,
  });

  /// True while `create_material` or `bind` is running.
  final bool running;
  final String? error;
  final String? notice;

  /// Result of `create_material` (a real local archive + its server-made SN).
  final CreateMaterialResult? created;

  /// Result of `bind`.
  final BindResult? bound;

  MaterialActionState copyWith({
    bool? running,
    Object? error = _unset,
    Object? notice = _unset,
    Object? created = _unset,
    Object? bound = _unset,
  }) {
    return MaterialActionState(
      running: running ?? this.running,
      error: identical(error, _unset) ? this.error : error as String?,
      notice: identical(notice, _unset) ? this.notice : notice as String?,
      created: identical(created, _unset) ? this.created : created as CreateMaterialResult?,
      bound: identical(bound, _unset) ? this.bound : bound as BindResult?,
    );
  }

  static const Object _unset = Object();
}

/// Creates a local archive for a captured catalog row, or binds it to an
/// existing `product.template`.
///
/// Both calls are contract endpoints (`/lab/api/catalog/create_material`,
/// `/lab/api/catalog/bind`). They create/link a local ARCHIVE - they do not
/// change stock, and this client never invents the SN: the server returns it.
class MaterialActionController extends StateNotifier<MaterialActionState> {
  MaterialActionController({
    required LabApiClient api,
    void Function(String inventoryRevision)? onDataChanged,
  })  : _api = api,
        _onDataChanged = onDataChanged,
        super(const MaterialActionState());

  final LabApiClient _api;
  final void Function(String inventoryRevision)? _onDataChanged;

  Future<bool> createMaterial(String itemKey) async {
    if (state.running) return false;
    state = state.copyWith(running: true, error: null, notice: null);
    try {
      final result = await _api.createMaterial(itemKey);
      state = MaterialActionState(
        created: result,
        notice: result.sn.isEmpty
            ? '已创建本地物料档案（服务端未返回 SN，请在详情中确认）。'
            : '已创建本地物料档案：SN ${result.sn}。',
      );
      _onDataChanged?.call('');
      return true;
    } on LabApiException catch (error) {
      state = state.copyWith(running: false, error: error.message);
      return false;
    } catch (error) {
      state = state.copyWith(running: false, error: describeLabError(error));
      return false;
    }
  }

  Future<bool> bind({
    required int productTemplateId,
    required String catalogCode,
  }) async {
    if (state.running) return false;
    if (productTemplateId <= 0) {
      state = state.copyWith(error: '请输入有效的本地档案 ID（product.template）。');
      return false;
    }
    if (catalogCode.trim().isEmpty) {
      state = state.copyWith(error: '该器件没有可绑定的立创编号。');
      return false;
    }
    state = state.copyWith(running: true, error: null, notice: null);
    try {
      final result = await _api.bind(
        productTemplateId: productTemplateId,
        catalogCode: catalogCode.trim(),
      );
      state = MaterialActionState(
        bound: result,
        notice: '已绑定本地档案 #$productTemplateId 到 ${result.itemKey}。',
      );
      _onDataChanged?.call('');
      return true;
    } on LabApiException catch (error) {
      state = state.copyWith(running: false, error: error.message);
      return false;
    } catch (error) {
      state = state.copyWith(running: false, error: describeLabError(error));
      return false;
    }
  }

  void clearMessages() {
    state = state.copyWith(error: null, notice: null);
  }
}

final materialActionProvider =
    StateNotifierProvider<MaterialActionController, MaterialActionState>((ref) {
  ref.watch(effectiveSessionScopeProvider);
  return MaterialActionController(
    api: ref.watch(labApiProvider),
    onDataChanged: (revision) =>
        ref.read(dataRevisionProvider.notifier).bump(catalog: revision),
  );
});
