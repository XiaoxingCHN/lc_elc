<#
.SYNOPSIS
  Restore the Windows/Android client toolchain from the offline developer
  dependency package, so a rebuild needs no further downloads.

.DESCRIPTION
  The package ships UPSTREAM ARCHIVES (not expanded SDK trees) plus the two
  package caches. This script turns them into a self-contained toolchain:

    <TargetRoot>\flutter\                            <- flutter_windows_<v>-stable.zip
    <TargetRoot>\jdk\jdk17.0.20_12\                  <- amazon-corretto-...-jdk.zip
    <TargetRoot>\android-sdk\cmdline-tools\latest\   <- commandlinetools-win-*.zip
    <TargetRoot>\android-sdk\platform-tools\         <- android\platform-tools\ (adb)
    <TargetRoot>\android-sdk\platforms\android-36\   <- platform-36_r02.zip
    <TargetRoot>\android-sdk\build-tools\36.0.0\     <- build-tools_r36_windows.zip
    <TargetRoot>\android-sdk\ndk\28.2.13676358\      <- android-ndk-r28c-windows.zip
    <TargetRoot>\pub-cache\                          <- pub-cache-windows\
    <TargetRoot>\gradle-home\                        <- gradle-cache\wrapper + caches\modules-2

  Three packaging quirks are handled explicitly, because getting them wrong makes
  Gradle or sdkmanager fail in confusing ways:
    * build-tools_r36_windows.zip has the INTERNAL top-level directory name
      "android-16" (a legacy Google packaging quirk). It must land in
      build-tools\36.0.0, NOT build-tools\android-16.
    * commandlinetools-win-*.zip unpacks to "cmdline-tools" and must be renamed
      to "cmdline-tools\latest" or sdkmanager refuses to run.
    * the JDK archive's top level is literally "jdk17.0.20_12".

  SAFETY: this script only ever creates or deletes paths it verified to be
  strictly inside -TargetRoot. Volume roots, and any path that is one, or whose
  parent chain contains one, is a reparse point (symlink/junction) are refused -
  deleting through a junction would remove data outside the target.

  NOT included in the package, and therefore NOT restored here:
    * expanded SDK trees (sdk\windows, android\java, android\sdk)
    * any proxy/credentials gradle.properties (dependencies\gradle-cache\gradle.properties
      is deliberately NOT copied - supply your own if your network needs one)
    * private keys / keystores

  MSVC is NOT part of this package: no MSVC offline installer is shipped.
  Windows desktop builds need "Desktop development with C++" (Visual Studio 2022
  or newer), installed through the Visual Studio installer. Visual Studio does
  support an offline layout (vs_installer.exe --layout <dir>) if one is needed.

.PARAMETER TargetRoot
  Where to restore. Default: <package>\tools

.PARAMETER WithLinuxFlutter
  Also unpack sdk\flutter_linux_*.tar.xz (only useful on a Linux dev box).

.PARAMETER Force
  Re-extract even if the destination exists. Destinations are deleted only after
  passing the containment/reparse checks described above.

.PARAMETER Verify
  Run the toolchain's own version commands at the end.

.PARAMETER AndroidProject
  Optional Flutter project directory (containing pubspec.yaml). When given, an
  android\local.properties is written pointing at the restored SDK - that is the
  file the Android Gradle build actually reads.

.PARAMETER NoChecksum
  Skip SHA-256/SHA-1 verification. Not recommended.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\restore_client_tools.ps1 -Verify

.EXAMPLE
  .\restore_client_tools.ps1 -TargetRoot D:\lc_elc_tools -AndroidProject ..\clients\shared_source
