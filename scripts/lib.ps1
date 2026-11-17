# Shared helpers for the Sparta PowerShell scripts (Windows PowerShell 5.1 and PowerShell 7+).
# Dot-source it from a script in this folder:   . (Join-Path $PSScriptRoot 'lib.ps1')
# Keep this folder ASCII-only: Windows PowerShell 5.1 reads BOM-less files as ANSI and would garble other characters.

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$script:ApiDir = Join-Path $script:RepoRoot 'services\api'
$script:WebDir = Join-Path $script:RepoRoot 'apps\web'
$script:AndroidDir = Join-Path $script:RepoRoot 'apps\android'
$script:IsDryRun = $false   # NOT named DryRun: scripts have a -DryRun parameter, and a same-named script variable would be overwritten

$script:IsWin = ([System.Environment]::OSVersion.Platform -eq 'Win32NT')

function Write-Step([string]$Message) { Write-Host ("==> " + $Message) -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host ("[ok]   " + $Message) -ForegroundColor Green }
function Write-Note([string]$Message) { Write-Host ("       " + $Message) -ForegroundColor DarkGray }
function Write-Warn([string]$Message) { Write-Host ("[warn] " + $Message) -ForegroundColor Yellow }

# Stop with an actionable message instead of a stack trace. Hints are printed as a short bullet list.
function Fail([string]$Message, [string[]]$Hints = @()) {
    $ex = New-Object System.InvalidOperationException $Message
    $ex.Data['SpartaHints'] = ($Hints -join "`n")
    throw $ex
}

# Runs the script body; prints errors as a message plus hints (no stack trace unless SPARTA_DEBUG=1) and exits 1.
function Invoke-Script([scriptblock]$Main) {
    try {
        & $Main
    }
    catch {
        $ex = $_.Exception
        Write-Host ''
        Write-Host ("ERROR: " + $ex.Message) -ForegroundColor Red
        $hints = $null
        if ($ex.Data -and $ex.Data.Contains('SpartaHints')) { $hints = [string]$ex.Data['SpartaHints'] }
        if ($hints) {
            foreach ($line in ($hints -split "`n")) { Write-Host ("  - " + $line) -ForegroundColor Yellow }
        }
        else {
            Write-Host '  - Re-run with $env:SPARTA_DEBUG=1 for the full error record.' -ForegroundColor Yellow
        }
        if ($env:SPARTA_DEBUG) { Write-Host $_.ScriptStackTrace }
        exit 1
    }
}

function Test-Command([string]$Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

# Runs a native command, streams its output, and turns a non-zero exit code into a clear failure.
function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [string[]]$Arguments = @(),
        [string]$WorkDir = $script:RepoRoot,
        [string[]]$Hints = @()
    )
    $shown = (($Exe + ' ' + ($Arguments -join ' ')).Trim())
    if ($script:IsDryRun) {
        Write-Host ("[dry-run] (" + $WorkDir + ") " + $shown)
        return
    }
    Push-Location $WorkDir
    $previousPreference = $ErrorActionPreference
    # Native tools print progress to stderr (uv, pip, alembic): that must not be a terminating error; the exit code decides.
    $ErrorActionPreference = 'Continue'
    try {
        & $Exe @Arguments | Out-Host
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
        Pop-Location
    }
    if ($code -ne 0) {
        Fail ("Command failed with exit code " + $code + ": " + $shown) $Hints
    }
}

function Get-PythonVersion {
    param([string]$Exe, [string[]]$PrefixArgs = @())
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $Exe @PrefixArgs -c "import sys; print('{}.{}'.format(*sys.version_info[:2]))" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $text = ("" + $out).Trim()
        if ($text -match '^\d+\.\d+$') { return [version]$text }
        return $null
    }
    catch { return $null }
    finally { $ErrorActionPreference = $previous }
}

# Finds a Python (SPARTA_PYTHON, the py launcher, python3.12, python3, python). Exactly 3.12 (what CI and the lock use)
# wins; any newer 3.x is accepted as a fallback because pyproject.toml says >=3.12. Returns @{ Exe; PrefixArgs; Version }.
function Find-Python {
    $candidates = @()
    if ($env:SPARTA_PYTHON) { $candidates += , @($env:SPARTA_PYTHON, @()) }
    if (Test-Command 'py') { $candidates += , @('py', @('-3.12')) }
    foreach ($name in 'python3.12', 'python3', 'python') {
        if (Test-Command $name) { $candidates += , @($name, @()) }
    }
    $fallback = $null
    foreach ($c in $candidates) {
        $version = Get-PythonVersion -Exe $c[0] -PrefixArgs $c[1]
        if (-not $version -or $version -lt [version]'3.12') { continue }
        $found = @{ Exe = $c[0]; PrefixArgs = $c[1]; Version = $version }
        if ($version -eq [version]'3.12') { return $found }
        if (-not $fallback) { $fallback = $found }
    }
    return $fallback
}

