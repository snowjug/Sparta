<#
.SYNOPSIS
    Runs the Sparta test suites: backend (pytest), web unit tests (vitest) and, optionally, Android JVM unit tests.

.PARAMETER Api          Run the backend tests (services\api, pytest).
.PARAMETER Web          Run the web unit tests (apps\web, vitest).
.PARAMETER Android      Run the Android JVM unit tests (apps\android, Gradle; needs JDK 17 and the Android SDK).
.PARAMETER PostgresUrl  Also run the PostgreSQL integration tests against this database, for example
                        postgresql+asyncpg://sparta:sparta-dev-only@127.0.0.1:5432/sparta_test
                        WARNING: those tests DROP ALL TABLES in that database. Use a dedicated throwaway database.
.PARAMETER PytestArgs   Extra arguments for pytest (for example -k risk).
.PARAMETER VenvDir      Python environment (default services\api\.venv or $env:SPARTA_VENV).
.PARAMETER DryRun       Print the commands without running them.

    With no suite switch the backend and web suites run.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\test.ps1 -Api -PytestArgs '-k','risk'
#>
[CmdletBinding()]
param(
    [switch]$Api,
    [switch]$Web,
    [switch]$Android,
    [string]$PostgresUrl = '',
    [string[]]$PytestArgs = @(),
    [string]$VenvDir = '',
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot 'lib.ps1')
$script:IsDryRun = [bool]$DryRun
Set-IndexEnvironment

Invoke-Script {
    $runApi = [bool]$Api
    $runWeb = [bool]$Web
    $runAndroid = [bool]$Android
    if (-not ($runApi -or $runWeb -or $runAndroid)) { $runApi = $true; $runWeb = $true }

    if ($runApi) {
        $venv = Get-VenvDir $VenvDir
        $python = if ($script:IsDryRun) { Join-Path $venv 'Scripts\python.exe' } else { Require-VenvPython $venv }
        if ($PostgresUrl) {
            Write-Warn 'The PostgreSQL integration tests DROP ALL TABLES in the target database.'
            [System.Environment]::SetEnvironmentVariable('SPARTA_TEST_POSTGRES_URL', $PostgresUrl, 'Process')
        }
        elseif (-not $env:SPARTA_TEST_POSTGRES_URL) {
            Write-Note 'SPARTA_TEST_POSTGRES_URL is not set: PostgreSQL integration tests are skipped (SQLite always runs).'
        }
        Write-Step 'Backend tests (pytest)'
        Invoke-Native $python (@('-X', 'utf8', '-m', 'pytest', 'tests') + $PytestArgs) $script:ApiDir -Hints @(
            'A failing test is reported above. Run `pytest tests/<path>::<test> -x` from services\api to iterate on one.'
        )
    }

    if ($runWeb) {
        if (-not (Test-Path (Join-Path $script:WebDir 'package.json'))) { Fail 'apps\web\package.json was not found.' @('Use -Api to run only the backend tests.') }
        if (-not $script:IsDryRun) {
            Require-Node
            if (-not (Test-Path (Join-Path $script:WebDir 'node_modules'))) { Fail 'The web dependencies are not installed.' @('Run scripts\bootstrap.ps1 (or `npm ci` in apps\web).') }
        }
        Write-Step 'Web unit tests (vitest)'
        $npm = if ($script:IsDryRun) { 'npm' } else { Get-NpmCommand }
        Invoke-Native $npm @('test') $script:WebDir
    }

    if ($runAndroid) {
        $gradlew = Join-Path $script:AndroidDir 'gradlew.bat'
        if (-not (Test-Path $gradlew)) { Fail 'apps\android\gradlew.bat was not found.' }
        if (-not $script:IsDryRun -and -not (Test-Command 'java') -and -not $env:JAVA_HOME) {
            Fail 'No JDK was found (JAVA_HOME is unset and java is not on PATH).' @(
                'Install JDK 17 (for example: winget install EclipseAdoptium.Temurin.17.JDK) and the Android SDK; see docs\ANDROID_SETUP.md.'
            )
        }
        Write-Step 'Android unit tests (Gradle testDebugUnitTest)'
        Invoke-Native $gradlew @('testDebugUnitTest') $script:AndroidDir -Hints @('See docs\ANDROID_SETUP.md for the SDK and JDK requirements.')
    }

    Write-Host ''
    if ($script:IsDryRun) { Write-Ok 'Dry run complete: nothing was executed.' } else { Write-Ok 'Tests passed.' }
}
