import 'dart:async';

import 'package:flutter/foundation.dart';

import '../../../models/lab_api_exception.dart';
import '../../../services/lab_api_client.dart';
import '../models/unified_item.dart';

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
/// Rules that matter:
///   * [start] reports `busy` only while the create request itself is in flight;
///   * a non-terminal answer (`queued` / `resolving` / `fetching`) is polled at
///     [pollInterval], at most [maxPolls] times, then reported as a timeout;
///   * [onDone] fires exactly once per successful `done`, never for other
///     terminal states;
///   * a transport failure becomes a `failed` status carrying the server's (or
///     the client's) Chinese message - it is never silently swallowed.
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

  /// Polling stops (and reports a timeout) after this many status calls.
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

  /// True while the create request itself is in flight.
  bool get busy => _busy;

  /// The latest status, or `null` when no fetch was started.
  CatalogFetchStatus? get status => _status;

  /// The exact term this controller is fetching (candidate picks reuse it).
  String get query => _query;

  bool get running => _status != null && !_status!.isTerminal;

  @override
  void dispose() {
    _disposed = true;
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
    _query = text;
    _cancelTimer();
    _polls = 0;
    _emit(busy: true, status: null);
    try {
      final status = await _api.requestCatalogFetch(
        text,
        catalogCode: catalogCode,
        refresh: refresh,
      );
      if (_disposed) return;
      _emit(busy: false, status: status);
      if (status.isDone) {
        await onDone?.call();
      } else if (!status.isTerminal) {
        _startPolling();
      }
    } on LabApiException catch (error) {
      if (_disposed) return;
      _emit(busy: false, status: _failedStatus(text, error.message));
    } catch (error) {
      if (_disposed) return;
      _emit(busy: false, status: _failedStatus(text, '$error'));
    }
  }

  /// Re-submits a "multiple candidates" result with the operator's choice.
  Future<void> chooseCandidate(CatalogFetchCandidate candidate) {
    if (candidate.catalogCode.isEmpty) return Future<void>.value();
    return start(query: _query, catalogCode: candidate.catalogCode);
  }

  /// Drops the timer and any displayed status (the owner moved on).
  void cancel() {
    _cancelTimer();
    if (_disposed) return;
    if (_busy || _status != null) _emit(busy: false, status: null);
  }

  void _startPolling() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(pollInterval, (timer) {
      unawaited(_poll(timer));
    });
  }

  Future<void> _poll(Timer timer) async {
    if (_polling) return;
    final current = _status;
    final requestId = current?.requestId;
    if (current == null || requestId == null) {
      timer.cancel();
      return;
    }
    if (_polls >= maxPolls) {
      timer.cancel();
      _emit(
        busy: false,
        status: _failedStatus(current.query, '抓取超时，请稍后重试。'),
      );
      return;
    }
    _polling = true;
    _polls++;
    try {
      final status = await _api.catalogFetchStatus(requestId);
      if (_disposed) {
        timer.cancel();
        return;
      }
      _emit(busy: false, status: status);
      if (status.isDone) {
        timer.cancel();
        await onDone?.call();
      } else if (status.isTerminal) {
        timer.cancel();
      }
    } on LabApiException catch (error) {
      timer.cancel();
      if (_disposed) return;
      _emit(busy: false, status: _failedStatus(current.query, error.message));
    } catch (error) {
      timer.cancel();
      if (_disposed) return;
      _emit(busy: false, status: _failedStatus(current.query, '$error'));
    } finally {
      _polling = false;
    }
  }

  void _cancelTimer() {
    _pollTimer?.cancel();
    _pollTimer = null;
    _polling = false;
    _polls = 0;
  }

  void _emit({required bool busy, required CatalogFetchStatus? status}) {
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