#>
[CmdletBinding()]
param(
    [string]$TargetRoot = '',
    [switch]$WithLinuxFlutter,
    [switch]$Force,
    [switch]$Verify,
    [string]$AndroidProject = '',
    [switch]$NoChecksum
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Pkg = $PSScriptRoot
if (-not $TargetRoot) { $TargetRoot = Join-Path $Pkg 'tools' }
$sep = [System.IO.Path]::DirectorySeparatorChar
$TargetRoot = [System.IO.Path]::GetFullPath($TargetRoot)

$script:Failures = 0

function Step  { param([string]$m) Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok    { param([string]$m) Write-Host "OK   $m" -ForegroundColor Green }
function Warn2 { param([string]$m) Write-Host "WARN $m" -ForegroundColor Yellow }
function Bad   { param([string]$m) Write-Host "FAIL $m" -ForegroundColor Red; $script:Failures++ }

function Assert-NoFailures {
    param([string]$Stage)
    if ($script:Failures -gt 0) {
        Write-Host ''
        Write-Host "ABORT after '$Stage': $script:Failures problem(s) found." -ForegroundColor Red
        Write-Host 'The toolchain is INCOMPLETE. Do not treat this as a successful restore.' -ForegroundColor Red
        exit 1
    }
}

# ---------------------------------------------------------------------------
# containment / reparse-point guard
# ---------------------------------------------------------------------------
function Assert-WithinTarget {
    <#
      Returns the normalised absolute path of something strictly inside
      $TargetRoot, or throws. Refuses:
        * a volume root as TargetRoot
        * a path equal to TargetRoot, or outside it
        * a path whose containment is only a string prefix (C:\a\bc vs C:\a\b)
        * TargetRoot, any intermediate directory, or the target itself being a
          reparse point (symlink / junction / mount point)
    #>
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Root
    )

    $trimChars = [char[]]@([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd($trimChars)
    $full = [System.IO.Path]::GetFullPath($Path).TrimEnd($trimChars)

    $volRoot = [System.IO.Path]::GetPathRoot($fullRoot).TrimEnd($trimChars)
    if ($fullRoot -ieq $volRoot) {
        throw "refusing to operate: TargetRoot is a volume root ($fullRoot)"
    }
    if ($full -ieq $fullRoot) {
        throw "refusing to operate on TargetRoot itself ($full)"
    }

    $prefix = $fullRoot + $sep
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "refusing: '$full' is not strictly inside '$fullRoot'"
    }

    # Walk root -> ... -> target and reject any reparse point along the way.
    $chain = New-Object System.Collections.Generic.List[string]
    $chain.Add($fullRoot)
    $acc = $fullRoot
    foreach ($seg in ($full.Substring($prefix.Length) -split '[\\/]')) {
        if (-not $seg) { continue }
        $acc = Join-Path $acc $seg
        $chain.Add($acc)
    }
    $reparse = [int][System.IO.FileAttributes]::ReparsePoint
    foreach ($d in $chain) {
        if (Test-Path -LiteralPath $d) {
            $item = Get-Item -LiteralPath $d -Force
            if (([int]$item.Attributes -band $reparse) -ne 0) {
                throw "refusing: '$d' is a reparse point (symlink/junction); a recursive delete could remove data outside TargetRoot"
            }
        }
    }
    return $full
}

function Remove-OwnDir {
    param([Parameter(Mandatory)][string]$Path)
    $full = Assert-WithinTarget -Path $Path -Root $TargetRoot
    if (Test-Path -LiteralPath $full) {
        Remove-Item -LiteralPath $full -Recurse -Force
        Write-Host "    removed $full" -ForegroundColor DarkGray
    }
}

function Format-PsLiteral {
    param([string]$Value)
    return "'" + $Value.Replace("'", "''") + "'"
}

function ConvertTo-JavaPropertyValue {
    <#
      local.properties is read by java.util.Properties.load(), which decodes as
      ISO-8859-1. A non-ASCII path (a Chinese user directory, for example) must
      therefore be written as \\uXXXX escapes - writing it as ASCII would silently
      turn every CJK character into '?' and Gradle would look in the wrong place.
    #>
    param([string]$Value)
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $Value.ToCharArray()) {
        if ([int]$ch -gt 127) { [void]$sb.AppendFormat('\u{0:X4}', [int]$ch) }
        elseif ($ch -eq ':') { [void]$sb.Append('\:') }
        else { [void]$sb.Append($ch) }
    }
    return $sb.ToString()
}

function Get-TarExe {
    $t = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (Test-Path -LiteralPath $t) { return $t }
    $c = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    return $null
}

function Read-Manifest {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { Warn2 "manifest not parseable: $Path"; return $null }
}

function Test-AssetHash {
    param([string]$File, [string]$ManifestPath)
    if ($NoChecksum) { Warn2 "checksum skipped (NoChecksum): $(Split-Path $File -Leaf)"; return $true }
    $m = Read-Manifest $ManifestPath
    if (-not $m) { Warn2 "no manifest -> cannot verify $(Split-Path $File -Leaf)"; return $true }

    $props = $m.PSObject.Properties.Name
    $want = $null; $algo = $null
    if (($props -contains 'sha256') -and $m.sha256) { $want = $m.sha256; $algo = 'SHA256' }
    elseif (($props -contains 'release') -and ($m.release.PSObject.Properties.Name -contains 'sha256') -and $m.release.sha256) {
        $want = $m.release.sha256; $algo = 'SHA256'
    }
    elseif (($props -contains 'sha1') -and $m.sha1) { $want = $m.sha1; $algo = 'SHA1' }

    if (-not $want) { Warn2 "manifest has no checksum -> skipping $(Split-Path $File -Leaf)"; return $true }

    $got = (Get-FileHash -LiteralPath $File -Algorithm $algo).Hash
    if ($got -ne $want.ToUpperInvariant()) {
        Bad "$(Split-Path $File -Leaf) $algo mismatch`n     expected $($want.ToUpperInvariant())`n     actual   $got"
        return $false
    }
    Ok "$(Split-Path $File -Leaf) $algo verified"
    return $true
}

function Expand-Asset {
    <#
      Extracts $Archive so exactly one top-level entry ($ExpectedTop) appears
      directly inside $Into, then optionally renames it to $RenameTo.
      $Into must be inside TargetRoot; the temporary unpack dir used by the
      Expand-Archive fallback is checked the same way before removal.
    #>
    param(
        [Parameter(Mandatory)][string]$Archive,
        [Parameter(Mandatory)][string]$Into,
        [Parameter(Mandatory)][string]$ExpectedTop,
        [string]$RenameTo = '',
        [string]$ManifestPath = ''
    )

    if (-not (Test-Path -LiteralPath $Archive)) { Bad "archive missing: $Archive"; return $false }
    if (-not (Test-AssetHash -File $Archive -ManifestPath $ManifestPath)) { return $false }

    # Validate the directory this call will CREATE (and may later delete), not the
    # extraction parent. The parent is allowed to be TargetRoot itself - for the
    # Flutter archive it is - because TargetRoot is never removed. The generated
    # directory, however, must be strictly inside TargetRoot.
    $finalName = if ($RenameTo) { $RenameTo } else { $ExpectedTop }
    try {
        $finalPath = Assert-WithinTarget -Path (Join-Path $Into $finalName) -Root $TargetRoot
    } catch {
        Bad "refusing to extract into an unsafe destination: $($_.Exception.Message)"
        return $false
    }
    $intoFull = Split-Path -Parent $finalPath

    if (Test-Path -LiteralPath $finalPath) {
        if (-not $Force) { Warn2 "already present, skipping: $finalPath"; return $true }
        # strict: Remove-OwnDir still refuses TargetRoot itself and reparse points
        Remove-OwnDir -Path $finalPath
    }
    New-Item -ItemType Directory -Force -Path $intoFull | Out-Null

    $tar = Get-TarExe
    if ($tar) {
        & $tar -xf $Archive -C $intoFull
        if ($LASTEXITCODE -ne 0) { Bad "tar failed on $(Split-Path $Archive -Leaf) (exit $LASTEXITCODE)"; return $false }
    } else {
        $tmp = Join-Path $intoFull ('.expand-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Force -Path $tmp | Out-Null
        try {
            Expand-Archive -LiteralPath $Archive -DestinationPath $tmp -Force
            Get-ChildItem -LiteralPath $tmp -Force | ForEach-Object {
                Move-Item -LiteralPath $_.FullName -Destination $intoFull -Force
            }
        } finally {
            Remove-OwnDir -Path $tmp
        }
    }

    $produced = Join-Path $intoFull $ExpectedTop
    if (-not (Test-Path -LiteralPath $produced)) {
        Bad "expected '$ExpectedTop' inside $intoFull but it was not created"
        return $false
    }
    if ($RenameTo) {
        Move-Item -LiteralPath $produced -Destination $finalPath -Force
        Ok "$(Split-Path $Archive -Leaf) -> $finalName  (internal name was '$ExpectedTop')"
    } else {
        Ok "$(Split-Path $Archive -Leaf) -> $finalName"
    }
    return $true
}

function Copy-Tree {
    param([string]$From, [string]$To, [string]$Label)
    if (-not (Test-Path -LiteralPath $From)) { Warn2 "$Label source absent: $From"; return $true }
    try {
        $toFull = Assert-WithinTarget -Path $To -Root $TargetRoot
    } catch {
        Bad "refusing to copy $Label to an unsafe destination: $($_.Exception.Message)"
        return $false
    }
    if (Test-Path -LiteralPath $toFull) {
        if (-not $Force) { Warn2 "$Label already present, skipping: $toFull"; return $true }
        Remove-OwnDir -Path $toFull
    }
    New-Item -ItemType Directory -Force -Path (Split-Path $toFull -Parent) | Out-Null
    # The pub cache is tens of thousands of small files; robocopy is far faster
    # than Copy-Item. Exit codes 0-7 are success for robocopy.
    $rc = Start-Process -FilePath robocopy.exe `
            -ArgumentList @("`"$From`"", "`"$toFull`"", '/E', '/NFL', '/NDL', '/NJH', '/NJS', '/R:1', '/W:1') `
            -Wait -PassThru -NoNewWindow
    if ($rc.ExitCode -ge 8) { Bad "$Label copy failed (robocopy exit $($rc.ExitCode))"; return $false }
    Ok "$Label -> $toFull"
    return $true
}

function Get-ArchiveTopLevel {
    param([string]$Archive)
    $tar = Get-TarExe
    if (-not $tar) { return '' }
    $first = (& $tar -tf $Archive 2>$null | Select-Object -First 1)
    if (-not $first) { return '' }
    return (($first -split '/')[0]).TrimEnd('/')
}

# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------
Write-Host '============================================================'
Write-Host ' LCSC client toolchain restore (offline developer package)'
Write-Host '============================================================'
Write-Host "package : $Pkg"
Write-Host "target  : $TargetRoot"
Write-Host "force   : $($Force.IsPresent)   verify: $($Verify.IsPresent)   checksum: $(-not $NoChecksum.IsPresent)"

$sdkDir = Join-Path $Pkg 'sdk'
$andDir = Join-Path $Pkg 'android'
$dlDir  = Join-Path $andDir 'downloads'

$flutterZip  = Get-ChildItem -LiteralPath $sdkDir -Filter 'flutter_windows_*-stable.zip' -File -ErrorAction SilentlyContinue | Select-Object -First 1
$flutterXz   = Get-ChildItem -LiteralPath $sdkDir -Filter 'flutter_linux_*-stable.tar.xz' -File -ErrorAction SilentlyContinue | Select-Object -First 1
$jdkZip      = Get-ChildItem -LiteralPath $andDir -Filter 'amazon-corretto-*-jdk.zip' -File -ErrorAction SilentlyContinue | Select-Object -First 1
$cmdZip      = Get-ChildItem -LiteralPath $andDir -Filter 'commandlinetools-win-*.zip' -File -ErrorAction SilentlyContinue | Select-Object -First 1
$platformZip = Get-ChildItem -LiteralPath $dlDir  -Filter 'platform-*.zip' -File -ErrorAction SilentlyContinue | Select-Object -First 1
$btZip       = Get-ChildItem -LiteralPath $dlDir  -Filter 'build-tools_r*_windows.zip' -File -ErrorAction SilentlyContinue | Select-Object -First 1
$ndkZip      = Get-ChildItem -LiteralPath $dlDir  -Filter 'android-ndk-*-windows.zip' -File -ErrorAction SilentlyContinue | Select-Object -First 1

if (-not ($flutterZip -or $jdkZip -or $cmdZip)) {
    Write-Host 'FAILED: this does not look like the SDK developer-dependency package.' -ForegroundColor Red
    Write-Host 'Expected sdk\flutter_*.zip and android\*.zip next to this script.' -ForegroundColor Red
    exit 1
}

try { New-Item -ItemType Directory -Force -Path $TargetRoot | Out-Null }
catch { Write-Host "FAILED: cannot create TargetRoot: $_" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------------------
# Flutter
# ---------------------------------------------------------------------------
Step 'Flutter SDK'
if ($flutterZip) {
    [void](Expand-Asset -Archive $flutterZip.FullName -Into $TargetRoot -ExpectedTop 'flutter' `
            -ManifestPath (Join-Path $sdkDir 'flutter-windows-release.json'))
} else { Bad 'flutter_windows_*.zip not present' }
Assert-NoFailures 'Flutter SDK'

