param(
    [Parameter(Mandatory = $true)][string]$PackageDirectory,
    [Parameter(Mandatory = $true)][string]$EvidenceDirectory
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class PackageSmokeNative {
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hwnd, uint message, IntPtr wparam, IntPtr lparam);
    [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr hwnd, uint message, IntPtr wparam, IntPtr lparam, uint flags, uint timeout, out IntPtr result);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hwnd, out Rect rect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr dc, uint flags);
    [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr hwnd, int x, int y, int width, int height, bool repaint);
    [StructLayout(LayoutKind.Sequential)] public struct Rect { public int Left, Top, Right, Bottom; }
}
'@

function Save-AppWindow([IntPtr]$Window, [string]$Path) {
    $rect = [PackageSmokeNative+Rect]::new()
    [PackageSmokeNative]::GetWindowRect($Window, [ref]$rect) | Out-Null
    $bitmap = [System.Drawing.Bitmap]::new($rect.Right - $rect.Left, $rect.Bottom - $rect.Top)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $dc = $graphics.GetHdc()
    try {
        if (-not [PackageSmokeNative]::PrintWindow($Window, $dc, 0)) { throw 'Application-only capture failed' }
    } finally { $graphics.ReleaseHdc($dc); $graphics.Dispose() }
    try { $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png) }
    finally { $bitmap.Dispose() }
}

