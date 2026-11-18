<#
.SYNOPSIS
    Runs the Sparta development stack on this machine: API (simulator providers) and web app.

.DESCRIPTION
    1. Loads .env (variables already set in your shell win).
    2. -Docker: starts PostgreSQL and Redis with `docker compose up -d --wait` and points the API at them.
       Without -Docker the API uses SQLite and in-process shared state (fine for one developer).
    3. Applies migrations and creates the development owner.
    4. Starts the API on 127.0.0.1:<ApiPort> and the web dev server on <WebPort>, waits for /healthz, prints the URLs.
    Ctrl+C stops everything this script started (and nothing else).

.PARAMETER Docker     Use docker compose for PostgreSQL and Redis.
.PARAMETER ApiOnly    Start only the API.
.PARAMETER WebOnly    Start only the web app (an API must already be running).
.PARAMETER ApiPort    API port (default $env:SPARTA_API_PORT or 8000).
.PARAMETER WebPort    Web port (default $env:SPARTA_WEB_PORT or 3000).
.PARAMETER VenvDir    Python environment (default services\api\.venv or $env:SPARTA_VENV).
.PARAMETER DryRun     Print the plan (commands and environment) without starting anything.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
    powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -Docker -ApiPort 8001
#>
[CmdletBinding()]
param(
    [switch]$Docker,
    [switch]$ApiOnly,
    [switch]$WebOnly,
    [int]$ApiPort = 0,
    [int]$WebPort = 0,
    [string]$VenvDir = '',
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot 'lib.ps1')
$script:IsDryRun = [bool]$DryRun
Set-IndexEnvironment

