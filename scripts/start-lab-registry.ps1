#Requires -Version 5.1
<#
.SYNOPSIS
    Start the native nmos-cpp registry for this repo.

.DESCRIPTION
    Repo root is the parent of this script ($PSScriptRoot\..). Every path is
    resolved from that root or from NMOS_REGISTRY_CONFIG. There are no
    hard-coded drive letters.

    Start-Process opens a new console (UseShellExecute). Close that window to
    stop the registry. Stdout and stderr are redirected to logs/.
#>

$ErrorActionPreference = 'Stop'
# nmos-reg-check, python, and netstat report status with their own exit codes.
# PowerShell 7 would otherwise turn a non-zero code into a terminating error.
$PSNativeCommandUseErrorActionPreference = $false

function Show-Usage {
    Write-Host @'
Usage: start-lab-registry.ps1 [--check]

Starts direct_deploy/nmos-cpp/bin/Release/nmos-cpp-registry.exe in a new
console window. Close that window to stop the registry.

Default config: lab/config.json under the repo root.
Override: set NMOS_REGISTRY_CONFIG to another config file.

--check  After the Query API probe succeeds, run:
         nmos-reg-check --registry http://<host_address>:<query_port> --lang zh
         If nmos-reg-check is not on PATH, try python -m nmos_reg_check from
         the repo root (.venv first). If the checker is missing, warn and
         leave the registry running.
'@
}

function Fail([string]$Message, [int]$Code = 1) {
    Write-Host $Message
    exit $Code
}

$RunCheck = $false
foreach ($arg in $args) {
    switch ($arg.ToLowerInvariant()) {
        '--check' { $RunCheck = $true }
        '-check' { $RunCheck = $true }
        '--help' { Show-Usage; exit 0 }
        '-help' { Show-Usage; exit 0 }
        '-h' { Show-Usage; exit 0 }
        '-?' { Show-Usage; exit 0 }
        default {
            Write-Host "Unknown argument: $arg"
            Show-Usage
            exit 1
        }
    }
}

if ($env:OS -ne 'Windows_NT') {
    Fail 'This script starts the native nmos-cpp registry on Windows.'
}

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$RegistryExe = Join-Path $RepoRoot 'direct_deploy\nmos-cpp\bin\Release\nmos-cpp-registry.exe'
$DefaultConfig = Join-Path $RepoRoot 'lab\config.json'

if (-not [string]::IsNullOrWhiteSpace($env:NMOS_REGISTRY_CONFIG)) {
    $candidate = $env:NMOS_REGISTRY_CONFIG.Trim()
    if (-not [System.IO.Path]::IsPathRooted($candidate)) {
        $fromCwd = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $candidate))
        $fromRoot = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot $candidate))
        if (Test-Path -LiteralPath $fromCwd) {
            $ConfigPath = $fromCwd
        } else {
            $ConfigPath = $fromRoot
        }
    } else {
        $ConfigPath = [System.IO.Path]::GetFullPath($candidate)
    }
} else {
    $ConfigPath = $DefaultConfig
}

if (-not (Test-Path -LiteralPath $RegistryExe)) {
    Fail @"
Registry executable was not found:
  $RegistryExe
Deploy nmos-cpp with Conan before starting the registry. See README.md
section "Deploy binaries with Conan". The same steps are in README.zh-CN.md
under the Conan deploy heading.
"@
}

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    Fail @"
Config file was not found:
  $ConfigPath
The default is lab/config.json under the repo root.
Set NMOS_REGISTRY_CONFIG to use a different file.
"@
}

$ConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
$RegistryExe = [System.IO.Path]::GetFullPath($RegistryExe)

$configBytes = [System.IO.File]::ReadAllBytes($ConfigPath)
if ($configBytes.Length -ge 3 -and $configBytes[0] -eq 0xEF -and $configBytes[1] -eq 0xBB -and $configBytes[2] -eq 0xBF) {
    Fail @"
Config file has a UTF-8 BOM, which nmos-cpp-registry cannot read:
  $ConfigPath
Save it as UTF-8 without a BOM.
"@
}

