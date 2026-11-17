<#
.SYNOPSIS
    Task runner for Windows: the same targets as the Makefile, without needing `make`.

.DESCRIPTION
    powershell -ExecutionPolicy Bypass -File scripts\tasks.ps1 <task> [options]

    help          list the tasks
    bootstrap     create the Python environment, install web dependencies, create .env      (scripts\bootstrap.ps1)
    dev           run API + web                       (-Docker adds PostgreSQL/Redis)        (scripts\dev.ps1)
    api           run only the API                                                           (scripts\dev.ps1 -ApiOnly)
    web           run only the web app                                                       (scripts\dev.ps1 -WebOnly)
    test          backend + web unit tests                                                   (scripts\test.ps1)
    check         everything CI checks (-Fast skips slow steps, -Security adds audits)       (scripts\check.ps1)
    smoke         smoke-test a running API (health, readiness, simulator call)              (scripts\smoke.ps1)
    lint          ruff check + ruff format --check (+ eslint when the web dependencies exist)
    typecheck     mypy (+ tsc for the web app)
    format        ruff format + ruff check --fix
    migrate       apply database migrations (uses SPARTA_DATABASE_URL)
    seed          create the development owner
    openapi       regenerate packages\contracts\openapi.json
    openapi-check fail when the committed contract is stale
    eval          run the evaluation on the dev split (never tune on the test split)
    keygen        print fresh SPARTA_DATA_KEYS / SPARTA_PEPPER / SPARTA_WEBHOOK_SECRET values
    docker-build  build the container images (-Tag sets the API image name)
    lock          regenerate the hash-pinned image locks requirements*.lock (needs network)  (scripts\lock.ps1)
    verify-locks  check that every hash in requirements*.lock is published on pypi.org (needs network)
    compose-up    docker compose up -d --build        compose-down   docker compose down (-Volumes deletes data)
    clean         remove caches and build output (keeps the virtual environment, node_modules and var\)

.PARAMETER Task      One of the tasks above.
.PARAMETER Docker    dev: use docker compose for PostgreSQL and Redis.
.PARAMETER Fast      check: skip evaluation, web build and security audits.
.PARAMETER Security  check: also run pip-audit and bandit.
.PARAMETER Volumes   compose-down: also delete the data volumes.
.PARAMETER ApiPort   dev/api: API port.
.PARAMETER WebPort   dev/web: web port.
.PARAMETER VenvDir   Python environment (default services\api\.venv or $env:SPARTA_VENV).
.PARAMETER Tag       docker-build: API image tag (default sparta-api).
.PARAMETER DryRun    Print what would run.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Task = 'help',
    [switch]$Docker,
    [switch]$Fast,
    [switch]$Security,
    [switch]$Volumes,
    [int]$ApiPort = 0,
    [int]$WebPort = 0,
    [string]$VenvDir = '',
    [string]$Tag = 'sparta-api',
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot 'lib.ps1')
$script:IsDryRun = [bool]$DryRun
Set-IndexEnvironment

function Get-Python {
    $venv = Get-VenvDir $VenvDir
    if ($script:IsDryRun) { return (Join-Path $venv 'Scripts\python.exe') }
    return (Require-VenvPython $venv)
}

function Invoke-Sparta([string[]]$CliArgs, [string[]]$Hints = @()) {
    Invoke-Native (Get-Python) (@('-X', 'utf8', '-m', 'sparta') + $CliArgs) $script:ApiDir -Hints $Hints
}