if ($WithLinuxFlutter) {
    if ($flutterXz) {
        [void](Expand-Asset -Archive $flutterXz.FullName -Into (Join-Path $TargetRoot 'linux') -ExpectedTop 'flutter' `
                -ManifestPath (Join-Path $sdkDir 'flutter-linux-release.json'))
    } else { Bad 'flutter_linux_*.tar.xz requested but not present' }
    Assert-NoFailures 'Linux Flutter SDK'
} else {
    Write-Host '    (sdk\flutter_linux_*.tar.xz not unpacked; pass -WithLinuxFlutter to include it)'
}

# ---------------------------------------------------------------------------
# JDK
# ---------------------------------------------------------------------------
Step 'JDK 17 (Amazon Corretto)'
if ($jdkZip) {
    $jdkTop = Get-ArchiveTopLevel -Archive $jdkZip.FullName
    if (-not $jdkTop) { Bad 'cannot read the JDK archive top level'; }
    else {
        Write-Host "    archive top-level directory: $jdkTop"
        [void](Expand-Asset -Archive $jdkZip.FullName -Into (Join-Path $TargetRoot 'jdk') -ExpectedTop $jdkTop `
                -ManifestPath (Join-Path $andDir 'jdk17-download.json'))
    }
} else { Bad 'amazon-corretto-*.zip not present' }
Assert-NoFailures 'JDK 17'

