# TuxD-Win installer - installs Python dependencies and registers a
# Scheduled Task that runs the agent at boot (as SYSTEM, so it can query
# every Windows service and Windows Update regardless of who's logged in),
# restarting it automatically if it ever exits. If tuxd-win.conf already
# exists it is left untouched - this only ever creates it from the example
# when missing.
#
# Before registering the real task it proves the interpreter it picked
# actually launches under SYSTEM and can import the agent's packages, using
# a one-shot self-test task (see Invoke-SystemSelfTest). "python works in my
# admin shell" is not enough: a Microsoft Store / Python install manager
# python.exe is an app-execution alias that launches fine interactively but
# makes Task Scheduler fail instantly with 0x80070780.
#
# Usage (elevated PowerShell):
#   powershell -ExecutionPolicy Bypass -File install-windows.ps1
#   powershell -ExecutionPolicy Bypass -File install-windows.ps1 -PythonPath "C:\Program Files\Python313\python.exe"

param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"

function Invoke-Native {
    # Windows PowerShell 5.1 turns a native command's stderr output into a
    # terminating error under $ErrorActionPreference = "Stop" - run these
    # probes under "Continue" so a missing/stub python is just "no result".
    param([scriptblock]$Block)
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Block } finally { $ErrorActionPreference = $old }
}

function Test-UsablePython {
    param([string]$Exe)
    if (-not $Exe -or -not (Test-Path -LiteralPath $Exe)) { return $false }
    # App-execution aliases (Microsoft Store Python, the Python install
    # manager's python.exe stub) live under ...\WindowsApps\ as 0-byte
    # reparse points. Task Scheduler running as SYSTEM cannot launch them.
    if ($Exe -match '\\WindowsApps\\') { return $false }
    $v = Invoke-Native { & $Exe -c "import sys; print(int(sys.version_info >= (3, 9)))" 2>$null }
    return ("$v".Trim() -eq "1")
}

function Find-RealPython {
    $candidates = New-Object System.Collections.Generic.List[string]

    # Ask each launcher which interpreter it actually runs (sys.executable).
    # Unlike Get-Command, that sees through an app-execution alias to the
    # real python.exe behind it.
    foreach ($launcher in @("python", "python3")) {
        if (Get-Command $launcher -ErrorAction SilentlyContinue) {
            $exe = Invoke-Native { & $launcher -c "import sys; print(sys.executable)" 2>$null }
            if ($exe) { $candidates.Add((("$exe" -split "`r?`n")[0]).Trim()) }
        }
    }

    if (Get-Command py -ErrorAction SilentlyContinue) {
        $listing = Invoke-Native { & py -0p 2>$null }
        foreach ($line in $listing) {
            if ("$line" -match '([A-Za-z]:\\.*?python\.exe)\s*$') { $candidates.Add($Matches[1]) }
        }
    }

    $globs = New-Object System.Collections.Generic.List[string]
    if ($env:ProgramFiles) { $globs.Add((Join-Path $env:ProgramFiles "Python3*\python.exe")) }
    if (${env:ProgramFiles(x86)}) { $globs.Add((Join-Path ${env:ProgramFiles(x86)} "Python3*\python.exe")) }
    $globs.Add("C:\Python3*\python.exe")
    if ($env:LOCALAPPDATA) {
        $globs.Add((Join-Path $env:LOCALAPPDATA "Programs\Python\Python3*\python.exe"))
        $globs.Add((Join-Path $env:LOCALAPPDATA "Python\pythoncore-*\python.exe"))
    }
    foreach ($g in $globs) {
        Get-ChildItem -Path $g -ErrorAction SilentlyContinue |
            Sort-Object FullName -Descending |
            ForEach-Object { $candidates.Add($_.FullName) }
    }

    foreach ($c in ($candidates | Select-Object -Unique)) {
        if (Test-UsablePython $c) { return $c }
    }
    return $null
}

function Invoke-SystemSelfTest {
    # Runs `windows_start.py --selftest` once as a temporary Scheduled Task
    # under the same principal the real task will use, then removes it.
    # windows_start.py's own selftest writes selftest.log next to itself, so
    # a launch failure (no log at all, plus a Task Scheduler result code) is
    # distinguishable from a launch that worked but hit a missing package.
    param(
        [string]$PythonExe,
        [string]$ScriptPath,
        [string]$WorkDir,
        $Principal,
        [string]$TaskName = "TuxD-Win-SelfTest"
    )
    $logPath = Join-Path $WorkDir "selftest.log"
    Remove-Item -LiteralPath $logPath -Force -ErrorAction SilentlyContinue

    $action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$ScriptPath`" --selftest" -WorkingDirectory $WorkDir
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $startedAt = Get-Date
    $result = $null
    try {
        Register-ScheduledTask -TaskName $TaskName -Action $action -Settings $settings -Principal $Principal -Force | Out-Null
        Start-ScheduledTask -TaskName $TaskName
        $deadline = (Get-Date).AddSeconds(90)
        do {
            Start-Sleep -Milliseconds 500
            $info = Get-ScheduledTaskInfo -TaskName $TaskName
            $state = (Get-ScheduledTask -TaskName $TaskName).State
            # A launch that fails instantly (0x80070780) never shows
            # "Running" - LastRunTime moving past $startedAt is what says a
            # run was attempted, not the state.
            $hasRun = $info.LastRunTime -ge $startedAt.AddSeconds(-2)
        } while ((-not $hasRun -or $state -eq "Running") -and (Get-Date) -lt $deadline)
        # L suffix matters: a bare 0xFFFFFFFF (or 0x80070780) parses as a
        # negative Int32 in PowerShell, not the unsigned HRESULT it looks like.
        $result = [int64]$info.LastTaskResult -band 0xFFFFFFFFL
    } finally {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    }

    $log = $null
    if (Test-Path -LiteralPath $logPath) { $log = Get-Content -LiteralPath $logPath -Raw }
    return [pscustomobject]@{
        Result  = $result
        Log     = $log
        LogPath = $logPath
        Passed  = [bool]($log -and $log -match "SELFTEST_OK")
    }
}

function Get-SelfTestFailure {
    param($Test, [string]$PythonExe, [string]$InstallDir)
    $hex = "0x{0:X8}" -f $Test.Result
    # 0x80070780L (long literal): a bare 0x80070780 parses as a negative
    # Int32 in PowerShell and would never equal the unsigned result.
    if ($Test.Result -eq 0x80070780L) {
        $why = "Task Scheduler could not open '$PythonExe' as SYSTEM ($hex, ERROR_CANT_ACCESS_FILE). This is what an interpreter behind a Microsoft Store / Python install manager alias, or in a folder SYSTEM cannot read, does. Install Python 3.9+ from python.org for all users and re-run (or pass -PythonPath)."
    } elseif ($Test.Log) {
        $why = "The interpreter launched under SYSTEM but its self-test failed - most likely a package is not visible to SYSTEM. Install them with: & '$PythonExe' -m pip install websockets pyyaml psutil"
    } else {
        $why = "The self-test task ran ($hex) but produced no selftest.log - either the interpreter could not start under SYSTEM, or SYSTEM cannot write to $InstallDir (needed for remote config editing and self-update)."
    }
    $report = if ($Test.Log) { "`n--- selftest.log ---`n$($Test.Log)" } else { "" }
    return "Self-test as SYSTEM failed: $why$report`nNo scheduled task was registered or changed."
}

