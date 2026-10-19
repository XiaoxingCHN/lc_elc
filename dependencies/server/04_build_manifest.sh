#!/usr/bin/env bash
#
# 04 — Build the SHA256 manifest and a human-readable status report.
#
# Included in the hash list: debs, odoo tarball, wheelhouses, requirements and
# constraint files.
# Excluded (scratch, not shipped): out/apt/ (isolated apt state + lists),
# *.log, and the manifest artefacts themselves.
#
# Output: out/SHA256SUMS, out/MANIFEST.json, out/REPORT.md

set -euo pipefail
. "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib/common.sh"

require_cmd sha256sum python3 find sort xargs du awk
ensure_dirs

cd "${OUT_DIR}"

# ---------------------------------------------------------------------------
# 1. Hash every shippable file
# ---------------------------------------------------------------------------
run "generate SHA256SUMS" bash -c "
    cd '${OUT_DIR}'
    find . -type f \
        ! -path './apt/*' \
        ! -name 'SHA256SUMS' \
        ! -name 'MANIFEST.json' \
        ! -name 'REPORT.md' \
        ! -name '*.log' \
        -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
"

hashed="$(wc -l < SHA256SUMS | tr -d ' ')"
[ "${hashed}" -gt 0 ] || die "SHA256SUMS is empty"
ok "hashed ${hashed} files"

# ---------------------------------------------------------------------------
# 2. Verify our own manifest immediately (cheap, catches a bad path scheme)
# ---------------------------------------------------------------------------
run "verify SHA256SUMS (sha256sum -c)" sha256sum -c SHA256SUMS --quiet

# ---------------------------------------------------------------------------
# 3. MANIFEST.json
# ---------------------------------------------------------------------------
run "write MANIFEST.json" python3 - "${OUT_DIR}" <<'PY'
import json, os, re, subprocess, sys, datetime

out = sys.argv[1]
os.chdir(out)

sums = {}
with open("SHA256SUMS", encoding="utf-8") as fh:
    for line in fh:
        line = line.rstrip("\n")
        if not line:
            continue
        digest, _, path = line.partition("  ")
        sums[path.lstrip("./")] = digest

def files_matching(pattern):
    rx = re.compile(pattern)
    return sorted(p for p in sums if rx.search(p))

debs = files_matching(r"^debs/.*\.deb$")
wheels_odoo = files_matching(r"^wheelhouse-odoo/.*\.whl$")
wheels_crawler = files_matching(r"^wheelhouse-crawler/.*\.whl$")
sdists_odoo = files_matching(r"^wheelhouse-odoo/.*\.(tar\.gz|zip)$")
sdists_crawler = files_matching(r"^wheelhouse-crawler/.*\.(tar\.gz|zip)$")
odo_tar = files_matching(r"^odoo/odoo-.*\.tar\.gz$")

def total(paths):
    return sum(os.path.getsize(p) for p in paths if os.path.exists(p))

revision = {}
if os.path.exists("odoo/REVISION"):
    for line in open("odoo/REVISION", encoding="utf-8"):
        k, _, v = line.strip().partition("=")
        if k:
            revision[k] = v

skipped = []
for name in ("MISSING-OPTIONAL.txt", "ODOO-SDIST-REMAINING.txt",
             "ODOO-SDIST-BUILD-FAILURES.txt"):
    if os.path.exists(name):
        body = [l.strip() for l in open(name, encoding="utf-8") if l.strip()]
        if body:
            skipped.append({"file": name, "entries": body})

