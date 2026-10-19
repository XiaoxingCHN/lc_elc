# ensure_plugin_junctions.ps1
#
# Windows-only build helper: makes `flutter pub get` work WITHOUT enabling
# Windows Developer Mode.
#
# Background: as soon as pubspec.yaml contains plugins, flutter_tools creates
# `windows/flutter/ephemeral/.plugin_symlinks/<plugin>` with real symbolic links.
# A normal user account may not create symlinks (ERROR_PRIVILEGE_NOT_HELD 1314)
# and the tool then aborts with "Building with plugins requires symlink support".
# Directory JUNCTIONS need no such privilege and are traversable exactly like a
# symlink for CMake, so this script pre-creates one junction per Windows plugin.
# flutter_tools skips links that already exist, but only when the plugin list did
# not change - which is why the recovery order below matters.
#
# Usage (from anywhere):
#   powershell -ExecutionPolicy Bypass -File ensure_plugin_junctions.ps1
#
# Recovery order when a new plugin was added to pubspec.yaml:
#   1. .\ensure_plugin_junctions.ps1        # after `flutter pub get` wrote the list
#   2. flutter pub get                       # first run may abort on symlinks
#   3. .\ensure_plugin_junctions.ps1         # junction every plugin it now lists
#   4. flutter pub get                       # now exits 0
[CmdletBinding()]
param(
    [string]$Project,
    [string]$PubCache
)

$ErrorActionPreference = 'Stop'
$Here = $PSScriptRoot
if (-not $Project) { $Project = Join-Path $Here '..\clients\app' }
if (-not $PubCache) { $PubCache = Join-Path $Here 'pub-cache-windows' }

$Project = (Resolve-Path $Project).Path
$PubCache = (Resolve-Path $PubCache).Path
$listFile = Join-Path $Project '.flutter-plugins-dependencies'
$lockFile = Join-Path $Project 'pubspec.lock'
$symlinkDir = Join-Path $Project 'windows\flutter\ephemeral\.plugin_symlinks'
$hosted = Join-Path $PubCache 'hosted\pub.dev'

if (-not (Test-Path $listFile)) { throw "missing $listFile - run 'flutter pub get' once first" }
if (-not (Test-Path $lockFile)) { throw "missing $lockFile" }
if (-not (Test-Path $hosted)) { throw "missing pub cache at $hosted" }

# name -> version from pubspec.lock
$versions = @{}
foreach ($m in [regex]::Matches((Get-Content $lockFile -Raw), '(?ms)^  ([a-z_0-9]+):\r?\n.*?^\s{4}version:\s*"?([^"\r\n]+)"?')) {
    $versions[$m.Groups[1].Value] = $m.Groups[2].Value.Trim()
}

$plugins = (Get-Content $listFile -Raw | ConvertFrom-Json).plugins.windows
if (-not $plugins) { Write-Host 'no windows plugins listed - nothing to do'; exit 0 }

New-Item -ItemType Directory -Force -Path $symlinkDir | Out-Null
$created = 0
$skipped = 0
$failed = 0

foreach ($plugin in $plugins) {
    $name = $plugin.name
    $target = $plugin.path
    if (-not $target) { $target = Join-Path $hosted ("$name-" + $versions[$name]) }
    $target = $target.TrimEnd('\')

    if (-not (Test-Path $target)) {
        # Pub may report the package root; fall back to the cache layout.
        $candidate = Join-Path $hosted ("$name-" + $versions[$name])
        if (Test-Path $candidate) { $target = $candidate } else {
            Write-Warning "target not found for $name (tried $target)"
            $failed++
            continue
        }
    }

    $link = Join-Path $symlinkDir $name
    if (Test-Path $link) {
        $item = Get-Item $link -Force
        if ($item.LinkType -eq 'Junction' -or $item.LinkType -eq 'SymbolicLink') {
            # Get-Item may report the target as '\\?\C:\...' for a junction, so
            # compare normalised forms; otherwise every run would recreate links.
            $wanted = $target.ToLower().TrimEnd('\') -replace '^\\\\\?\\', ''
            $current = @($item.Target) | ForEach-Object {
                ([string]$_).ToLower().TrimEnd('\') -replace '^\\\\\?\\', ''
            }
            if ($current -contains $wanted) { $skipped++; continue }
            # wrong target: replace the junction (never the target itself)
            cmd /c "rmdir /q `"$link`"" | Out-Null
        } else {
            Write-Warning "$link exists and is not a link - leaving it alone"
            $failed++
            continue
        }
    }

    $out = cmd /c "mklink /J `"$link`" `"$target`"" 2>&1
    if (Test-Path (Join-Path $link 'pubspec.yaml')) {
        $created++
        Write-Host "junction $name -> $target"
    } else {
        Write-Warning "mklink failed for $name : $out"
        $failed++
    }
}

Write-Host ''
Write-Host "plugin junctions: created=$created kept=$skipped failed=$failed (dir: $symlinkDir)"
if ($failed -gt 0) { exit 1 }