# ---------------------------------------------------------------------------
# Android SDK components
# ---------------------------------------------------------------------------
Step 'Android SDK components'
$sdk = Join-Path $TargetRoot 'android-sdk'

if ($cmdZip) {
    # internal name 'cmdline-tools' must become cmdline-tools\latest
    [void](Expand-Asset -Archive $cmdZip.FullName -Into (Join-Path $sdk 'cmdline-tools') -ExpectedTop 'cmdline-tools' `
            -RenameTo 'latest' -ManifestPath (Join-Path $andDir 'cmdline-tools-release.json'))
} else { Bad 'commandlinetools-win-*.zip not present' }

if ($platformZip) {
    $top = Get-ArchiveTopLevel -Archive $platformZip.FullName
    [void](Expand-Asset -Archive $platformZip.FullName -Into (Join-Path $sdk 'platforms') -ExpectedTop $top `
            -ManifestPath (Join-Path $dlDir 'platforms-android-36.json'))
} else { Bad 'platform-*.zip not present' }

if ($btZip) {
    # TRAP: build-tools_r36_windows.zip unpacks as 'android-16', not 'android-36'
    $top = Get-ArchiveTopLevel -Archive $btZip.FullName
    Write-Host "    NOTE: build-tools archive internal name is '$top' (Google packaging quirk)"
    [void](Expand-Asset -Archive $btZip.FullName -Into (Join-Path $sdk 'build-tools') -ExpectedTop $top `
            -RenameTo '36.0.0' -ManifestPath (Join-Path $dlDir 'build-tools-36.0.0.json'))
} else { Bad 'build-tools_r*_windows.zip not present' }

if ($ndkZip) {
    $top = Get-ArchiveTopLevel -Archive $ndkZip.FullName
    [void](Expand-Asset -Archive $ndkZip.FullName -Into (Join-Path $sdk 'ndk') -ExpectedTop $top `
            -RenameTo '28.2.13676358' -ManifestPath (Join-Path $dlDir 'ndk-28.2.13676358.json'))
} else { Bad 'android-ndk-*-windows.zip not present' }

