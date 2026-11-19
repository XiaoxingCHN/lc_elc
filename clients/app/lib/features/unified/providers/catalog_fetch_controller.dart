import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../models/lab_api_exception.dart';
import '../../../services/lab_api_client.dart';
import '../models/unified_item.dart';
import 'lab_errors.dart';

typedef CatalogFetchListener = void Function(
  bool busy,
  CatalogFetchStatus? status,
);

/// Drives ONE on-demand LCSC fetch and follows it to a terminal state.
///
/// It is deliberately independent of the catalog list so the receipt form and
/// the item detail can start a fetch for THEIR OWN query - the server accepts
/// only one exact C code / MPN per request, so this controller never batches.
///
/// Ownership (audit P2-03 / M2). Every fetch attempt carries a local
/// **generation** and the **server task id** (`request_id`). Each `await`
/// returns into a generation check, so a create/poll response for an attempt
/// that has been superseded can never write its status anywhere. The server
/// task itself is NOT cancelled by a local change of mind: when the operator
/// switches the query or the client stops waiting, the task id is retained in a
/// queryable `still_running` state instead of being dropped or turned into an
/// unqueryable `failed`.
///
/// Rules that matter:
///   * [start] reports `busy` only while the create request itself is in flight;
///   * a non-terminal answer (`queued` / `resolving` / `fetching`) is polled at
///     [pollInterval], at most [maxPolls] times; after that the task id is kept
///     and reported as `still_running` (the server cron may still finish it);
///   * a transport failure while polling keeps the task id and reports
///     `still_running` too - only a real business error is a `failed` status;
///   * [cancel] stops the local subscription only; a queued task id survives;
///   * [resume] asks the server again about a retained task id (an explicit
///     human action - nothing is ever submitted automatically);
///   * [onDone] fires exactly once per successful `done` of the CURRENT attempt,
///     never for other terminal states and never for a superseded attempt;
///   * every failure carries the server's (or the client's) Chinese message - it
///     is never silently swallowed.
class CatalogFetchController extends ChangeNotifier {
  CatalogFetchController({
    required LabApiClient api,
    this.pollInterval = const Duration(seconds: 1),
    this.maxPolls = 60,
    this.onDone,
    this.onChanged,
  }) : _api = api;

  final LabApiClient _api;

  /// How often a queued / running fetch is polled.
  final Duration pollInterval;

  /// Polling stops after this many status calls; the task id is kept.
  final int maxPolls;

  /// Called after a fetch reached `done`; the owner reloads its own data.
  final Future<void> Function()? onDone;

  /// Mirrors [busy] / [status] into an owner that keeps its own state object.
  final CatalogFetchListener? onChanged;

  bool _busy = false;
  CatalogFetchStatus? _status;
  String _query = '';
  Timer? _pollTimer;
  bool _polling = false;
  int _polls = 0;
  bool _disposed = false;

  /// Bumped by every [start], [cancel], [follow] and [resume]. A response is
  /// written only when the generation it was issued for is still the current
  /// one.
  int _generation = 0;

  /// Set when the operator moved on while the CREATE request was in flight.
  ///
  /// Its late answer is still never written as a status, but if it carries a
  /// task id that the server accepted, that id is retained as a queryable
  /// `still_running` status - the backend may still process it.
  bool _adoptLateTask = false;

  /// True while the create request itself is in flight.
  bool get busy => _busy;

  /// The latest status, or `null` when no fetch was started.
  CatalogFetchStatus? get status => _status;

  /// The exact term this controller is fetching (candidate picks reuse it).
  String get query => _query;

  /// The server task id this controller is following, when known.
  int? get requestId => _status?.requestId;

  /// Current ownership generation (exposed for diagnostics and tests).
  int get generation => _generation;

  /// True while a poll subscription is running for the current attempt.
  bool get running => _status?.isActive == true;

  /// True when the server can still be asked about the current task.
  bool get hasQueryableTask => _status?.isQueryable == true;

  @override
  void dispose() {
    _disposed = true;
    _generation++;
    _cancelTimer();
    super.dispose();
  }

