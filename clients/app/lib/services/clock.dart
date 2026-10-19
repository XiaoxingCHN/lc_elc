/// Injectable "now".
///
/// The "remember login" rule is a pure function of the last successful server
/// authentication and the current time, so the whole 10-day boundary can be
/// tested without waiting, without touching the machine clock and without a
/// server (see test/services/login_freshness_test.dart).
typedef Clock = DateTime Function();

/// Production clock: the device's local wall clock.
DateTime systemClock() => DateTime.now();
