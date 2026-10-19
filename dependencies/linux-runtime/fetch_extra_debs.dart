// Fetch the EXTRA Ubuntu 22.04 .debs needed by the new Flutter client plugins,
// on top of the closure that lc_elc/dependencies/linux-runtime already ships.
//
// Why a separate tool: the existing apt closure (161 debs) predates
// flutter_secure_storage / printing, so it has no libsecret and no CUPS.
// Re-running the original downloader would work only on a machine with apt and
// network; this tool talks to archive.ubuntu.com over Dart's own HTTPS stack and
// resolves the dependency closure locally from the official Packages indexes.
//
// Usage (run from anywhere; --packages points at the client project so
// package:crypto resolves; add --components universe only if a package needs it):
//   dart --packages=<project>/.dart_tool/package_config.json \
//     fetch_extra_debs.dart --list libsecret-1-0,libcups2 [--optional gnome-keyring] [--dry-run]
//
// Output:
//   <out>/debs/<name>_<version>_<arch>.deb     (only the missing ones)
//   <out>/INCREMENT-<tag>.txt                  (name version arch sha256 url-path)
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';

const String _archive = 'https://archive.ubuntu.com/ubuntu';

/// Suite priority: later entries win when the same package exists in several
/// suites, which mirrors what apt would install on a jammy machine.
const List<String> _defaultSuites = <String>[
  'jammy',
  'jammy-updates',
  'jammy-backports',
  'jammy-security',
];

class Deb {
  Deb({
    required this.name,
    required this.version,
    required this.arch,
    required this.filename,
    required this.sha256,
    required this.depends,
    required this.provides,
    required this.priority,
    required this.suite,
  });

  final String name;
  final String version;
  final String arch;
  final String filename;
  final String sha256;
  final List<String> depends;
  final List<String> provides;
  final String priority;
  final String suite;

  bool get isOptionalPriority => priority == 'optional' || priority == 'extra';
}

Future<void> main(List<String> args) async {
  final scriptDir = File.fromUri(Platform.script).parent;
  final outDir = Directory('${scriptDir.path}${Platform.pathSeparator}out');
  final debDir = Directory('${outDir.path}${Platform.pathSeparator}debs');

  final required = <String>[];
  final optional = <String>[];
  final components = <String>['main'];
  var dryRun = false;

  for (var i = 0; i < args.length; i++) {
    final arg = args[i];
    if (arg == '--dry-run') {
      dryRun = true;
    } else if (arg == '--list' && i + 1 < args.length) {
      required.addAll(_split(args[++i]));
    } else if (arg == '--optional' && i + 1 < args.length) {
      optional.addAll(_split(args[++i]));
    } else if (arg == '--components' && i + 1 < args.length) {
      components
        ..clear()
        ..addAll(_split(args[++i]));
    } else if (!arg.startsWith('--')) {
      required.addAll(_split(arg));
    }
  }

  if (required.isEmpty && optional.isEmpty) {
    stderr.writeln(
        'usage: fetch_extra_debs.dart --list pkg1,pkg2 [--optional pkg3] [--components main] [--dry-run]');
    exit(64);
  }
  if (!debDir.existsSync()) {
    stderr.writeln('missing base deb directory: ${debDir.path}');
    exit(66);
  }

  final present = _presentDebs(debDir);
  stdout.writeln('base closure: ${present.length} debs already in ${debDir.path}');

  final index = await _loadPackages(components);
  stdout.writeln('apt index: ${index.length} package stanzas loaded');

  final plan = <String, Deb>{};
  final unresolved = <String, String>{};

  for (final name in required) {
    _resolve(name, index, plan, unresolved, required: true);
  }
  for (final name in optional) {
    _resolve(name, index, plan, unresolved, required: false);
  }

  final missing = <String, Deb>{};
  for (final entry in plan.entries) {
    if (!present.contains(_debFileName(entry.value))) {
      missing[entry.key] = entry.value;
    }
  }

  stdout.writeln('closure resolved: ${plan.length} packages, of which ${missing.length} are new');
  if (unresolved.isNotEmpty) {
    stdout.writeln('UNRESOLVED (not in the official index, check name/arch):');
    unresolved.forEach((k, v) => stdout.writeln('  $k ($v)'));
  }

  final tag = _stamp();
  if (dryRun) {
    missing.values
        .toList()
      ..sort((a, b) => a.name.compareTo(b.name))
      ..forEach((d) => stdout.writeln('  would fetch ${d.name} ${d.version} ${d.arch} <- ${d.filename}'));
    stdout.writeln('dry run: nothing downloaded');
    return;
  }

  final manifest = StringBuffer();
  var fetched = 0;
  var bytes = 0;
  final sorted = missing.values.toList()..sort((a, b) => a.name.compareTo(b.name));

  for (final deb in sorted) {
    final target = File('${debDir.path}${Platform.pathSeparator}${_debFileName(deb)}');
    if (target.existsSync() && target.lengthSync() > 0) {
      manifest.writeln('${deb.name}\t${deb.version}\t${deb.arch}\t(already present)');
      continue;
    }
    final data = await _httpGet('$_archive/${deb.filename}');
    target.writeAsBytesSync(data);
    final sha = _sha256Hex(data);
    if (deb.sha256.isNotEmpty && sha != deb.sha256) {
      stderr.writeln('CHECKSUM MISMATCH for ${deb.name}: index=${deb.sha256} got=$sha');
      target.deleteSync();
      exit(65);
    }
    bytes += data.length;
    fetched++;
    manifest.writeln('${deb.name}\t${deb.version}\t${deb.arch}\t$sha\t${deb.filename}');
    stdout.writeln('  + ${deb.name} ${deb.version} ${deb.arch} (${data.length} bytes)');
  }

  final manifestFile = File('${outDir.path}${Platform.pathSeparator}INCREMENT-$tag.txt');
  manifestFile.writeAsStringSync(
    '# extra debs for "remember login" (libsecret) + label printing (CUPS)\n'
    '# name\tversion\tarch\tsha256\turl-path\n'
    '${manifest.toString()}',
  );

  stdout.writeln('fetched $fetched new debs (${(bytes / 1024 / 1024).toStringAsFixed(2)} MiB)');
  stdout.writeln('manifest: ${manifestFile.path}');
}