  /// Starts (or restarts) one fetch for [query].
  ///
  /// [catalogCode] is passed only after the operator chooses among the server's
  /// candidates. [refresh] asks the server to re-fetch a code the library
  /// already has; it is always a single code, never a list.
  Future<void> start({
    required String query,
    String? catalogCode,
    bool refresh = false,
  }) async {
    final text = query.trim();
    if (text.isEmpty || _disposed) return;
    final generation = ++_generation;
    _adoptLateTask = false;
    _query = text;
    _cancelTimer();
    _emit(busy: true, status: null);
    try {
      final status = await _api.requestCatalogFetch(
        text,
        catalogCode: catalogCode,
        refresh: refresh,
      );
      if (_disposed) return;
      if (!_isCurrent(generation)) {
        _adoptLateCreate(status, text);
        return;
      }
      _adoptLateTask = false;
      if (!status.isTerminal && status.requestId == null) {
        // The server accepted the task but did not return its id: keep the
        // status, but do not pretend to follow it.
        _emit(
          busy: false,
          status: status.copyWith(
            state: CatalogFetchStatus.stillRunningState,
            message: '服务器已接收抓取任务，但没有返回任务号；'
                '可稍后重新检索，或重新发起抓取。',
          ),
        );
        return;
      }
      _emit(busy: false, status: status);
      if (status.isDone) {
        await onDone?.call();
      } else if (status.isQueryable) {
        _startPolling(generation, status.requestId!);
      }
    } on LabApiException catch (error) {
      if (!_isCurrent(generation)) return;
      _emit(busy: false, status: _failedStatus(text, error.message));
    } catch (error) {
      if (!_isCurrent(generation)) return;
      _emit(busy: false, status: _failedStatus(text, '$error'));
    }
  }

  /// Re-submits a "multiple candidates" result with the operator's choice.
  Future<void> chooseCandidate(CatalogFetchCandidate candidate) {
    if (candidate.catalogCode.isEmpty) return Future<void>.value();
    return start(query: _query, catalogCode: candidate.catalogCode);
  }

  /// Stops the local subscription without touching the server task.
  ///
  /// A create request in flight is abandoned (its answer is dropped by the
  /// generation check). A queued / running task keeps its request id in a
  /// `still_running` status so the operator can ask about it later; only a
  /// settled (terminal) status is cleared, because it belongs to the query the
  /// operator just left.
  void cancel() {
    _generation++;
    _cancelTimer();
    if (_disposed) return;
    final current = _status;
    if (current == null) {
      // The create answer is still in flight: never write it as a status, but
      // adopt the task id it may carry (see [_adoptLateCreate]). A second
      // cancel while it is still in flight must not clear that intent.
      if (_busy) {
        _adoptLateTask = true;
        _emit(busy: false, status: null);
      }
      return;
    }
    if (current.isTerminal) {
      _emit(busy: false, status: null);
      return;
    }
    final requestId = current.requestId;
    _emit(
      busy: false,
      status: current.copyWith(
        state: CatalogFetchStatus.stillRunningState,
        message: requestId == null
            ? '已切换查询；抓取任务仍在后台处理，可稍后重新检索。'
            : '已切换查询；抓取任务 $requestId 仍在后台处理，可稍后重新查询结果。',
      ),
    );
  }

  /// Asks the server about the current task id again.
  ///
  /// This is an explicit human action: it never submits a new fetch and never
  /// writes anything. A no-op when there is no queryable task.
  Future<void> resume() async {
    final current = _status;
    if (_disposed || current == null) return;
    final requestId = current.requestId;
    if (requestId == null || current.isTerminal) return;
    await follow(requestId: requestId, query: current.query);
  }

  /// Follows a known server task without submitting anything.
  ///
  /// Used after a query switch: the old task id survives locally, and this is
  /// how the operator asks about it again. It replaces the controller's current
  /// status, so callers must not use it to clobber an active subscription.
  Future<void> follow({
    required int requestId,
    required String query,
  }) async {
    if (_disposed) return;
    final generation = ++_generation;
    _adoptLateTask = false;
    _cancelTimer();
    _query = query.trim();
    _emit(
      busy: false,
      status: CatalogFetchStatus(
        requestId: requestId,
        state: 'queued',
        query: _query,
        queryKind: '',
        catalogCode: '',
        itemKey: '',
        message: '正在向服务器重新查询任务 $requestId…',
        candidates: const <CatalogFetchCandidate>[],
      ),
    );
    await _poll(generation, requestId);
    if (!_isCurrent(generation) || _status?.requestId != requestId) return;
    if (_status?.isActive == true) _startPolling(generation, requestId);
  }

  void _startPolling(int generation, int requestId) {
    _cancelTimer();
    _pollTimer = Timer.periodic(pollInterval, (timer) {
      unawaited(_poll(generation, requestId));
    });
  }