# ---------------------------------------------------------------- main

$InstallDir = $PSScriptRoot
Write-Host "Installing TuxD-Win into $InstallDir"

$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "This must be run from an elevated (Run as Administrator) PowerShell - registering a SYSTEM Scheduled Task requires it."
    exit 1
}

if ($PythonPath) {
    if (-not (Test-UsablePython $PythonPath)) {
        Write-Error "-PythonPath '$PythonPath' is not usable: it must exist, be Python 3.9+, and not be a WindowsApps alias (Task Scheduler cannot launch those as SYSTEM)."
        exit 1
    }
    $pythonExe = $PythonPath
} else {
    $pythonExe = Find-RealPython
    if (-not $pythonExe) {
        $onPath = (Get-Command python -ErrorAction SilentlyContinue).Source
        $seen = if ($onPath) { "'python' on PATH is $onPath. " } else { "No 'python' on PATH. " }
        Write-Error ("No Python 3.9+ that Task Scheduler can launch was found. " + $seen +
            "A Microsoft Store / Python install manager python.exe under WindowsApps is only a launcher alias - it works in your shell but fails as SYSTEM (0x80070780). " +
            "Install Python 3.9+ from python.org (not the Store), then re-run this script, or pass -PythonPath.")
        exit 1
    }
}
Write-Host "Using Python: $pythonExe"

Write-Host "Installing Python dependencies (websockets, pyyaml, psutil)..."
& $pythonExe -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) { Write-Warning "Could not upgrade pip (exit $LASTEXITCODE) - continuing with the version already installed." }
& $pythonExe -m pip install --quiet websockets pyyaml psutil
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip could not install websockets/pyyaml/psutil for $pythonExe (exit $LASTEXITCODE)."
    exit 1
}

$confPath = Join-Path $InstallDir "tuxd-win.conf"
$examplePath = Join-Path $InstallDir "tuxd-win.conf.example"
if (-not (Test-Path $confPath)) {
    Copy-Item $examplePath $confPath
    Write-Host "Created tuxd-win.conf from the example - edit device.name and home-assistant.url/pairing_key before starting the task."
} else {
    Write-Host "tuxd-win.conf already exists - left untouched."
}

$taskName = "TuxD-Win"
$scriptPath = Join-Path $InstallDir "windows_start.py"
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Write-Host "Checking that SYSTEM can launch this interpreter and import its packages..."
$test = Invoke-SystemSelfTest -PythonExe $pythonExe -ScriptPath $scriptPath -WorkDir $InstallDir -Principal $principal
if (-not $test.Passed) {
    Write-Error (Get-SelfTestFailure -Test $test -PythonExe $pythonExe -InstallDir $InstallDir)
    exit 1
}
Remove-Item -LiteralPath $test.LogPath -Force -ErrorAction SilentlyContinue
Write-Host "Self-test passed (ran as SYSTEM)."

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$scriptPath`"" -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

$wasRunning = $false
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    $wasRunning = ($existing.State -eq 'Running')
    Write-Host "Scheduled Task '$taskName' already exists - replacing its definition (this does not touch tuxd-win.conf)."
    # Unregistering alone leaves a running instance alive on the old code.
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description "TuxD-Win monitoring agent - reports to Home Assistant via TuxD-HA" | Out-Null

if ($wasRunning) {
    Start-ScheduledTask -TaskName $taskName
    Write-Host "It was running before - started it again on the new definition."
}

Write-Host ""
Write-Host "############################################################"
Write-Host "# TuxD-Win installed as Scheduled Task '$taskName' (runs at boot as SYSTEM)."
Write-Host "# Interpreter: $pythonExe"
Write-Host "# It is NOT started automatically by this script."
Write-Host "# Edit $confPath now if you haven't already, then start it with:"
Write-Host "#   Start-ScheduledTask -TaskName $taskName"
Write-Host "# Check on it with:"
Write-Host "#   Get-ScheduledTaskInfo -TaskName $taskName"
Write-Host "############################################################"