$utf8 = New-Object System.Text.UTF8Encoding $false
try {
    $config = [System.IO.File]::ReadAllText($ConfigPath, $utf8) | ConvertFrom-Json
} catch {
    Fail "Could not parse config JSON: $ConfigPath`n$($_.Exception.Message)"
}

if ($null -eq $config.host_address -or [string]::IsNullOrWhiteSpace([string]$config.host_address)) {
    Fail "Config is missing host_address: $ConfigPath"
}
$hostAddress = ([string]$config.host_address).Trim()

$queryPort = 0
if (-not [int]::TryParse([string]$config.query_port, [ref]$queryPort) -or $queryPort -lt 1 -or $queryPort -gt 65535) {
    Fail "Config query_port is not a TCP port: $($config.query_port)"
}

$bonjourHint = @'
Install Apple Bonjour Print Services for Windows (support article DL999:
https://support.apple.com/kb/DL999). That package registers the Windows
service "Bonjour Service". Set the startup type to Automatic and start it.
This script does not install or start Bonjour.
'@

$bonjour = $null
try {
    $bonjour = Get-Service -Name 'Bonjour Service' -ErrorAction SilentlyContinue
} catch {
    $bonjour = $null
}
if (-not $bonjour) {
    Fail @"
Windows service 'Bonjour Service' was not found.
$bonjourHint
"@
}
if ([string]$bonjour.Status -ne 'Running') {
    Fail @"
Windows service 'Bonjour Service' is '$($bonjour.Status)', not Running.
$bonjourHint
"@
}

function Get-ProcessName([int]$ProcessId) {
    if ($ProcessId -le 0) { return 'unknown' }
    try {
        $proc = Get-Process -Id $ProcessId -ErrorAction Stop
        if ($proc.ProcessName) { return [string]$proc.ProcessName }
    } catch {
    }
    return 'unknown'
}

function Get-ListenOwners([int[]]$Ports) {
    $rows = New-Object System.Collections.Generic.List[object]
    $sawCmd = Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue
    $usedNetTcp = $false
    if ($sawCmd) {
        try {
            foreach ($port in $Ports) {
                $conns = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop)
                foreach ($conn in $conns) {
                    $rows.Add([pscustomobject]@{
                        Port = [int]$conn.LocalPort
                        ProcessId = [int]$conn.OwningProcess
                        Process = Get-ProcessName ([int]$conn.OwningProcess)
                        Address = [string]$conn.LocalAddress
                    }) | Out-Null
                }
            }
            $usedNetTcp = $true
        } catch {
            $rows.Clear()
            $usedNetTcp = $false
        }
    }
    if (-not $usedNetTcp) {
        # Foreign port 0 is a listener. The state column is localized, so do not match its text.
        $netstatLines = @(netstat.exe -ano -p tcp)
        foreach ($line in $netstatLines) {
            if ($line -notmatch '^\s*TCP\s+(\S+):(\d+)\s+\S+:0\s+\S+\s+(\d+)\s*$') { continue }
            $port = [int]$Matches[2]
            if ($Ports -notcontains $port) { continue }
            $processId = [int]$Matches[3]
            $rows.Add([pscustomobject]@{
                Port = $port
                ProcessId = $processId
                Process = Get-ProcessName $processId
                Address = $Matches[1]
            }) | Out-Null
        }
    }
    return @($rows.ToArray())
}

$owners = @(Get-ListenOwners -Ports @(3210, 3211, 3212, 3213))
if ($owners.Count -gt 0) {
    Write-Host 'TCP 3210-3213 is already in use. This script does not stop Docker or any other process.'
    foreach ($owner in ($owners | Sort-Object Port, ProcessId, Address)) {
        Write-Host ("  port {0}  pid {1}  process {2}  address {3}" -f $owner.Port, $owner.ProcessId, $owner.Process, $owner.Address)
    }
    exit 1
}