  Future<void> _poll(int generation, int requestId) async {
    if (_disposed || generation != _generation) return;
    if (_polling) return;
    final current = _status;
    if (current == null ||
        current.requestId != requestId ||
        !current.isActive) {
      _cancelTimer();
      return;
    }
    if (_polls >= maxPolls) {
      _stopWaiting(current);
      return;
    }
    _polling = true;
    _polls++;
    try {
      final status = await _api.catalogFetchStatus(requestId);
      if (!_isCurrent(generation) || _status?.requestId != requestId) return;
      _emit(busy: false, status: status);
      if (status.isDone) {
        _cancelTimer();
        await onDone?.call();
      } else if (status.isTerminal) {
        _cancelTimer();
      }
    } on LabApiException catch (error) {
      if (!_isCurrent(generation) || _status?.requestId != requestId) return;
      _cancelTimer();
      if (isOfflineFailure(error)) {
        _emit(
          busy: false,
          status: current.copyWith(
            state: CatalogFetchStatus.stillRunningState,
            message: '与服务器连接中断；抓取任务 $requestId 仍在后台，'
                '网络恢复后可重新查询。',
          ),
        );
      } else {
        // A real business answer about this task (e.g. it no longer exists).
        _emit(
          busy: false,
          status: current.copyWith(state: 'failed', message: error.message),
        );
      }
    } catch (error) {
      if (!_isCurrent(generation) || _status?.requestId != requestId) return;
      _cancelTimer();
      // An unexpected client-side failure says nothing about the server task.
      _emit(
        busy: false,
        status: current.copyWith(
          state: CatalogFetchStatus.stillRunningState,
          message: '无法读取任务状态（$error）；任务 $requestId 仍在后台，'
              '可稍后重新查询。',
        ),
      );
    } finally {
      if (generation == _generation) _polling = false;
    }
  }

  /// Handles the CREATE answer of an attempt the operator already abandoned.
  ///
  /// The response is never written as the current status. But the server may
  /// have accepted the task, and its cron may still finish it: when the answer
  /// carries a request id, that id is retained in a queryable `still_running`
  /// status so it is not silently lost. An answer without an id changes nothing.
  void _adoptLateCreate(CatalogFetchStatus late, String text) {
    if (!_adoptLateTask) return;
    _adoptLateTask = false;
    final requestId = late.requestId;
    if (requestId == null) return;
    final current = _status;
    if (current != null && current.requestId == requestId) return;
    _emit(
      busy: false,
      status: CatalogFetchStatus(
        requestId: requestId,
        state: CatalogFetchStatus.stillRunningState,
        query: late.query.isEmpty ? text : late.query,
        queryKind: late.queryKind,
        catalogCode: late.catalogCode,
        itemKey: late.itemKey,
        message: '抓取任务 $requestId 已提交到服务器，仍在后台处理；'
            '可稍后重新查询结果。',
        candidates: const <CatalogFetchCandidate>[],
      ),
    );
  }

  /// Stops waiting for a task the server has not finished yet.
  ///
  /// The task id and its last known server state are kept: the backend cron may
  /// still complete the fetch, so calling this "failed" would be wrong.
  void _stopWaiting(CatalogFetchStatus current) {
    _cancelTimer();
    final task = current.requestId == null ? '' : '（任务号 ${current.requestId}）';
    _emit(
      busy: false,
      status: current.copyWith(
        state: CatalogFetchStatus.stillRunningState,
        message: '已等待较长时间，抓取任务$task仍在后台处理；'
            '可稍后重新查询，或重新检索该器件。',
      ),
    );
  }

  bool _isCurrent(int generation) => !_disposed && generation == _generation;

  void _cancelTimer() {
    _pollTimer?.cancel();
    _pollTimer = null;
    _polling = false;
    _polls = 0;
  }

  void _emit({required bool busy, required CatalogFetchStatus? status}) {
    if (_disposed) return;
    _busy = busy;
    _status = status;
    onChanged?.call(busy, status);
    notifyListeners();
  }

  static CatalogFetchStatus _failedStatus(String query, String message) {
    return CatalogFetchStatus(
      requestId: null,
      state: 'failed',
      query: query,
      queryKind: '',
      catalogCode: '',
      itemKey: '',
      message: message,
      candidates: const <CatalogFetchCandidate>[],
    );
  }
}