function Get-VenvDir([string]$Override = '') {
    if ($Override) { return $Override }
    if ($env:SPARTA_VENV) { return $env:SPARTA_VENV }
    return (Join-Path $script:ApiDir '.venv')
}

function Get-VenvPython([string]$VenvDir) {
    $relative = if ($script:IsWin) { 'Scripts\python.exe' } else { 'bin/python' }
    $path = Join-Path $VenvDir $relative
    if (Test-Path $path) { return $path }
    return $null
}

function Require-VenvPython([string]$VenvDir) {
    $python = Get-VenvPython $VenvDir
    if (-not $python) {
        Fail ("The Python environment " + $VenvDir + " does not exist yet.") @(
            'Run scripts\bootstrap.ps1 once (it creates the environment and installs the locked dependencies).',
            'Using another location? Set $env:SPARTA_VENV to that environment folder.'
        )
    }
    return $python
}

function Get-NodeVersion {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & node --version 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $text = ("" + $out).Trim().TrimStart('v')
        if ($text -match '^(\d+)\.(\d+)') { return [version]("{0}.{1}" -f $Matches[1], $Matches[2]) }
        return $null
    }
    catch { return $null }
    finally { $ErrorActionPreference = $previous }
}

function Require-Node {
    if (-not (Test-Command 'node')) {
        Fail 'Node.js was not found on PATH.' @(
            'Install Node.js 22.12 or newer from https://nodejs.org (or: winget install OpenJS.NodeJS.LTS), then open a new terminal.',
            'The web app (apps/web) needs it; the API does not.'
        )
    }
    $version = Get-NodeVersion
    if (-not $version -or $version -lt [version]'22.12') {
        Fail ("Node.js 22.12 or newer is required (found " + $version + ").") @('Upgrade Node.js, then open a new terminal.')
    }
}

function Get-NpmCommand {
    $cmd = Get-Command 'npm.cmd' -ErrorAction SilentlyContinue
    if (-not $cmd) { $cmd = Get-Command 'npm' -ErrorAction SilentlyContinue }
    if (-not $cmd) { Fail 'npm was not found on PATH.' @('Install Node.js (it ships npm), then open a new terminal.') }
    return $cmd.Source
}

function Require-Docker {
    if (-not (Test-Command 'docker')) {
        Fail 'Docker was not found on PATH.' @(
            'Install Docker Desktop (https://www.docker.com/products/docker-desktop) or Docker Engine with the compose plugin.',
            'No Docker? The simulator also runs without it: use scripts\dev.ps1 (SQLite, in-process state).'
        )
    }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & docker info *> $null; $code = $LASTEXITCODE } catch { $code = 1 } finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) {
        Fail 'The Docker engine is not running.' @('Start Docker Desktop (or the docker service) and wait until it reports it is running, then retry.')
    }
}

# Loads KEY=VALUE lines from a .env file into this process. Variables that are already set win, like pydantic-settings does.
function Import-DotEnv([string]$Path) {
    if (-not (Test-Path $Path)) { return 0 }
    $count = 0
    foreach ($raw in (Get-Content -LiteralPath $Path)) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith('#')) { continue }
        if ($line.StartsWith('export ')) { $line = $line.Substring(7).TrimStart() }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { continue }
        $key = $line.Substring(0, $eq).Trim()
        $value = $line.Substring($eq + 1).Trim()
        if ($value.Length -ge 2 -and (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        elseif ($value -match '^(.*?)\s+#') {
            $value = $Matches[1]
        }
        if ($value -eq '') {
            Write-Warn ($key + " is empty in " + (Split-Path -Leaf $Path) + " and was ignored (an empty value counts as set for the API). Comment the line out instead.")
            continue
        }
        if (-not [System.Environment]::GetEnvironmentVariable($key, 'Process')) {
            [System.Environment]::SetEnvironmentVariable($key, $value, 'Process')
            $count++
        }
    }
    return $count
}

function Wait-Http {
    param([string]$Url, [int]$TimeoutSeconds = 60)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) { return $true }
        }
        catch { }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# Stops a process and everything it started (PID based).
function Stop-ProcessTree([int]$ProcessId) {
    if ($script:IsWin) {
        $children = @(Get-CimInstance Win32_Process -Filter ("ParentProcessId = " + $ProcessId) -ErrorAction SilentlyContinue)
        foreach ($child in $children) { Stop-ProcessTree ([int]$child.ProcessId) }
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Set-DefaultEnv([string]$Name, [string]$Value) {
    if (-not [System.Environment]::GetEnvironmentVariable($Name, 'Process')) {
        [System.Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
    }
}

# Mirrors the pip index into uv so a corporate mirror set through PIP_INDEX_URL also works for the locked install.
function Set-IndexEnvironment {
    if ($env:PIP_INDEX_URL) { Set-DefaultEnv 'UV_DEFAULT_INDEX' $env:PIP_INDEX_URL }
    Set-DefaultEnv 'PYTHONUTF8' '1'
}
