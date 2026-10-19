// DEV-ONLY verification entry point. Not part of the shipped app.
//
// It exists to prove, on a REAL Windows/Linux/Android device, that this project's
// two storage mechanisms actually write and read through the platform
// implementations (Windows DPAPI / Android Keystore / Linux libsecret, plus
// shared_preferences), because that cannot be proven by a unit test: the plugins
// need the engine and the OS key store.
//
// It only ever touches a DUMMY value (`probe-secret-<timestamp>`) and deletes it
// again; it never reads or writes a real account, and it never contacts a server.
//
// Build (Windows, same recipe as the release):
//   set FLUTTER_TARGET=lib/dev/storage_probe.dart
//   lc_elc\build_work\build_windows_release.cmd
// Then run the produced exe; it writes storage_probe_result.json next to the exe
// and exits 0 (all checks passed) or 1 (something failed).
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final results = <String, Object?>{};
  var ok = true;

  void record(String key, Object? value) => results[key] = value;

  // ---- 1. non-secret preferences round trip --------------------------------
  const prefKey = 'lc_probe_key';
  final dummyValue = 'probe-value-${DateTime.now().millisecondsSinceEpoch}';
  try {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(prefKey, dummyValue);
    await prefs.reload();
    final read = (await SharedPreferences.getInstance()).getString(prefKey);
    record('prefs_write_read_ok', read == dummyValue);
    record('prefs_value_matches', read == dummyValue);
    if (read != dummyValue) ok = false;
  } catch (e) {
    ok = false;
    record('prefs_error', '${e.runtimeType}: $e');
  }

  // ---- 2. platform secure store round trip (DUMMY secret only) -------------
  const secretKey = 'lc_probe_secret';
  final dummySecret = 'probe-secret-${DateTime.now().millisecondsSinceEpoch}';
  const storage = FlutterSecureStorage();
  try {
    await storage.write(key: secretKey, value: dummySecret);
    final read = await storage.read(key: secretKey);
    record('secure_write_read_ok', read == dummySecret);
    record('secure_value_matches', read == dummySecret);
    if (read != dummySecret) ok = false;

    await storage.delete(key: secretKey);
    final afterDelete = await storage.read(key: secretKey);
    record('secure_delete_ok', afterDelete == null);
    if (afterDelete != null) ok = false;
  } catch (e) {
    ok = false;
    record('secure_error', '${e.runtimeType}: $e');
  }

  // ---- 3. where the data actually lives (paths only, never contents) -------
  try {
    final exeDir = File(Platform.resolvedExecutable).parent;
    record('executable', Platform.resolvedExecutable);
    record('exe_dir', exeDir.path);
  } catch (e) {
    record('path_error', '$e');
  }

  record('platform', Platform.operatingSystem);
  record('dart_version', Platform.version);
  record('all_ok', ok);
  record('finished_at', DateTime.now().toIso8601String());

  // Write the report next to the executable so the harness can read it without
  // knowing the plugin's storage directory.
  try {
    final exeDir = File(Platform.resolvedExecutable).parent;
    final reportFile = File(p.join(exeDir.path, 'storage_probe_result.json'));
    reportFile.writeAsStringSync(
      const JsonEncoder.withIndent('  ').convert(results),
    );
  } catch (_) {
    // last resort: stdout, which the harness also captures
  }

  stdout.writeln(const JsonEncoder.withIndent('  ').convert(results));
  await stdout.flush();
  exit(ok ? 0 : 1);
}