List<String> _split(String value) => value
    .split(',')
    .map((e) => e.trim())
    .where((e) => e.isNotEmpty)
    .toList();

/// apt's on-disk name for a package: the epoch colon is percent-encoded,
/// because ':' is not a legal character in a Windows file name either.
String _debFileName(Deb deb) =>
    '${deb.name}_${deb.version.replaceAll(':', '%3a')}_${deb.arch}.deb';

String _stamp() {
  final now = DateTime.now();
  String two(int v) => v.toString().padLeft(2, '0');
  return '${now.year}${two(now.month)}${two(now.day)}-${two(now.hour)}${two(now.minute)}';
}

/// Existing *.deb file names, which are exactly the base closure.
Set<String> _presentDebs(Directory dir) {
  final result = <String>{};
  for (final entity in dir.listSync()) {
    if (entity is! File) continue;
    final name = entity.uri.pathSegments.last;
    if (name.endsWith('.deb')) result.add(name);
  }
  return result;
}

Future<List<Deb>> _loadPackages(List<String> components) async {
  final byName = <String, Deb>{};
  final provides = <String, String>{};

  for (final suite in _defaultSuites) {
    for (final component in components) {
      final url = '$_archive/dists/$suite/$component/binary-amd64/Packages.gz';
      List<int> raw;
      try {
        raw = await _httpGet(url);
      } catch (e) {
        stdout.writeln('  index skipped: $url ($e)');
        continue;
      }
      final text = utf8.decode(gzip.decode(raw));
      var count = 0;
      for (final stanza in text.split('\n\n')) {
        final deb = _parseStanza(stanza, suite);
        if (deb == null) continue;
        count++;
        final existing = byName[deb.name];
        if (existing == null || _compareVersions(deb.version, existing.version) > 0) {
          byName[deb.name] = deb;
        }
        for (final p in deb.provides) {
          provides.putIfAbsent(p, () => deb.name);
        }
      }
      stdout.writeln('  index loaded: $suite/$component ($count stanzas)');
    }
  }

  // Virtual packages resolve through what Provides them.
  for (final entry in provides.entries) {
    byName.putIfAbsent(entry.key, () => byName[entry.value]!);
  }
  return byName.values.toList();
}

Deb? _parseStanza(String stanza, String suite) {
  if (stanza.trim().isEmpty) return null;
  String? name;
  String? version;
  String? arch;
  String? filename;
  String? sha;
  String? priority;
  final depends = <String>[];
  final provides = <String>[];

  for (final line in stanza.split('\n')) {
    if (line.startsWith(' ')) continue; // continuation of Depends etc.
    final idx = line.indexOf(':');
    if (idx <= 0) continue;
    final key = line.substring(0, idx);
    final value = line.substring(idx + 1).trim();
    switch (key) {
      case 'Package':
        name = value;
      case 'Version':
        version = value;
      case 'Architecture':
        arch = value;
      case 'Filename':
        filename = value;
      case 'SHA256':
        sha = value;
      case 'Priority':
        priority = value;
      case 'Depends':
      case 'Pre-Depends':
        depends.addAll(_parseDepends(value));
      case 'Provides':
        provides.addAll(value.split(',').map((e) => e.trim().split(RegExp(r'[\s(]')).first).where((e) => e.isNotEmpty));
    }
  }

  if (name == null || version == null || arch == null || filename == null) return null;
  if (arch != 'amd64' && arch != 'all') return null;

  return Deb(
    name: name,
    version: version,
    arch: arch,
    filename: filename,
    sha256: sha ?? '',
    depends: depends,
    provides: provides,
    priority: priority ?? 'optional',
    suite: suite,
  );
}

