<#
.SYNOPSIS
    One-time developer setup: Python environment with the locked dependencies, web dependencies, and a .env file.

.DESCRIPTION
    * API: creates services\api\.venv (Python 3.12 preferred) and installs services\api\requirements-dev.lock (sha256
      hashes verified; plain pip, or uv when it is on PATH and can also fetch Python 3.12), then the API itself in
      editable mode.
    * Web: runs `npm ci` in apps\web (Node 22.12 or newer).
    * .env: copies .env.example to .env when it does not exist (development defaults, no secrets).
    Nothing is installed globally. Every step fails with a plain explanation when a tool is missing.

.PARAMETER SkipApi   Do not set up the Python environment.
.PARAMETER SkipWeb   Do not install the web dependencies.
.PARAMETER Force     Recreate the Python environment and reinstall the web dependencies.
.PARAMETER VenvDir   Python environment location. Default: services\api\.venv (or $env:SPARTA_VENV).
.PARAMETER DryRun    Print what would run and change nothing.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1

.NOTES
    Behind a corporate package mirror: set $env:PIP_INDEX_URL (pip and uv) and the npm registry before running.
#>
[CmdletBinding()]
param(
    [switch]$SkipApi,
    [switch]$SkipWeb,
    [switch]$Force,
    [string]$VenvDir = '',
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot 'lib.ps1')
$script:IsDryRun = [bool]$DryRun
Set-IndexEnvironment

function Initialize-Api {
    $venv = Get-VenvDir $VenvDir
    $lock = Join-Path $script:ApiDir 'requirements-dev.lock'
    if (-not (Test-Path $lock)) {
        Fail ("Missing " + $lock) @('Run this script from a complete checkout of the repository.')
    }

    $uvOnPath = Test-Command 'uv'
    $python = Find-Python
    Write-Note ("uv on PATH: " + $uvOnPath)
    if ($python) { Write-Note ("Python found: " + $python.Exe + ' ' + ($python.PrefixArgs -join ' ') + " (" + $python.Version + ")") }
    else { Write-Note 'Python 3.12+ found: no' }

    $existing = Get-VenvPython $venv
    if ($existing -and -not $Force) {
        Write-Ok ("Python environment already exists: " + $venv + " (use -Force to recreate it)")
    }
    else {
        if (-not $uvOnPath -and -not $python) {
            Fail 'Python 3.12 or newer was not found, and uv is not installed.' @(
                'Install Python 3.12 from https://www.python.org/downloads/ (or: winget install Python.Python.3.12), then open a new terminal.',
                'Alternatively install uv (https://docs.astral.sh/uv/getting-started/installation/); it can download Python 3.12 itself.'
            )
        }
        if ($existing -and $Force -and -not $script:IsDryRun) {
            if (-not (Test-Path (Join-Path $venv 'pyvenv.cfg'))) { Fail ($venv + " does not look like a Python environment; refusing to delete it.") }
            Write-Step ("Removing " + $venv)
            Remove-Item -Recurse -Force -LiteralPath $venv
        }
        Write-Step ("Creating the Python environment at " + $venv)
        if ($uvOnPath) {
            Invoke-Native 'uv' @('venv', '--python', '3.12', $venv) $script:ApiDir -Hints @(
                'uv could not create the environment. It downloads Python 3.12 when none is installed: check your network or proxy.'
            )
        }
        else {
            if ($python.Version -ne [version]'3.12') {
                Write-Warn ("Python " + $python.Version + " is not the tested version (3.12). Locked packages may lack wheels for it; install Python 3.12 if installation fails.")
            }
            Invoke-Native $python.Exe (@($python.PrefixArgs) + @('-m', 'venv', $venv)) $script:ApiDir -Hints @(
                'The venv module failed. On Debian/Ubuntu install python3-venv; on Windows reinstall Python with the standard library option.'
            )
        }
    }

    if ($script:IsDryRun -and -not (Get-VenvPython $venv)) {
        $venvPython = Join-Path $venv 'Scripts\python.exe'
    }
    else {
        $venvPython = Require-VenvPython $venv
    }

    # The lock carries sha256 hashes only, so plain pip (hash-checking mode) and uv both install it. uv is used when present.
    if ($uvOnPath) {
        Write-Step 'Installing the locked dependencies with uv (services\api\requirements-dev.lock)'
        Invoke-Native 'uv' @('pip', 'install', '--python', $venvPython, '-r', 'requirements-dev.lock') $script:ApiDir -Hints @(
            'Dependency installation failed. If pypi.org is unreachable, set $env:PIP_INDEX_URL to a mirror and retry.'
        )
        Write-Step 'Installing the API package in editable mode'
        Invoke-Native 'uv' @('pip', 'install', '--python', $venvPython, '--no-deps', '-e', '.') $script:ApiDir
    }
    else {
        Write-Step 'Installing the locked dependencies with pip (services\api\requirements-dev.lock, hashes verified)'
        Invoke-Native $venvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'requirements-dev.lock') $script:ApiDir -Hints @(
            'Dependency installation failed. If pypi.org is unreachable, set $env:PIP_INDEX_URL to a mirror and retry.',
            'A hash mismatch means the lock file and the package index disagree: do not bypass it, regenerate the lock.'
        )
        Write-Step 'Installing the API package in editable mode'
        Invoke-Native $venvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '--no-deps', '-e', '.') $script:ApiDir
    }

    if (-not $script:IsDryRun) {
        Invoke-Native $venvPython @('-m', 'sparta', '--help') $script:ApiDir -Hints @('The API package did not import after installation.')
        Write-Ok ("API environment ready: " + $venvPython)
    }
}

