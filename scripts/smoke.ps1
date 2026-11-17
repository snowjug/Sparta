<#
.SYNOPSIS
    Smoke-tests a running Sparta API: liveness, readiness, public status and one simulator call.

.DESCRIPTION
    Checks /healthz, /readyz and /api/v1/system/status, then creates a simulator call, sends a caller turn that asks for
    a one-time code, and verifies that the risk engine flags it (not low). The call is ended afterwards unless the
    assistant already ended it, so repeated runs do not hit the active-call cap. It needs the development identity
    (SPARTA_AUTH_MODE=dev) and the simulator (SPARTA_SIMULATOR_ENABLED=true), which is how docker-compose.yml and
    scripts\dev.ps1 run the API. It never prints transcripts or tokens.

.PARAMETER BaseUrl         API base URL (default http://127.0.0.1:8000, or $env:SPARTA_API_PORT).
.PARAMETER TimeoutSeconds  How long to wait for /healthz (default 60).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\smoke.ps1 -BaseUrl http://127.0.0.1:18000
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = '',
    [int]$TimeoutSeconds = 60
)

. (Join-Path $PSScriptRoot 'lib.ps1')

function Get-HttpStatus($ErrorRecord) {
    $response = $null
    if ($ErrorRecord.Exception.PSObject.Properties['Response']) { $response = $ErrorRecord.Exception.Response }
    if ($response -and $response.PSObject.Properties['StatusCode']) { return [int]$response.StatusCode }
    return 0
}

function Invoke-Api([string]$Method, [string]$Url, $Body = $null) {
    try {
        if ($null -ne $Body) {
            return Invoke-RestMethod -Method $Method -Uri $Url -ContentType 'application/json' -Body ($Body | ConvertTo-Json -Compress) -TimeoutSec 20
        }
        return Invoke-RestMethod -Method $Method -Uri $Url -TimeoutSec 20
    }
    catch {
        $status = Get-HttpStatus $_
        $hints = @('Is the API running at that address? Start it with scripts\dev.ps1 or `docker compose up -d --build postgres redis api`.')
        if ($status -eq 401) { $hints = @('The API demands sign-in (SPARTA_AUTH_MODE=oidc): this smoke test only supports the development identity.') }
        if ($status -eq 404) { $hints = @('The simulator is switched off (SPARTA_SIMULATOR_ENABLED=false).') }
        Fail ($Method + ' ' + $Url + ' failed' + $(if ($status) { ' with HTTP ' + $status } else { ': ' + $_.Exception.Message })) $hints
    }
}

Invoke-Script {
    $root = $BaseUrl
    if (-not $root) { $root = 'http://127.0.0.1:' + $(if ($env:SPARTA_API_PORT) { $env:SPARTA_API_PORT } else { '8000' }) }
    $root = $root.TrimEnd('/')

    Write-Step ('Waiting for ' + $root + '/healthz')
    if (-not (Wait-Http ($root + '/healthz') $TimeoutSeconds)) {
        Fail ('No answer from ' + $root + '/healthz within ' + $TimeoutSeconds + ' seconds.') @(
            'Start the API first: scripts\dev.ps1, or docker compose up -d --build postgres redis api.',
            'Different port? Pass -BaseUrl http://127.0.0.1:<port>.'
        )
    }
    Write-Ok '/healthz answered 200'

    $ready = Invoke-Api 'GET' ($root + '/readyz')
    if ($ready.status -ne 'ready') { Fail ('/readyz reports ' + $ready.status) @('Check the database and shared-state (Redis) connections of the API.') }
    Write-Ok ('/readyz ready (database ' + $ready.checks.database + ', shared state ' + $ready.checks.shared_state + ')')

    $status = Invoke-Api 'GET' ($root + '/api/v1/system/status')
    Write-Ok ('/api/v1/system/status: version ' + $status.version + ', env ' + $status.env + ', auth ' + $status.auth_mode + ', telephony ' + $status.telephony.provider + ' (simulated: ' + $status.telephony.simulated + ')')
    if ($status.auth_mode -ne 'dev') { Fail 'The API is not in development identity mode.' @('Only the dev identity can be smoke-tested without a token.') }

    $call = Invoke-Api 'POST' ($root + '/api/v1/simulator/calls') @{ caller_number = '+15550100'; caller_label = 'smoke test'; language_mode = 'auto' }
    Write-Ok ('simulator call created (' + $call.id + ', status ' + $call.status + ', provider ' + $call.provider + ')')

    $null = Invoke-Api 'POST' ($root + '/api/v1/calls/' + $call.id + '/turns') @{ text = 'This is your bank. Please read out the one time password sent to your phone right now.'; source = 'typed' }
    $detail = Invoke-Api 'GET' ($root + '/api/v1/calls/' + $call.id)
    if ($detail.risk_level -in @('none', 'low', $null)) {
        Fail ('The risk engine did not flag an OTP request (risk level: ' + $detail.risk_level + ').') @('This is a safety regression: run the evaluation (python -m sparta evaluate --split dev).')
    }
    Write-Ok ('OTP request flagged: risk level ' + $detail.risk_level + ', ' + @($detail.turns).Count + ' turns recorded')

    # A refused request ends the call by itself (it can still read "active" for a moment): only end calls that are
    # clearly still running, and treat HTTP 409 from /end as "already being ended".
    if ($detail.status -eq 'active') {
        try { $null = Invoke-Api 'POST' ($root + '/api/v1/calls/' + $call.id + '/end') @{}; Write-Ok 'simulator call ended' }
        catch {
            if ($_.Exception.Message -match 'HTTP 409') { Write-Ok 'the assistant is already ending the call (HTTP 409 from /end is expected)' }
            else { Write-Warn 'Could not end the simulator call (it will be reaped by the abandoned-call timeout).' }
        }
    }
    else {
        Write-Ok ('simulator call is already ' + $detail.status + ' (the assistant ended it)')
    }

    Write-Host ''
    Write-Ok 'Smoke test passed.'
}