/// `a (>= 1) | b, c:any [amd64]` -> ['a', 'c'] (first alternative of each clause).
List<String> _parseDepends(String value) {
  final result = <String>[];
  for (final clause in value.split(',')) {
    for (final alternative in clause.split('|')) {
      var token = alternative.trim();
      if (token.isEmpty) continue;
      token = token.split('[').first.trim(); // drop architecture restriction
      token = token.replaceAll(RegExp(r'\s*\(.*$'), ''); // drop version constraint
      token = token.split(':').first.trim(); // drop :any / :amd64
      if (token.isEmpty) continue;
      result.add(token);
      break; // only the first alternative is needed for a plain offline closure
    }
  }
  return result;
}

void _resolve(
  String name,
  List<Deb> index,
  Map<String, Deb> plan,
  Map<String, String> unresolved, {
  required bool required,
  Set<String>? visiting,
}) {
  if (plan.containsKey(name)) return;
  visiting ??= <String>{};
  if (!visiting.add(name)) return;

  Deb? candidate;
  for (final deb in index) {
    if (deb.name == name) {
      candidate = deb;
      break;
    }
  }
  if (candidate == null) {
    unresolved[name] = required ? 'required' : 'optional';
    return;
  }

  plan[name] = candidate;
  for (final dep in candidate.depends) {
    _resolve(dep, index, plan, unresolved, required: false, visiting: visiting);
  }
  visiting.remove(name);
}

/// Debian version comparison (epoch:upstream-revision), good enough to pick the
/// newest candidate across suites.
int _compareVersions(String a, String b) {
  int epoch(String v) => int.tryParse(v.split(':').first) ?? 0;
  String rest(String v) => v.contains(':') ? v.split(':').sublist(1).join(':') : v;

  final ea = epoch(a);
  final eb = epoch(b);
  if (ea != eb) return ea.compareTo(eb);

  List<String> parts(String v) {
    final r = rest(v);
    final dash = r.lastIndexOf('-');
    return dash == -1 ? <String>[r] : <String>[r.substring(0, dash), r.substring(dash + 1)];
  }

  final pa = parts(a);
  final pb = parts(b);
  for (var i = 0; i < 2; i++) {
    final va = i < pa.length ? pa[i] : '';
    final vb = i < pb.length ? pb[i] : '';
    final cmp = _comparePart(va, vb);
    if (cmp != 0) return cmp;
  }
  return 0;
}

int _comparePart(String a, String b) {
  final ra = RegExp(r'\d+|\D+').allMatches(a).map((m) => m.group(0)!).toList();
  final rb = RegExp(r'\d+|\D+').allMatches(b).map((m) => m.group(0)!).toList();
  final n = ra.length > rb.length ? ra.length : rb.length;
  for (var i = 0; i < n; i++) {
    final x = i < ra.length ? ra[i] : '';
    final y = i < rb.length ? rb[i] : '';
    final nx = int.tryParse(x);
    final ny = int.tryParse(y);
    if (nx != null && ny != null) {
      if (nx != ny) return nx.compareTo(ny);
    } else {
      // '~' sorts before everything, letters sort before non-letters.
      final cx = _weight(x);
      final cy = _weight(y);
      if (cx != cy) return cx.compareTo(cy);
    }
  }
  return 0;
}

int _weight(String value) {
  if (value.isEmpty) return 0;
  if (value == '~') return -1;
  final first = value.codeUnitAt(0);
  final isAlpha = (first >= 65 && first <= 90) || (first >= 97 && first <= 122);
  return isAlpha ? first : first + 256;
}

Future<List<int>> _httpGet(String url) async {
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 20);
  try {
    final request = await client.getUrl(Uri.parse(url));
    final response = await request.close().timeout(const Duration(seconds: 120));
    if (response.statusCode != 200) {
      throw HttpException('HTTP ${response.statusCode} for $url');
    }
    final bytes = <int>[];
    await for (final chunk in response) {
      bytes.addAll(chunk);
    }
    return bytes;
  } finally {
    client.close(force: true);
  }
}

String _sha256Hex(List<int> data) => sha256.convert(data).toString();
