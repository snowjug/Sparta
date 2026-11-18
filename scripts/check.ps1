<#
.SYNOPSIS
    Runs the same checks as CI, locally, and prints a PASS/FAIL summary. Every step runs even if an earlier one failed.

.DESCRIPTION
    Backend (services\api): ruff check, ruff format --check, mypy, pytest, OpenAPI drift check, evaluation smoke
                           (python -m sparta evaluate --split dev), and with -Security also pip-audit and bandit.
    Web (apps\web):         lint, typecheck, unit tests, lockfile check, production build.
    Exit code 0 only when every step passed.

.PARAMETER Api       Check only the backend.
.PARAMETER Web       Check only the web app.
.PARAMETER Fast      Skip the slow steps: evaluation, web build and the security audits.
.PARAMETER Security  Also run pip-audit (network needed) and bandit.
.PARAMETER VenvDir   Python environment (default services\api\.venv or $env:SPARTA_VENV).
.PARAMETER DryRun    Print the commands without running them.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\check.ps1 -Fast
#>
[CmdletBinding()]
param(
    [switch]$Api,
    [switch]$Web,
    [switch]$Fast,
    [switch]$Security,
    [string]$VenvDir = '',
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot 'lib.ps1')
$script:IsDryRun = [bool]$DryRun
Set-IndexEnvironment

$script:Results = New-Object System.Collections.ArrayList

function Invoke-Step([string]$Name, [scriptblock]$Body) {
    Write-Step $Name
    $started = Get-Date
    $result = 'PASS'
    try { & $Body }
    catch {
        $result = 'FAIL'
        Write-Host ('       ' + $_.Exception.Message) -ForegroundColor Red
    }
    if ($script:IsDryRun) { $result = 'DRY' }
    $seconds = [int]((Get-Date) - $started).TotalSeconds
    [void]$script:Results.Add([pscustomobject]@{ Step = $Name; Result = $result; Seconds = $seconds })
}

function Skip-Step([string]$Name, [string]$Reason) {
    Write-Note ('skipped: ' + $Name + ' (' + $Reason + ')')
    [void]$script:Results.Add([pscustomobject]@{ Step = $Name; Result = 'SKIP'; Seconds = 0 })
}

Invoke-Script {
    $runApi = [bool]$Api
    $runWeb = [bool]$Web
    if (-not ($runApi -or $runWeb)) { $runApi = $true; $runWeb = $true }

    if ($runApi) {
        $venv = Get-VenvDir $VenvDir
        $python = if ($script:IsDryRun) { Join-Path $venv 'Scripts\python.exe' } else { Require-VenvPython $venv }
        $pythonArgs = @('-X', 'utf8', '-m')
        # CI runs with none of the application settings in the environment. Do the same here (this process only), so a
        # stray SPARTA_* variable from your shell cannot change a test or the contract export.
        $keep = @('SPARTA_TEST_POSTGRES_URL', 'SPARTA_TEST_REDIS_URL', 'SPARTA_VENV', 'SPARTA_PYTHON', 'SPARTA_DEBUG')
        $stray = @(Get-ChildItem Env: | Where-Object { ($_.Name -like 'SPARTA_*' -or $_.Name -eq 'TELEPHONY_PROVIDER') -and ($keep -notcontains $_.Name) } | ForEach-Object { $_.Name })
        foreach ($name in $stray) { Remove-Item -LiteralPath ('Env:' + $name) }
        if ($stray.Count -gt 0) { Write-Note ('Ignoring ' + $stray.Count + ' SPARTA_* variable(s) from your shell, as CI does.') }
        Invoke-Step 'api: ruff check' { Invoke-Native $python ($pythonArgs + @('ruff', 'check', '.')) $script:ApiDir }
        Invoke-Step 'api: ruff format --check' { Invoke-Native $python ($pythonArgs + @('ruff', 'format', '--check', '.')) $script:ApiDir }
        Invoke-Step 'api: mypy' { Invoke-Native $python ($pythonArgs + @('mypy', 'src')) $script:ApiDir }
        Invoke-Step 'api: pytest' { Invoke-Native $python ($pythonArgs + @('pytest', 'tests', '-q')) $script:ApiDir }
        Invoke-Step 'api: OpenAPI contract is current' { Invoke-Native $python ($pythonArgs + @('sparta', 'openapi', '--check')) $script:ApiDir -Hints @('Regenerate it: python -m sparta openapi (from services\api) and commit packages\contracts\openapi.json.') }
        if ($Fast) { Skip-Step 'api: evaluation (dev split)' '-Fast' }
        else { Invoke-Step 'api: evaluation (dev split)' { Invoke-Native $python ($pythonArgs + @('sparta', 'evaluate', '--split', 'dev')) $script:ApiDir -Hints @('A non-zero exit means a safety invariant failed: do not tune on the held-out test split.') } }
        if ($Security -and -not $Fast) {
            Invoke-Step 'api: pip-audit (the lock file; needs network)' { Invoke-Native $python ($pythonArgs + @('pip_audit', '-r', 'requirements-dev.lock', '--no-deps', '--disable-pip', '--progress-spinner', 'off')) $script:ApiDir -Hints @('Needs network access to the advisory service. A finding means a pinned version is vulnerable: bump it in requirements-dev.lock.') }
            Invoke-Step 'api: bandit' { Invoke-Native $python ($pythonArgs + @('bandit', '-q', '-c', 'pyproject.toml', '-r', 'src')) $script:ApiDir }
        }
        else { Skip-Step 'api: pip-audit and bandit' 'use -Security (not with -Fast)' }
    }

    if ($runWeb) {
        if (-not (Test-Path (Join-Path $script:WebDir 'package.json'))) { Skip-Step 'web: all' 'apps\web\package.json not found' }
        else {
            if (-not $script:IsDryRun) {
                Require-Node
                if (-not (Test-Path (Join-Path $script:WebDir 'node_modules'))) { Fail 'The web dependencies are not installed.' @('Run scripts\bootstrap.ps1 (or `npm ci` in apps\web), or use -Api.') }
            }
            $npm = if ($script:IsDryRun) { 'npm' } else { Get-NpmCommand }
            Invoke-Step 'web: lockfile has no mirror URLs' { Invoke-Native $npm @('run', 'lock:check') $script:WebDir }
            Invoke-Step 'web: eslint' { Invoke-Native $npm @('run', 'lint') $script:WebDir }
            Invoke-Step 'web: typecheck' { Invoke-Native $npm @('run', 'typecheck') $script:WebDir }
            Invoke-Step 'web: unit tests' { Invoke-Native $npm @('test') $script:WebDir }
            if ($Fast) { Skip-Step 'web: production build' '-Fast' }
            else { Invoke-Step 'web: production build' { Invoke-Native $npm @('run', 'build') $script:WebDir } }
        }
    }

    Write-Host ''
    Write-Host 'Summary' -ForegroundColor Cyan
    $script:Results | Format-Table -AutoSize | Out-Host
    $failed = @($script:Results | Where-Object { $_.Result -eq 'FAIL' })
    if ($failed.Count -gt 0) {
        Fail ($failed.Count.ToString() + ' check(s) failed.') @('Scroll up for the output of each failing step.')
    }
    if ($script:IsDryRun) { Write-Ok 'Dry run complete: nothing was executed.' } else { Write-Ok 'All checks passed.' }
}
