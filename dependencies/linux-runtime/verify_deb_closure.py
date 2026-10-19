#!/usr/bin/env python3
"""Verify that the offline .deb set in out/debs is dependency-complete.

Run inside WSL (needs dpkg-deb, which the Windows side does not have):

  wsl -d Ubuntu-22.04 -- python3 \
    "/mnt/c/.../lc_elc/dependencies/linux-runtime/verify_deb_closure.py"

For every .deb in out/debs it reads Package/Provides/Depends/Pre-Depends and
reports any dependency that is not satisfied by another .deb in the same set.
Alternatives (`a | b`) count as satisfied when either name is present, and the
usual apt-internal names (debconf, dpkg, libc6, ...) are reported separately so
a genuinely missing library is not lost among essential packages.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Packages that a normal Ubuntu install always provides and that the offline
# bundle intentionally does not duplicate.
BASE_SYSTEM = {
    "libc6", "libc-bin", "dpkg", "debconf", "perl-base", "tar", "gzip",
    "base-files", "base-passwd", "bash", "coreutils", "dash", "sed", "grep",
    "findutils", "hostname", "init-system-helpers", "libcrypt1",
}


def field(path: Path, name: str) -> str:
    out = subprocess.run(
        ["dpkg-deb", "-f", str(path), name],
        capture_output=True, text=True, check=False,
    )
    return out.stdout.strip()


def names(value: str) -> list[str]:
    """`a (>= 1), b:any | c [amd64]` -> ['a', 'b', 'c'] (flat, for Provides)."""
    result: list[str] = []
    for clause in value.split(","):
        for alternative in clause.split("|"):
            token = alternative.strip()
            if not token:
                continue
            token = token.split("[")[0].strip()
            token = re.sub(r"\s*\(.*$", "", token).strip()
            token = token.split(":")[0].strip()
            if token:
                result.append(token)
    return result


def clauses(value: str) -> list[list[str]]:
    """A dependency list as clauses of alternatives: `a | b, c` -> [[a,b],[c]].

    apt is satisfied when ANY alternative of a clause is installed, so that is
    how completeness has to be judged - flattening the list would report the
    unused alternatives as missing.
    """
    result: list[list[str]] = []
    for clause in value.split(","):
        alternatives: list[str] = []
        for alternative in clause.split("|"):
            token = alternative.strip()
            if not token:
                continue
            token = token.split("[")[0].strip()
            token = re.sub(r"\s*\(.*$", "", token).strip()
            token = token.split(":")[0].strip()
            if token:
                alternatives.append(token)
        if alternatives:
            result.append(alternatives)
    return result


def main() -> int:
    here = Path(__file__).resolve().parent
    deb_dir = here / "out" / "debs"
    debs = sorted(deb_dir.glob("*.deb"))
    if not debs:
        print(f"no debs found in {deb_dir}", file=sys.stderr)
        return 2

    provided: dict[str, set[str]] = {}
    depends: dict[str, list[str]] = {}
    owners: dict[str, list[str]] = {}
    unreadable: list[str] = []
    for deb in debs:
        pkg = field(deb, "Package")
        if not pkg:
            unreadable.append(deb.name)
            continue
        owners.setdefault(pkg, []).append(deb.name)
        names_out = {pkg}
        for p in names(field(deb, "Provides")):
            names_out.add(p)
        provided[pkg] = names_out
        depends[pkg] = clauses(field(deb, "Depends")) + clauses(field(deb, "Pre-Depends"))

    duplicate_versions = {p: f for p, f in owners.items() if len(f) > 1}
    if unreadable:
        print("unreadable debs:")
        for name in unreadable:
            print(f"  {name}")
    if duplicate_versions:
        print("same package shipped twice (apt will pick one):")
        for pkg, files in sorted(duplicate_versions.items()):
            print(f"  {pkg}: {', '.join(files)}")

    all_provided = {n for group in provided.values() for n in group}
    missing: dict[str, list[str]] = {}
    base_only: dict[str, list[str]] = {}
    for pkg, dep_clauses in depends.items():
        for alternatives in dep_clauses:
            if any(a in all_provided for a in alternatives):
                continue
            key = " | ".join(alternatives)
            if any(a in BASE_SYSTEM for a in alternatives):
                base_only.setdefault(key, []).append(pkg)
            else:
                missing.setdefault(key, []).append(pkg)

    print(f"debs scanned      : {len(provided)}")
    print(f"provided names    : {len(all_provided)}")
    print(f"unresolved deps   : {sum(len(v) for v in missing.values())}")
    print(f"base-system deps  : {sum(len(v) for v in base_only.values())}")

    if missing:
        print("\nUNRESOLVED (needed by -> clause):")
        for dep, pkg_owners in sorted(missing.items()):
            print(f"  {dep}  <- {', '.join(sorted(pkg_owners))}")
    if base_only:
        print("\nassumed present on any Ubuntu install:")
        for dep, pkg_owners in sorted(base_only.items()):
            print(f"  {dep}  <- {', '.join(sorted(pkg_owners))}")

    for probe in ("libsecret-1-0", "libcups2", "gnome-keyring"):
        if probe in provided:
            print(f"\n{probe}: present")
            for alternatives in depends.get(probe, []):
                if any(a in all_provided for a in alternatives):
                    state = "ok"
                elif any(a in BASE_SYSTEM for a in alternatives):
                    state = "base"
                else:
                    state = "MISSING"
                print(f"  depends {' | '.join(alternatives)}: {state}")
        else:
            print(f"\n{probe}: NOT in the set")

    print("\nfield detail for the reported gaps (Depends vs Recommends):")
    for probe in ("fontconfig-config", "adwaita-icon-theme", "libpam-runtime"):
        deb = next((d for d in debs if field(d, "Package") == probe), None)
        if deb is None:
            continue
        print(f"  {probe}")
        print(f"    Depends   : {field(deb, 'Depends') or '-'}")
        print(f"    Recommends: {field(deb, 'Recommends') or '-'}")

    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
