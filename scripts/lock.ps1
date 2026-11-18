<#
.SYNOPSIS
    Regenerates the hash-pinned lock files used to build the container image (and checks them).

.DESCRIPTION
    Writes, in services\api:
      requirements.lock         runtime dependencies only            (image built with --build-arg SPARTA_EXTRAS=)
      requirements-extras.lock  runtime + the azure and otlp extras  (the default image)
      requirements-build.lock   uv and hatchling, from requirements-build.in (the image's build tools)
    Every package is pinned with sha256 hashes only (md5 lines that some package mirrors add are removed), and the versions
    are held to the ones in requirements-dev.lock, so the image runs what the test suite ran against. Order of work when
    you change dependencies: edit pyproject.toml, regenerate requirements-dev.lock (uv pip compile ... --group dev), then
    run this script and commit all lock files together.

    It creates services\api\var\lock-venv (git-ignored) with uv, needs network access to the package index (set
    $env:PIP_INDEX_URL when you build behind a mirror), and changes nothing else. Afterwards it runs scripts\verify_locks.py,
    which asks pypi.org whether every sha256 in the new locks is a published file digest (a mirror cannot slip a different
    file into the lock unnoticed); an unreachable pypi.org is only a warning, a hash it does not know is an error.

.PARAMETER VenvDir     Where the throwaway uv environment lives (default services\api\var\lock-venv).
.PARAMETER SkipVerify  Do not cross-check the hashes against pypi.org (run scripts\tasks.ps1 verify-locks later).
.PARAMETER DryRun      Print the commands without running them.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\lock.ps1
#>
[CmdletBinding()]
param(
    [string]$VenvDir = '',
    [switch]$SkipVerify,
    [switch]$DryRun
)

. (Join-Path $PSScriptRoot 'lib.ps1')
$script:IsDryRun = [bool]$DryRun
Set-IndexEnvironment

function Remove-Md5Hashes([string]$Path) {
    $lines = [System.IO.File]::ReadAllLines($Path)
    $kept = @($lines | Where-Object { $_ -notmatch '^\s+--hash=md5:' })
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, (($kept -join "`n") + "`n"), $utf8)
    return ($lines.Count - $kept.Count)
}

function Test-LockFile([string]$Path) {
    $lines = [System.IO.File]::ReadAllLines($Path)
    $requirements = @($lines | Where-Object { $_ -match '^[A-Za-z0-9_.\-]+(\[[^\]]+\])?==' })
    $hashes = @($lines | Where-Object { $_ -match '^\s+--hash=sha256:[0-9a-f]{64}' })
    $other = @($lines | Where-Object { $_ -match '^\s+--hash=' -and $_ -notmatch '^\s+--hash=sha256:' })
    if ($requirements.Count -eq 0) { Fail ((Split-Path -Leaf $Path) + ' has no pinned requirements.') }
    if ($other.Count -gt 0) { Fail ((Split-Path -Leaf $Path) + ' still contains non-sha256 hashes.') }
    if ($hashes.Count -lt $requirements.Count) { Fail ((Split-Path -Leaf $Path) + ' has requirements without a sha256 hash.') }
    return $requirements.Count
}

# Exit code of scripts\verify_locks.py: 0 all hashes published on PyPI, 1 some are not, 2 PyPI unreachable.
function Test-LocksOnPyPI([string]$Python, [string[]]$Names) {
    $paths = @($Names | ForEach-Object { Join-Path $script:ApiDir $_ })
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Python (Join-Path $PSScriptRoot 'verify_locks.py') @paths | Out-Host
        return $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
}