# platform-tools ships as a directory (it is small, 17 MB) and provides adb
[void](Copy-Tree -From (Join-Path $andDir 'platform-tools') -To (Join-Path $sdk 'platform-tools') -Label 'platform-tools (adb)')
Assert-NoFailures 'Android SDK components'

# ---------------------------------------------------------------------------
# package caches
# ---------------------------------------------------------------------------
Step 'pub cache (Windows)'
[void](Copy-Tree -From (Join-Path $Pkg 'pub-cache-windows') -To (Join-Path $TargetRoot 'pub-cache') -Label 'pub-cache-windows')
Assert-NoFailures 'pub cache'

Step 'Gradle cache (wrapper + modules-2)'
$gh = Join-Path $TargetRoot 'gradle-home'
[void](Copy-Tree -From (Join-Path $Pkg 'gradle-cache\wrapper') -To (Join-Path $gh 'wrapper') -Label 'gradle wrapper')
[void](Copy-Tree -From (Join-Path $Pkg 'gradle-cache\caches\modules-2') -To (Join-Path $gh 'caches\modules-2') -Label 'gradle modules-2')
Assert-NoFailures 'Gradle cache'

if (Test-Path -LiteralPath (Join-Path $Pkg 'gradle-cache\gradle.properties')) {
    Warn2 'dependencies\gradle-cache\gradle.properties was NOT copied on purpose:'
    Warn2 '  the local package carries proxy settings. Create your own if needed at'
    Warn2 "  $(Join-Path $gh 'gradle.properties')"
}