$LogDir = [System.IO.Path]::GetFullPath((Join-Path $RepoRoot 'logs'))
$LogFile = Join-Path $LogDir 'native-registry.log'
$ErrFile = Join-Path $LogDir 'native-registry.err'
if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
}
Remove-Item -LiteralPath $LogFile -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $ErrFile -Force -ErrorAction SilentlyContinue

Write-Host "Repo root:     $RepoRoot"
Write-Host "Registry exe:  $RegistryExe"
Write-Host "Config:        $ConfigPath"
Write-Host "host_address:  $hostAddress"
Write-Host "query_port:    $queryPort"
Write-Host "stdout log:    $LogFile"
Write-Host "stderr log:    $ErrFile"

function ConvertTo-PsSingleQuoted([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

$qRoot = ConvertTo-PsSingleQuoted $RepoRoot
$qExe = ConvertTo-PsSingleQuoted $RegistryExe
$qCfg = ConvertTo-PsSingleQuoted $ConfigPath
$qLog = ConvertTo-PsSingleQuoted $LogFile
$qErr = ConvertTo-PsSingleQuoted $ErrFile
$launcherBody = @"
`$Host.UI.RawUI.WindowTitle = 'nmos-cpp-registry'
Write-Host 'nmos-cpp-registry is running in this window. Close this window to stop it.'
Write-Host ('stdout: ' + $qLog)
Write-Host ('stderr: ' + $qErr)
Set-Location -LiteralPath $qRoot
& $qExe $qCfg > $qLog 2> $qErr
Write-Host ('Registry exited with code ' + `$LASTEXITCODE)
"@
$launcherBody = ($launcherBody -replace "`r", '').Replace("`n", "`r`n")
if (-not $launcherBody.EndsWith("`r`n")) {
    $launcherBody += "`r`n"
}

$tempDir = $env:TEMP
if ([string]::IsNullOrWhiteSpace($tempDir)) { $tempDir = $LogDir }
$launcherPath = Join-Path $tempDir 'nmos-reg-check-start-native-registry.ps1'
if ($launcherPath.Contains('"')) {
    Fail "Launcher path contains a double quote and cannot be passed safely: $launcherPath"
}
$utf8Bom = New-Object System.Text.UTF8Encoding $true
[System.IO.File]::WriteAllText($launcherPath, $launcherBody, $utf8Bom)

$psExe = $null
if (-not [string]::IsNullOrWhiteSpace($env:SystemRoot)) {
    $psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
}
if (-not $psExe -or -not (Test-Path -LiteralPath $psExe)) {
    $psCmd = Get-Command powershell.exe -ErrorAction SilentlyContinue
    if (-not $psCmd) {
        Fail 'powershell.exe was not found. Cannot open a registry console window.'
    }
    $psExe = $psCmd.Source
}

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $psExe
$startInfo.Arguments = '-NoExit -NoProfile -ExecutionPolicy Bypass -File "{0}"' -f $launcherPath
$startInfo.WorkingDirectory = $RepoRoot
$startInfo.UseShellExecute = $true
$startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Normal
try {
    $proc = [System.Diagnostics.Process]::Start($startInfo)
} catch {
    Fail "Could not open a console window for the registry.`n$($_.Exception.Message)"
}
if (-not $proc) {
    Fail 'Could not open a console window for the registry.'
}
Write-Host "Started with Start-Process in a new console (PID $($proc.Id)). Close that window to stop the registry."

$probeUrl = "http://127.0.0.1:$queryPort/x-nmos/query/"
Write-Host "Waiting 3 seconds, then probing $probeUrl"
Start-Sleep -Seconds 3

$probeOk = $false
$previousProgress = $ProgressPreference
$ProgressPreference = 'SilentlyContinue'
try {
    $response = Invoke-WebRequest -Uri $probeUrl -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
        $probeOk = $true
        Write-Host "Probe OK: HTTP $($response.StatusCode) $probeUrl"
    } else {
        Write-Host "Probe FAIL: HTTP $($response.StatusCode) $probeUrl"
    }
} catch {
    Write-Host "Probe FAIL: $probeUrl"
    Write-Host $_.Exception.Message
} finally {
    $ProgressPreference = $previousProgress
}