Invoke-Script {
    $buildIn = Join-Path $script:ApiDir 'requirements-build.in'
    $devLock = Join-Path $script:ApiDir 'requirements-dev.lock'
    foreach ($needed in $buildIn, $devLock, (Join-Path $script:ApiDir 'pyproject.toml')) {
        if (-not (Test-Path $needed)) { Fail ('Missing ' + $needed) @('Run this script from a complete checkout.') }
    }
    $uvLine = Get-Content $buildIn | Where-Object { $_ -match '^uv==' } | Select-Object -First 1
    if (-not $uvLine) { Fail 'requirements-build.in does not pin uv (a line like uv==0.13.7).' }
    $uvVersion = ($uvLine -replace '^uv==', '').Trim()

    $venv = if ($VenvDir) { $VenvDir } else { Join-Path $script:ApiDir 'var\lock-venv' }
    $python = Find-Python
    if (-not $python) {
        Fail 'Python 3.12 or newer was not found.' @('Install Python 3.12, then retry (it is only used to install uv).')
    }

    $venvPython = Get-VenvPython $venv
    if (-not $venvPython) {
        Write-Step ('Creating ' + $venv)
        Invoke-Native $python.Exe (@($python.PrefixArgs) + @('-m', 'venv', $venv)) $script:ApiDir
        $venvPython = if ($script:IsDryRun) { Join-Path $venv 'Scripts\python.exe' } else { Require-VenvPython $venv }
    }
    Write-Step ('Installing uv ' + $uvVersion + ' (the version named in requirements-build.in)')
    Invoke-Native $venvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '--quiet', ('uv==' + $uvVersion)) $script:ApiDir -Hints @(
        'pip could not download uv. If pypi.org is unreachable, set $env:PIP_INDEX_URL to a mirror and retry.'
    )

    $common = @('pip', 'compile', '-qq', '--universal', '--generate-hashes', '--python-version', '3.12')
    $jobs = @(
        @('requirements.lock', @('pyproject.toml', '--constraint', 'requirements-dev.lock')),
        @('requirements-extras.lock', @('pyproject.toml', '--extra', 'azure', '--extra', 'otlp', '--constraint', 'requirements-dev.lock')),
        @('requirements-build.lock', @('requirements-build.in'))
    )
    $uvArgsPrefix = @('-m', 'uv')
    foreach ($job in $jobs) {
        $out = $job[0]
        Write-Step ('Compiling ' + $out)
        Invoke-Native $venvPython ($uvArgsPrefix + $common + $job[1] + @('-o', $out)) $script:ApiDir -Hints @(
            'uv could not resolve the dependencies. Check the network, or set $env:PIP_INDEX_URL (also used by uv) to a reachable index.'
        )
        if (-not $script:IsDryRun) {
            $removed = Remove-Md5Hashes (Join-Path $script:ApiDir $out)
            $count = Test-LockFile (Join-Path $script:ApiDir $out)
            Write-Ok ($out + ': ' + $count + ' pinned packages, sha256 only' + $(if ($removed -gt 0) { ' (removed ' + $removed + ' md5 lines)' } else { '' }))
        }
    }

    Write-Host ''
    if ($script:IsDryRun) { Write-Ok 'Dry run complete: nothing was executed.' }
    else {
        if ($SkipVerify) { Write-Warn 'Skipped the cross-check against pypi.org: run scripts\tasks.ps1 verify-locks before committing.' }
        else {
            Write-Step 'Cross-checking every sha256 against pypi.org (scripts\verify_locks.py)'
            $code = Test-LocksOnPyPI $venvPython @('requirements.lock', 'requirements-extras.lock', 'requirements-build.lock')
            if ($code -eq 0) { Write-Ok 'Every sha256 in the new locks is a file digest that pypi.org publishes.' }
            elseif ($code -eq 1) {
                Fail 'A lock lists a hash that pypi.org does not publish for that release.' @(
                    'Do not commit these files: the package index you used served files that differ from the published ones.',
                    'Retry with $env:PIP_INDEX_URL unset (pypi.org itself) or another trusted index.'
                )
            }
            else { Write-Warn 'Could not reach pypi.org, so the hashes were not cross-checked: run scripts\tasks.ps1 verify-locks from a network that can, before committing.' }
        }
        Write-Ok 'Lock files regenerated. Review the diff, then commit requirements*.lock together.'
        Write-Note 'The image build verifies every file against these hashes (pip/uv --require-hashes); the build fails if an index serves different bytes.'
    }
}