# ---------------------------------------------------------------------------
# environment file
# ---------------------------------------------------------------------------
Step 'environment file'
$jdkDir = Get-ChildItem -LiteralPath (Join-Path $TargetRoot 'jdk') -Directory -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $jdkDir) { Bad 'the JDK directory is missing after extraction'; }
Assert-NoFailures 'JDK layout'
$jdkHome = $jdkDir.FullName
$flutterHome = Join-Path $TargetRoot 'flutter'
$pubCache = Join-Path $TargetRoot 'pub-cache'
$cmdlineBin = Join-Path $sdk 'cmdline-tools\latest\bin'
$platformTools = Join-Path $sdk 'platform-tools'

# Built with single-quoted PowerShell literals so nothing is interpolated while
# generating: a backslash does NOT escape $env: inside a here-string, and a
# TargetRoot containing a single quote would otherwise break the file.
$envLines = @(
    '# Generated by restore_client_tools.ps1. Load it with:  . .\set_client_env.ps1',
    ('$env:JAVA_HOME        = ' + (Format-PsLiteral $jdkHome)),
    ('$env:ANDROID_SDK_ROOT = ' + (Format-PsLiteral $sdk)),
    ('$env:ANDROID_HOME     = ' + (Format-PsLiteral $sdk)),
    ('$env:PUB_CACHE        = ' + (Format-PsLiteral $pubCache)),
    ('$env:GRADLE_USER_HOME = ' + (Format-PsLiteral $gh)),
    ('$env:FLUTTER_ROOT     = ' + (Format-PsLiteral $flutterHome)),
    ('$env:Path = ' + (Format-PsLiteral $flutterHome) + ' + ''\bin;'' + $env:JAVA_HOME + ''\bin;'' + ' +
        (Format-PsLiteral $cmdlineBin) + ' + '';'' + ' + (Format-PsLiteral $platformTools) + ' + '';'' + $env:Path'),
    'Write-Host "JAVA_HOME         = $env:JAVA_HOME"',
    'Write-Host "ANDROID_SDK_ROOT  = $env:ANDROID_SDK_ROOT"',
    'Write-Host "PUB_CACHE         = $env:PUB_CACHE"',
    'Write-Host "GRADLE_USER_HOME  = $env:GRADLE_USER_HOME"',
    'Write-Host "FLUTTER_ROOT      = $env:FLUTTER_ROOT"'
)
$envFile = Join-Path $Pkg 'set_client_env.ps1'
# UTF-8 WITH BOM on purpose: Windows PowerShell 5.1 decodes a BOM-less script as
# ANSI, so a TargetRoot under a Chinese directory (the common case here) would be
# mojibake and the file could even fail to parse.
[System.IO.File]::WriteAllLines($envFile, $envLines, (New-Object System.Text.UTF8Encoding($true)))
Ok "wrote $envFile (UTF-8 with BOM, so PowerShell 5.1 reads non-ASCII paths correctly)"