manifest = {
    "generated_at": datetime.datetime.now(datetime.timezone.utc)
                    .strftime("%Y-%m-%dT%H:%M:%SZ"),
    "generated_on_host": "Ubuntu 22.04 (WSL) / python3.10 / amd64",
    "hashed_file_count": len(sums),
    "counts": {
        "debs": len(debs),
        "wheels_odoo": len(wheels_odoo),
        "wheels_crawler": len(wheels_crawler),
        "sdists_odoo": len(sdists_odoo),
        "sdists_crawler": len(sdists_crawler),
        "odoo_tarballs": len(odo_tar),
    },
    "bytes": {
        "debs": total(debs),
        "wheels_odoo": total(wheels_odoo),
        "wheels_crawler": total(wheels_crawler),
        "odoo_tarball": total(odo_tar),
    },
    "odoo_revision": revision,
    "not_included": skipped,
    "notes": [
        "debs/ is the FULL dependency closure resolved with an EMPTY dpkg status,",
        "so it is independent of what was installed on the prep machine.",
        "out/apt/ is scratch (isolated apt state/lists) and is deliberately NOT hashed.",
        "An sdist in a wheelhouse means the offline target must compile it;",
        "see ODOO-SDIST-REMAINING.txt and the -dev packages in debs/.",
    ],
}

with open("MANIFEST.json", "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, ensure_ascii=False)
    fh.write("\n")

c = manifest["counts"]
print(f"debs={c['debs']} wheels_odoo={c['wheels_odoo']} "
      f"wheels_crawler={c['wheels_crawler']} sdists_odoo={c['sdists_odoo']} "
      f"odoo_tarballs={c['odoo_tarballs']}")
PY

# ---------------------------------------------------------------------------
# 4. REPORT.md
# ---------------------------------------------------------------------------
run "write REPORT.md" python3 - "${OUT_DIR}" <<'PY'
import json, os, sys

out = sys.argv[1]
os.chdir(out)
m = json.load(open("MANIFEST.json", encoding="utf-8"))
c, b = m["counts"], m["bytes"]

def mb(n):
    return f"{n/1024/1024:.1f} MB"

def read_list(name):
    if not os.path.exists(name):
        return []
    return [l.strip() for l in open(name, encoding="utf-8") if l.strip()]

lines = []
A = lines.append
A("# 依赖包状态报告")
A("")
A(f"生成时间：{m['generated_at']}  ")
A(f"生成环境：{m['generated_on_host']}  ")
A(f"纳入哈希的文件：{m['hashed_file_count']}")
A("")
A("## 实物清单（已下载到本目录）")
A("")
A("| 部分 | 数量 | 体积 |")
A("|---|---:|---:|")
A(f"| `debs/`（APT 完整闭包） | {c['debs']} | {mb(b['debs'])} |")
A(f"| `wheelhouse-odoo/` 轮子 | {c['wheels_odoo']} | {mb(b['wheels_odoo'])} |")
A(f"| `wheelhouse-crawler/` 轮子 | {c['wheels_crawler']} | {mb(b['wheels_crawler'])} |")
A(f"| `odoo/` 源码包 | {c['odoo_tarballs']} | {mb(b['odoo_tarball'])} |")
A("")
A("## Odoo 固定 revision")
A("")
if m["odoo_revision"]:
    for k, v in m["odoo_revision"].items():
        A(f"- `{k}` = `{v}`")
else:
    A("- **未记录**（02_fetch_odoo.sh 尚未成功运行）")
A("")
A("## 明确未包含 / 仍需处理")
A("")
if m["not_included"]:
    for entry in m["not_included"]:
        A(f"### {entry['file']}")
        A("")
        for item in entry["entries"]:
            A(f"- `{item}`")
        A("")
else:
    A("无。（所有请求的包都已就位，且每个 Odoo 依赖都有轮子）")
    A("")
A("## 验收方式")
A("")
A("```bash")
A("cd <把 out/ 拷到的位置>")
A("bash 05_offline_verify.sh          # 无需网络")
A("bash 05_offline_verify.sh --docker # 需要 docker 引擎，做闭包安装验收")
A("```")
A("")
A("## 注意事项")
A("")
for n in m["notes"]:
    A(f"- {n}")

open("REPORT.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("REPORT.md written")
PY

echo
ok "manifest complete: ${OUT_DIR}/{SHA256SUMS,MANIFEST.json,REPORT.md}"