function Invoke-Delegate([string]$ScriptName, [hashtable]$Splat) {
    & (Join-Path $PSScriptRoot $ScriptName) @Splat
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

function Remove-Artifacts {
    $targets = New-Object System.Collections.ArrayList
    foreach ($name in '.pytest_cache', '.mypy_cache', '.ruff_cache', '.hypothesis') { [void]$targets.Add((Join-Path $script:ApiDir $name)) }
    foreach ($name in '.next', 'test-results', 'playwright-report', 'coverage') { [void]$targets.Add((Join-Path $script:WebDir $name)) }
    foreach ($folder in 'src', 'tests', 'migrations') {
        $path = Join-Path $script:ApiDir $folder
        if (Test-Path $path) {
            Get-ChildItem -LiteralPath $path -Recurse -Directory -Filter '__pycache__' -ErrorAction SilentlyContinue | ForEach-Object { [void]$targets.Add($_.FullName) }
        }
    }
    $removed = 0
    foreach ($target in $targets) {
        if (-not (Test-Path -LiteralPath $target)) { continue }
        if (-not $target.StartsWith($script:RepoRoot)) { continue }   # never delete outside the repository
        if ($script:IsDryRun) { Write-Host ('[dry-run] remove ' + $target) }
        else { Remove-Item -Recurse -Force -LiteralPath $target }
        $removed++
    }
    Write-Ok ($removed.ToString() + ' item(s) ' + $(if ($script:IsDryRun) { 'would be removed' } else { 'removed' }) + ' (the virtual environment, node_modules and services\api\var were left alone).')
}

Invoke-Script {
    switch ($Task.ToLowerInvariant()) {
        'help' {
            Get-Help $PSCommandPath -Detailed | Out-Host
        }
        'bootstrap' { Invoke-Delegate 'bootstrap.ps1' @{ VenvDir = $VenvDir; DryRun = $DryRun } }
        'dev' { Invoke-Delegate 'dev.ps1' @{ Docker = $Docker; ApiPort = $ApiPort; WebPort = $WebPort; VenvDir = $VenvDir; DryRun = $DryRun } }
        'api' { Invoke-Delegate 'dev.ps1' @{ ApiOnly = $true; Docker = $Docker; ApiPort = $ApiPort; VenvDir = $VenvDir; DryRun = $DryRun } }
        'web' { Invoke-Delegate 'dev.ps1' @{ WebOnly = $true; WebPort = $WebPort; VenvDir = $VenvDir; DryRun = $DryRun } }
        'test' { Invoke-Delegate 'test.ps1' @{ VenvDir = $VenvDir; DryRun = $DryRun } }
        'check' { Invoke-Delegate 'check.ps1' @{ Fast = $Fast; Security = $Security; VenvDir = $VenvDir; DryRun = $DryRun } }
        'smoke' { Invoke-Delegate 'smoke.ps1' @{} }
        'lock' { Invoke-Delegate 'lock.ps1' @{ DryRun = $DryRun } }
        'verify-locks' {
            $python = Find-Python
            if (-not $python) { Fail 'Python 3.12 or newer was not found.' @('Install Python 3.12 (the check uses only the standard library).') }
            Invoke-Native $python.Exe (@($python.PrefixArgs) + @((Join-Path $PSScriptRoot 'verify_locks.py'))) $script:RepoRoot -Hints @(
                'Exit status 1: a lock lists a hash that pypi.org does not publish (do not commit it). Exit status 2: pypi.org could not be reached.'
            )
        }
        'lint' {
            $py = Get-Python
            Invoke-Native $py @('-m', 'ruff', 'check', '.') $script:ApiDir
            Invoke-Native $py @('-m', 'ruff', 'format', '--check', '.') $script:ApiDir
            if (Test-Path (Join-Path $script:WebDir 'node_modules')) { Invoke-Native (Get-NpmCommand) @('run', 'lint') $script:WebDir }
            else { Write-Note 'Web dependencies are not installed: skipping eslint.' }
        }
        'typecheck' {
            Invoke-Native (Get-Python) @('-m', 'mypy', 'src') $script:ApiDir
            if (Test-Path (Join-Path $script:WebDir 'node_modules')) { Invoke-Native (Get-NpmCommand) @('run', 'typecheck') $script:WebDir }
            else { Write-Note 'Web dependencies are not installed: skipping tsc.' }
        }
        'format' {
            $py = Get-Python
            Invoke-Native $py @('-m', 'ruff', 'format', '.') $script:ApiDir
            Invoke-Native $py @('-m', 'ruff', 'check', '--fix', '.') $script:ApiDir
        }
        'migrate' { Invoke-Sparta @('migrate') @('The "error:" line above says which dependency is unreachable and what to start (docker compose up -d postgres redis).') }
        'seed' { Invoke-Sparta @('seed') }
        'openapi' { Invoke-Sparta @('openapi') }
        'openapi-check' { Invoke-Sparta @('openapi', '--check') }
        'eval' { Invoke-Sparta @('evaluate', '--split', 'dev') }
        'keygen' {
            Write-Note 'Nothing is stored: copy the three lines into your secret store (never into a committed file).'
            Invoke-Sparta @('keygen')
        }
        'docker-build' {
            if (-not $script:IsDryRun) { Require-Docker }
            $apiBuild = @('build', '-t', $Tag)
            if ($env:PIP_INDEX_URL) { $apiBuild += @('--build-arg', ('PIP_INDEX_URL=' + $env:PIP_INDEX_URL)) }
            Invoke-Native 'docker' ($apiBuild + @((Join-Path $script:RepoRoot 'services\api'))) $script:RepoRoot -Hints @('Behind a corporate mirror set $env:PIP_INDEX_URL to it (the package hashes in requirements*.lock still apply).')
            $webBuild = @('build', '-t', 'sparta-web')
            if ($env:NPM_REGISTRY) { $webBuild += @('--build-arg', ('NPM_REGISTRY=' + $env:NPM_REGISTRY)) }
            Invoke-Native 'docker' ($webBuild + @($script:WebDir)) $script:RepoRoot -Hints @('The web build runs npm ci inside the container: behind a TLS-inspecting proxy set $env:NPM_REGISTRY to your npm mirror (see docs\DEPLOYMENT.md, Troubleshooting).')
        }
        'compose-up' {
            if (-not $script:IsDryRun) { Require-Docker }
            Invoke-Native 'docker' @('compose', 'up', '-d', '--build') $script:RepoRoot -Hints @('To start only the backend run: docker compose up -d --build postgres redis api')
        }
        'compose-down' {
            if (-not $script:IsDryRun) { Require-Docker }
            $downArgs = @('compose', 'down')
            if ($Volumes) { $downArgs += '-v' }
            Invoke-Native 'docker' $downArgs $script:RepoRoot
        }
        'clean' { Remove-Artifacts }
        default {
            Fail ("Unknown task '" + $Task + "'.") @('Run `scripts\tasks.ps1 help` for the list of tasks.')
        }
    }
}