if ($TargetRoot -match '[^\x00-\x7F]') {
    Warn2 'TargetRoot contains non-ASCII characters:'
    Warn2 "  $TargetRoot"
    Warn2 '  The Android/NDK toolchains handle non-ASCII paths poorly. If a Gradle'
    Warn2 '  build fails unexpectedly, restore to an ASCII path instead, e.g.'
    Warn2 '    -TargetRoot D:\lc_elc_tools'
    Warn2 '  local.properties is written with \uXXXX escapes, so it stays correct.'
}

if ($AndroidProject) {
    $proj = if ([System.IO.Path]::IsPathRooted($AndroidProject)) { [System.IO.Path]::GetFullPath($AndroidProject) }
            else { [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $AndroidProject)) }
    if (-not (Test-Path -LiteralPath (Join-Path $proj 'pubspec.yaml'))) {
        Bad "-AndroidProject has no pubspec.yaml: $proj"
    } else {
        $androidDir = Join-Path $proj 'android'
        New-Item -ItemType Directory -Force -Path $androidDir | Out-Null
        $lp = Join-Path $androidDir 'local.properties'
        # forward slashes + \uXXXX escapes: Properties.load() is ISO-8859-1, so a
        # CJK path would otherwise become '?' and Gradle would look in the wrong place
        $sdkVal = ConvertTo-JavaPropertyValue ($sdk -replace '\\', '/')
        $flVal = ConvertTo-JavaPropertyValue ($flutterHome -replace '\\', '/')
        [System.IO.File]::WriteAllLines($lp, @("sdk.dir=$sdkVal", "flutter.sdk=$flVal"),
            (New-Object System.Text.ASCIIEncoding))
        Ok "wrote $lp (non-ASCII escaped as \\uXXXX)"
    }
}

# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------
if ($Verify) {
    Step 'verify'
    $flutterBat = Join-Path $flutterHome 'bin\flutter.bat'
    if (Test-Path -LiteralPath $flutterBat) {
        & $flutterBat --version
        if ($LASTEXITCODE -eq 0) { Ok 'flutter --version' } else { Bad "flutter --version exit $LASTEXITCODE" }
    } else { Bad "flutter.bat not found at $flutterBat" }

    $javaExe = Join-Path $jdkHome 'bin\java.exe'
    if (Test-Path -LiteralPath $javaExe) {
        & $javaExe -version
        if ($LASTEXITCODE -eq 0) { Ok 'java -version' } else { Bad "java -version exit $LASTEXITCODE" }
    } else { Bad "java.exe not found at $javaExe" }

    $adbExe = Join-Path $platformTools 'adb.exe'
    if (Test-Path -LiteralPath $adbExe) { Ok 'adb.exe present (platform-tools restored)' }
    else { Bad "adb.exe not found at $adbExe" }

    Assert-NoFailures 'verify'
}

# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------
Write-Host ''
Write-Host '============================================================'
if ($script:Failures -eq 0) {
    Write-Host ' RESTORE COMPLETE' -ForegroundColor Green
} else {
    Write-Host " RESTORE INCOMPLETE - $script:Failures problem(s)" -ForegroundColor Red
}
Write-Host '============================================================'
Write-Host "flutter         : $flutterHome"
Write-Host "jdk             : $jdkHome"
Write-Host "android sdk     : $sdk"
Write-Host "platform-tools  : $platformTools"
Write-Host "pub cache       : $pubCache"
Write-Host "gradle home     : $gh"
Write-Host ''
Write-Host 'Next:'
Write-Host "  1. . $envFile"
Write-Host '  2. cd <client source>; flutter pub get --offline'
Write-Host '  3. flutter build windows --release    (needs the VS C++ workload)'
Write-Host '     flutter build apk --release        (see 开发依赖还原说明.md for the'
Write-Host '                                         strictly-offline Gradle variant)'
Write-Host ''
Write-Host 'Windows desktop builds additionally need the Visual Studio workload'
Write-Host '"Desktop development with C++" (VS 2022 or newer). That is NOT in this'
Write-Host 'package and must be installed through the Visual Studio installer.'
if ($script:Failures -ne 0) { exit 1 }