Invoke-Script {
    if ($ApiOnly -and $WebOnly) { Fail '-ApiOnly and -WebOnly cannot be combined.' }
    $runApi = -not $WebOnly
    $runWeb = -not $ApiOnly

    $loaded = Import-DotEnv (Join-Path $script:RepoRoot '.env')
    if (-not (Test-Path (Join-Path $script:RepoRoot '.env'))) {
        Write-Note '.env not found: using built-in development defaults (scripts\bootstrap.ps1 creates it from .env.example).'
    }

    $apiPortNumber = $ApiPort
    if ($apiPortNumber -eq 0) { $apiPortNumber = if ($env:SPARTA_API_PORT) { [int]$env:SPARTA_API_PORT } else { 8000 } }
    $webPortNumber = $WebPort
    if ($webPortNumber -eq 0) { $webPortNumber = if ($env:SPARTA_WEB_PORT) { [int]$env:SPARTA_WEB_PORT } else { 3000 } }

    # Environment for the processes started below (values already set in the shell or .env are kept).
    [System.Environment]::SetEnvironmentVariable('SPARTA_PUBLIC_BASE_URL', ('http://localhost:' + $apiPortNumber), 'Process')
    Set-DefaultEnv 'SPARTA_CORS_ORIGINS' ('http://localhost:' + $webPortNumber + ',http://127.0.0.1:' + $webPortNumber)
    Set-DefaultEnv 'NEXT_PUBLIC_API_BASE_URL' ('http://localhost:' + $apiPortNumber)
    Set-DefaultEnv 'PYTHONUTF8' '1'

    # Preconditions, each with a plain explanation.
    $venv = Get-VenvDir $VenvDir
    $python = $null
    if ($runApi) {
        $python = if ($script:IsDryRun) { Join-Path $venv 'Scripts\python.exe' } else { Require-VenvPython $venv }
    }
    $nodeModules = Join-Path $script:WebDir 'node_modules'
    $nextCli = Join-Path $script:WebDir 'node_modules\next\dist\bin\next'
    if ($runWeb -and -not $script:IsDryRun) {
        if (-not (Test-Path (Join-Path $script:WebDir 'package.json'))) { Fail 'apps\web\package.json was not found.' @('Use -ApiOnly to run just the API.') }
        Require-Node
        if (-not (Test-Path $nextCli)) {
            Fail 'The web dependencies are not installed.' @('Run scripts\bootstrap.ps1 (or `npm ci` in apps\web).', 'Use -ApiOnly to run just the API.')
        }
    }

    if ($Docker) {
        if (-not $script:IsDryRun) { Require-Docker }
        $postgresPort = if ($env:SPARTA_POSTGRES_PORT) { $env:SPARTA_POSTGRES_PORT } else { '5432' }
        $redisPort = if ($env:SPARTA_REDIS_PORT) { $env:SPARTA_REDIS_PORT } else { '6379' }
        $postgresPassword = if ($env:SPARTA_POSTGRES_PASSWORD) { $env:SPARTA_POSTGRES_PASSWORD } else { 'sparta-dev-only' }
        $redisPassword = if ($env:SPARTA_REDIS_PASSWORD) { $env:SPARTA_REDIS_PASSWORD } else { 'sparta-dev-only' }
        Write-Step 'Starting PostgreSQL and Redis (docker compose)'
        Invoke-Native 'docker' @('compose', 'up', '-d', '--wait', 'postgres', 'redis') $script:RepoRoot -Hints @(
            'Port already in use? Set SPARTA_POSTGRES_PORT / SPARTA_REDIS_PORT in .env.',
            'See `docker compose logs postgres redis` for the reason.'
        )
        [System.Environment]::SetEnvironmentVariable('SPARTA_DATABASE_URL', ('postgresql+asyncpg://sparta:' + $postgresPassword + '@127.0.0.1:' + $postgresPort + '/sparta'), 'Process')
        [System.Environment]::SetEnvironmentVariable('SPARTA_REDIS_URL', ('redis://:' + $redisPassword + '@127.0.0.1:' + $redisPort + '/0'), 'Process')
    }

    if ($runApi) {
        Write-Step 'Applying database migrations'
        Invoke-Native $python @('-X', 'utf8', '-m', 'sparta', 'migrate') $script:ApiDir -Hints @(
            'The "error:" line above says which dependency is unreachable (database or Redis) and what to start; scripts\dev.ps1 -Docker starts PostgreSQL and Redis.',
            'Configuration problems are listed one per line under "Invalid Sparta configuration".'
        )
        Write-Step 'Creating the development owner'
        Invoke-Native $python @('-X', 'utf8', '-m', 'sparta', 'seed') $script:ApiDir -Hints @(
            'The "error:" line above says which dependency is unreachable. If Redis is configured (SPARTA_REDIS_URL), it must answer PING.'
        )
    }

    $children = @()
    $apiProcess = $null
    $webProcess = $null
    try {
        if ($runApi) {
            Write-Step ("Starting the API on http://127.0.0.1:" + $apiPortNumber)
            $apiArgs = @('-X', 'utf8', '-m', 'sparta', 'serve', '--host', '127.0.0.1', '--port', [string]$apiPortNumber)
            if ($script:IsDryRun) { Write-Host ("[dry-run] (" + $script:ApiDir + ") " + $python + ' ' + ($apiArgs -join ' ')) }
            else {
                $apiProcess = Start-Process -FilePath $python -ArgumentList $apiArgs -WorkingDirectory $script:ApiDir -NoNewWindow -PassThru
                $null = $apiProcess.Handle   # keeps the handle open so ExitCode is readable in Windows PowerShell 5.1
                $children += $apiProcess
            }
        }
        if ($runWeb) {
            Write-Step ("Starting the web app on http://localhost:" + $webPortNumber)
            # Same as `npm run dev` (next dev -p 3000) with a configurable port and no npm shim to clean up.
            $webArgs = @($nextCli, 'dev', '-p', [string]$webPortNumber)
            if ($script:IsDryRun) { Write-Host ("[dry-run] (" + $script:WebDir + ") node " + ($webArgs -join ' ')) }
            else {
                $webProcess = Start-Process -FilePath 'node' -ArgumentList $webArgs -WorkingDirectory $script:WebDir -NoNewWindow -PassThru
                $null = $webProcess.Handle
                $children += $webProcess
            }
        }
        if ($script:IsDryRun) {
            Write-Note ('Environment: SPARTA_PUBLIC_BASE_URL=' + $env:SPARTA_PUBLIC_BASE_URL + ' SPARTA_CORS_ORIGINS=' + $env:SPARTA_CORS_ORIGINS + ' NEXT_PUBLIC_API_BASE_URL=' + $env:NEXT_PUBLIC_API_BASE_URL)
            Write-Ok 'Dry run complete: nothing was started.'
            return
        }

        if ($runApi) {
            if (-not (Wait-Http ("http://127.0.0.1:" + $apiPortNumber + "/healthz") 90)) {
                if ($apiProcess.HasExited) { Fail ("The API exited with code " + $apiProcess.ExitCode + " during startup.") @('Read the error printed above (configuration problems are listed one per line).', 'Port in use? Pass -ApiPort <free port>.') }
                Fail 'The API did not answer /healthz within 90 seconds.' @('Check the log output above.')
            }
        }
        Write-Host ''
        Write-Ok 'Sparta is running (development identity, simulator providers: no real calls, no cloud accounts).'
        if ($runApi) { Write-Note ("API          http://localhost:" + $apiPortNumber + "   (interactive docs: /docs, status: /api/v1/system/status)") }
        if ($runWeb) { Write-Note ("Web          http://localhost:" + $webPortNumber) ; Write-Note ("Simulator    http://localhost:" + $webPortNumber + "/simulator") }
        Write-Note 'Press Ctrl+C to stop.'

        while ($true) {
            Start-Sleep -Seconds 1
            foreach ($child in $children) {
                if ($child.HasExited) { Fail ("A server process exited unexpectedly (exit code " + $child.ExitCode + "). Everything started by this script is being stopped.") @('Read the output above for the reason.') }
            }
        }
    }
    finally {
        foreach ($child in $children) {
            if ($child -and -not $child.HasExited) { Stop-ProcessTree $child.Id }
        }
        if ($children.Count -gt 0) { Write-Note 'Stopped the processes started by this script.' }
        if ($Docker -and -not $script:IsDryRun) { Write-Note 'PostgreSQL and Redis keep running: stop them with `docker compose stop postgres redis`.' }
    }
}