$package = (Resolve-Path -LiteralPath $PackageDirectory).Path
$executable = Join-Path $package 'AbletonLibraryManager.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw "Missing executable: $executable" }
$privateNames = @('library_config.json', 'library_assets.db', 'sidebar_cache.json', 'saved_searches.json', 'Options.txt', 'Log.txt')
$files = @(Get-ChildItem -LiteralPath $package -Recurse -File)
$private = @($files | Where-Object { $_.Name -in $privateNames -or $_.Name -match '\.(bak|db-journal|db-wal|db-shm)$' })
if ($private.Count) { throw "Package contains runtime/private state: $($private.FullName -join ', ')" }
New-Item -ItemType Directory -Path $EvidenceDirectory -Force | Out-Null
$evidence = (Resolve-Path -LiteralPath $EvidenceDirectory).Path
$temporary = Join-Path ([System.IO.Path]::GetTempPath()) ("alm-package-smoke-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporary | Out-Null
$results = @()
$running = $null
try {
    foreach ($scenario in @('fresh', 'upgrade')) {
        $run = Join-Path $temporary $scenario
        $copy = Join-Path $run 'application'
        New-Item -ItemType Directory -Path $run | Out-Null
        Copy-Item -LiteralPath $package -Destination $copy -Recurse
        $fixtureHome = Join-Path $run 'home'
        $library = Join-Path $fixtureHome 'Documents\Ableton\User Library'
        New-Item -ItemType Directory -Path $library -Force | Out-Null
        $profile = Join-Path $copy 'library_config.json'
        if ($scenario -eq 'upgrade') {
            $legacy = @{
                DRUM_KEYWORDS = @{ '\bkick\b' = 'Kicks' }
                RULE_METADATA = @{}
                XO_CUSTOM_TYPES = @{ 'Keep my folder' = @('preserved') }
                LEARNED_RULE_CANDIDATES = @(@{ token = 'old'; target = 'Snares'; count = 7; status = 'pending' })
            }
            $legacy | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $profile -Encoding utf8
        }
        $info = [System.Diagnostics.ProcessStartInfo]::new()
        $info.FileName = Join-Path $copy 'AbletonLibraryManager.exe'
        $info.WorkingDirectory = $copy
        $info.UseShellExecute = $false
        foreach ($name in @('USERPROFILE', 'HOME', 'HOMEDRIVE', 'HOMEPATH', 'OneDrive', 'OneDriveConsumer', 'OneDriveCommercial', 'APPDATA', 'LOCALAPPDATA')) {
            $info.Environment.Remove($name) | Out-Null
        }
        $info.Environment['USERPROFILE'] = $fixtureHome
        $info.Environment['HOME'] = $fixtureHome
        $info.Environment['APPDATA'] = Join-Path $fixtureHome 'AppData\Roaming'
        $info.Environment['LOCALAPPDATA'] = Join-Path $fixtureHome 'AppData\Local'
        $running = [System.Diagnostics.Process]::Start($info)
        $deadline = [DateTime]::UtcNow.AddSeconds(20)
        do {
            Start-Sleep -Milliseconds 100
            $running.Refresh()
        } while (-not $running.HasExited -and $running.MainWindowHandle -eq [IntPtr]::Zero -and [DateTime]::UtcNow -lt $deadline)
        if ($running.HasExited) { throw "$scenario exited during startup: $($running.ExitCode)" }
        $window = $running.MainWindowHandle
        if ($window -eq [IntPtr]::Zero) { throw "$scenario did not create a window" }
        Start-Sleep -Milliseconds 1000
        $running.Refresh()
        if ($running.MainWindowTitle -notlike '*Sample Studio Manager v2.1.0*') {
            throw "$scenario unexpected window: $($running.MainWindowTitle)"
        }
        $reply = [IntPtr]::Zero
        if ([PackageSmokeNative]::SendMessageTimeout($window, 0, [IntPtr]::Zero, [IntPtr]::Zero, 2, 2000, [ref]$reply) -eq [IntPtr]::Zero) {
            throw "$scenario window is unresponsive"
        }
        $rect = [PackageSmokeNative+Rect]::new()
        [PackageSmokeNative]::GetWindowRect($window, [ref]$rect) | Out-Null
        Save-AppWindow $window (Join-Path $evidence "$scenario-home.png")
        if (-not [PackageSmokeNative]::MoveWindow($window, $rect.Left, $rect.Top, 1036, 740, $true)) {
            throw "$scenario minimum-size resize failed"
        }
        Start-Sleep -Milliseconds 200
        if ([PackageSmokeNative]::SendMessageTimeout($window, 0, [IntPtr]::Zero, [IntPtr]::Zero, 2, 2000, [ref]$reply) -eq [IntPtr]::Zero) {
            throw "$scenario window is unresponsive after resizing"
        }
        Save-AppWindow $window (Join-Path $evidence "$scenario-minimum-home.png")
        if (-not (Test-Path -LiteralPath $profile)) { throw "$scenario did not create/load the fixture profile" }
        $saved = Get-Content -LiteralPath $profile -Raw | ConvertFrom-Json
        if ($scenario -eq 'upgrade' -and $saved.XO_CUSTOM_TYPES.'Keep my folder'[0] -ne 'preserved') {
            throw 'Legacy profile custom settings were not preserved'
        }
        [PackageSmokeNative]::PostMessage($window, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
        if (-not $running.WaitForExit(15000)) { throw "$scenario did not close gracefully" }
        if ($running.ExitCode -ne 0) { throw "$scenario exit code: $($running.ExitCode)" }
        $results += @{
            scenario = $scenario; startup = 'passed'; responsive = $true; graceful_exit = $running.ExitCode
            title = 'Ableton Production Assets & Sample Studio Manager v2.1.0'
            profile = 'isolated'
            navigation = 'Not tested by this startup smoke; source UI acceptance is separate.'
        }
        $running.Dispose()
        $running = $null
    }
    @{
        executable_sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash
        packaged_files = $files.Count; forbidden_files = $private.Count
        scenarios = $results
        limits = 'Startup, resize, responsiveness, profile preservation and close only; not packaged page navigation, editing/operation workflows or Live acceptance.'
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $evidence 'package-smoke.json') -Encoding utf8
    Write-Output "PASS: clean package; fresh and legacy-profile startup, responsiveness and graceful close."
} finally {
    if ($null -ne $running) {
        $running.Refresh()
        if (-not $running.HasExited) { Stop-Process -Id $running.Id -Force }
        $running.Dispose()
    }
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