function Initialize-Web {
    if (-not (Test-Path (Join-Path $script:WebDir 'package.json'))) {
        Write-Warn 'apps\web\package.json not found: skipping the web dependencies.'
        return
    }
    Require-Node
    $npm = Get-NpmCommand
    $modules = Join-Path $script:WebDir 'node_modules'
    if ((Test-Path $modules) -and -not $Force) {
        Write-Ok 'Web dependencies already installed (use -Force to reinstall).'
        return
    }
    Write-Step 'Installing the web dependencies (npm ci)'
    Invoke-Native $npm @('ci') $script:WebDir -Hints @(
        'npm ci failed. Behind a corporate mirror, set the npm registry (npm config set registry <url>) and retry.',
        'The lockfile must point at registry.npmjs.org: run `npm run lock:check` in apps\web.'
    )
    if (-not $script:IsDryRun) { Write-Ok 'Web dependencies installed.' }
}

function Initialize-EnvFile {
    $envFile = Join-Path $script:RepoRoot '.env'
    $example = Join-Path $script:RepoRoot '.env.example'
    if (Test-Path $envFile) {
        Write-Ok '.env already exists (left untouched).'
    }
    elseif ($script:IsDryRun) {
        Write-Host '[dry-run] copy .env.example to .env'
    }
    else {
        Copy-Item -LiteralPath $example -Destination $envFile
        Write-Ok 'Created .env from .env.example (development defaults, no secrets).'
    }
}

Invoke-Script {
    Write-Step 'Checking prerequisites'
    if ($DryRun) { Write-Note 'Dry run: nothing will be changed.' }
    if (Test-Command 'docker') { Write-Note 'Docker: found (needed only for docker compose and the container build)' }
    else { Write-Note 'Docker: not found (optional; the simulator runs without it)' }
    if (Test-Command 'git') { Write-Note 'Git: found' } else { Write-Warn 'Git was not found on PATH.' }

    if (-not $SkipApi) { Initialize-Api }
    if (-not $SkipWeb) { Initialize-Web }
    Initialize-EnvFile

    Write-Host ''
    Write-Ok 'Setup finished. Next steps:'
    Write-Note 'scripts\dev.ps1            start the API (SQLite, simulator) and the web app'
    Write-Note 'scripts\dev.ps1 -Docker    same, with PostgreSQL and Redis from docker compose'
    Write-Note 'scripts\check.ps1          run the same checks as CI'
    Write-Note 'Simulator Lab: http://localhost:3000/simulator'
}