if (-not $probeOk) {
    Write-Host "The registry window was left open."
    Write-Host "stdout: $LogFile"
    Write-Host "stderr: $ErrFile"
    if (Test-Path -LiteralPath $ErrFile) {
        Write-Host '--- stderr (last 20 lines) ---'
        Get-Content -LiteralPath $ErrFile -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
    }
    exit 1
}

if (-not $RunCheck) { exit 0 }

function Get-ToolExitCode {
    if ($null -eq $LASTEXITCODE) { return 0 }
    return [int]$LASTEXITCODE
}

function Test-NmosModule([string]$Executable, [string]$PrefixArg) {
    if ([string]::IsNullOrEmpty($PrefixArg)) {
        & $Executable -c 'import nmos_reg_check' 1>$null 2>$null
    } else {
        & $Executable $PrefixArg -c 'import nmos_reg_check' 1>$null 2>$null
    }
    return ((Get-ToolExitCode) -eq 0)
}

function Test-StoreAlias([string]$PathValue) {
    return ($PathValue -like '*\WindowsApps\*')
}

$checkUrl = if ($hostAddress.Contains(':')) { "http://[$hostAddress]:$queryPort" } else { "http://${hostAddress}:$queryPort" }
Write-Host "Check: nmos-reg-check --registry $checkUrl --lang zh"

$checkCode = $null
Push-Location -LiteralPath $RepoRoot
try {
    $onPath = Get-Command nmos-reg-check -ErrorAction SilentlyContinue
    $pathSource = if ($onPath) { [string]$onPath.Source } else { '' }
    if ($onPath -and -not (Test-StoreAlias $pathSource)) {
        Write-Host "Using nmos-reg-check from PATH ($pathSource)"
        & nmos-reg-check --registry $checkUrl --lang zh
        $checkCode = Get-ToolExitCode
    } else {
        $candidates = New-Object System.Collections.Generic.List[object]
        $venvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $venvPython) {
            $candidates.Add([pscustomobject]@{ Exe = $venvPython; Prefix = '' }) | Out-Null
        }
        $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pythonCmd -and $pythonCmd.Source -and -not (Test-StoreAlias ([string]$pythonCmd.Source))) {
            $candidates.Add([pscustomobject]@{ Exe = [string]$pythonCmd.Source; Prefix = '' }) | Out-Null
        }
        $pyCmd = Get-Command py -ErrorAction SilentlyContinue
        if ($pyCmd -and $pyCmd.Source -and -not (Test-StoreAlias ([string]$pyCmd.Source))) {
            $candidates.Add([pscustomobject]@{ Exe = [string]$pyCmd.Source; Prefix = '-3' }) | Out-Null
        }

        foreach ($candidateTool in $candidates) {
            if (Test-NmosModule $candidateTool.Exe $candidateTool.Prefix) {
                if ([string]::IsNullOrEmpty($candidateTool.Prefix)) {
                    Write-Host "Using $($candidateTool.Exe) -m nmos_reg_check"
                    & $candidateTool.Exe -m nmos_reg_check --registry $checkUrl --lang zh
                } else {
                    Write-Host "Using $($candidateTool.Exe) $($candidateTool.Prefix) -m nmos_reg_check"
                    & $candidateTool.Exe $candidateTool.Prefix -m nmos_reg_check --registry $checkUrl --lang zh
                }
                $checkCode = Get-ToolExitCode
                break
            }
        }
    }
} finally {
    Pop-Location
}

if ($null -ne $checkCode) { exit $checkCode }

Write-Host 'WARNING: nmos-reg-check was not found on PATH, and python -m nmos_reg_check is not available from the repo root (.venv, then python, then py -3). Skipping --check. The registry is still running.'
exit 0
