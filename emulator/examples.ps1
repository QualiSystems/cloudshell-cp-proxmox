# Manual walkthrough of the Proxmox emulator's API using Invoke-RestMethod, mirroring
# exactly what cloudshell-cp-proxmox's ProxmoxAutomationAPI does (JSON bodies, ticket
# cookie + CSRFPreventionToken header, task-UPID polling, cluster/resources for
# vmid->node lookup). Run this against a running emulator to sanity-check that
# requests/responses look the way they should. Mirrors examples.sh step-for-step
# so behavior can be compared across Windows and Mac/Linux.
#
# Usage:
#   powershell -File examples.ps1 [-HostName <ip>] [-Port <port>] [-Scheme http|https]
#   .\examples.ps1                                        # defaults to http://127.0.0.1:8006, i.e. run the
#                                                          # server with `python server.py --no-tls`
#   .\examples.ps1 -Scheme https -Port 8006               # against the server's default self-signed HTTPS
#
# Defaults to HTTP, not HTTPS. Windows PowerShell 5.1's Invoke-RestMethod (the
# legacy .NET HttpWebRequest TLS stack) is intermittently incompatible with
# Werkzeug's ad-hoc self-signed dev certificate -- random "underlying
# connection was closed" errors on an otherwise-correct request. This is a
# quirk of that specific client/dev-server combination, not of the emulator's
# API behavior: curl and Python's requests/urllib3 (what the real driver
# uses) are unaffected over HTTPS. Pass -Scheme https to exercise that path
# anyway; if it's flaky, that's this known limitation, not a bug in a
# response body.
#
# Written for Windows PowerShell 5.1.

param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8006,
    [string]$Scheme = "http"
)

$BaseUrl = "$($Scheme)://$($HostName):$($Port)/api2/json"

if ($Scheme -eq "https") {
    # Self-signed cert, exactly like a fresh real Proxmox node.
    [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }
}

function Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Show($obj) {
    $obj | ConvertTo-Json -Depth 6
}

function Write-ConnectivityError($err) {
    Write-Error "Failed to reach the emulator at $BaseUrl. Is it running? (see README for 'python server.py')"
    if ($Port -eq 8006) {
        Write-Host ""
        Write-Host "Note: if the server's console shows it's listening but every" -ForegroundColor Yellow
        Write-Host "request still resets/times out immediately, and you're running" -ForegroundColor Yellow
        Write-Host "this inside a sandboxed or restrictively-networked shell (some CI" -ForegroundColor Yellow
        Write-Host "runners and coding-agent sandboxes do this), that sandbox may be" -ForegroundColor Yellow
        Write-Host "blocking Proxmox's well-known port 8006 specifically, regardless" -ForegroundColor Yellow
        Write-Host "of client. A normal terminal session shouldn't hit this. Either" -ForegroundColor Yellow
        Write-Host "way, running the server on a different port (e.g. --port 18006," -ForegroundColor Yellow
        Write-Host "passed as -Port 18006 here) sidesteps it." -ForegroundColor Yellow
    }
}

Step "Version (no auth required)"
try {
    $version = Invoke-RestMethod -Uri "$BaseUrl/version" -Method Get -TimeoutSec 5
} catch {
    Write-ConnectivityError $_
    exit 1
}
Show $version

Step "Log in (POST /access/ticket with a JSON body, like the real driver)"
$authBody = @{ username = "root@pam"; password = "anything" } | ConvertTo-Json
try {
    $authResponse = Invoke-RestMethod -Uri "$BaseUrl/access/ticket" -Method Post -Body $authBody -ContentType "application/json" -TimeoutSec 5
} catch {
    Write-ConnectivityError $_
    exit 1
}
Show $authResponse

$ticket = $authResponse.data.ticket
$csrf = $authResponse.data.CSRFPreventionToken
if (-not $ticket) {
    Write-Error "Connected, but did not get back an authentication ticket."
    exit 1
}

$headers = @{ "CSRFPreventionToken" = $csrf }
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$session.Cookies.Add((New-Object System.Net.Cookie("PVEAuthCookie", $ticket, "/", $HostName)))

Step "List VMs (should be empty on a fresh state file)"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu" -Method Get -Headers $headers -WebSession $session)

Step "Ask for the next free VM ID"
$nextIdResp = Invoke-RestMethod -Uri "$BaseUrl/cluster/nextid" -Method Get -Headers $headers -WebSession $session
Show $nextIdResp
$vmid = [int]$nextIdResp.data

Step "Create VM $vmid (this is what a bare 'create' looks like; the real driver always clones instead - see below)"
$createBody = @{ vmid = $vmid; name = "demo-vm"; cores = 2; memory = 2048 } | ConvertTo-Json
$createResp = Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu" -Method Post -Body $createBody -ContentType "application/json" -Headers $headers -WebSession $session
Show $createResp
$upid = $createResp.data

Step "Poll the task until it's done (real UPID: $upid)"
$escapedUpid = [uri]::EscapeDataString($upid)
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/tasks/$escapedUpid/status" -Method Get -Headers $headers -WebSession $session)

Step "cluster/resources now resolves vmid $vmid -> node (this is how the driver finds which node a VM lives on)"
Show (Invoke-RestMethod -Uri "$BaseUrl/cluster/resources?type=vm" -Method Get -Headers $headers -WebSession $session)

Step "Get VM $vmid config"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid/config" -Method Get -Headers $headers -WebSession $session)

Step "Status before starting: should be 'stopped', and must NOT contain a 'lock' key"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid/status/current" -Method Get -Headers $headers -WebSession $session)

Step "Start VM $vmid"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid/status/start" -Method Post -Headers $headers -WebSession $session)

Step "Status after starting: 'running' with mock cpu/mem/uptime data"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid/status/current" -Method Get -Headers $headers -WebSession $session)

Step "Get Snapshots (empty except the synthetic 'current' pointer)"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid/snapshot" -Method Get -Headers $headers -WebSession $session)

Step "Save Snapshot 'before-clone' (vmstate=1 -- 'with memory', VM is running)"
$snapBody = @{ snapname = "before-clone"; vmstate = 1 } | ConvertTo-Json
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid/snapshot" -Method Post -Body $snapBody -ContentType "application/json" -Headers $headers -WebSession $session)

Step "Refresh IP: VM $vmid config reports a net0 MAC"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid/config" -Method Get -Headers $headers -WebSession $session)

Step "Refresh IP: guest agent reports a matching IPv4 address (VM is running)"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid/agent/network-get-interfaces" -Method Get -Headers $headers -WebSession $session)

Step "Restore Snapshot 'before-clone' (a 'with memory' snapshot -- VM stays running)"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid/snapshot/before-clone/rollback" -Method Post -Headers $headers -WebSession $session)

Step "Remove Snapshot 'before-clone'"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid/snapshot/before-clone" -Method Delete -Headers $headers -WebSession $session)

Step "Clone VM $vmid (this is the path the real driver actually uses to 'create' a VM)"
$newIdResp = Invoke-RestMethod -Uri "$BaseUrl/cluster/nextid" -Method Get -Headers $headers -WebSession $session
$newId = [int]$newIdResp.data
$cloneBody = @{ newid = $newId; name = "demo-vm-clone" } | ConvertTo-Json
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid/clone" -Method Post -Body $cloneBody -ContentType "application/json" -Headers $headers -WebSession $session)

Step "Both VMs now listed"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu" -Method Get -Headers $headers -WebSession $session)

Step "Deleting a running VM is rejected (matches real Proxmox) - expect an HTTP error here"
try {
    Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid" -Method Delete -Headers $headers -WebSession $session
    Write-Warning "Expected this call to fail (VM is running) but it succeeded."
} catch {
    Write-Host "Got expected error: $($_.Exception.Response.StatusCode.value__)" -ForegroundColor Yellow
}

Step "Stop, then delete VM $vmid"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid/status/stop" -Method Post -Headers $headers -WebSession $session)
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$vmid" -Method Delete -Headers $headers -WebSession $session)

Step "Stop and delete the clone too"
Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$newId/status/stop" -Method Post -Headers $headers -WebSession $session | Out-Null
Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/$newId" -Method Delete -Headers $headers -WebSession $session | Out-Null

Step "Final list: back to empty"
Show (Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu" -Method Get -Headers $headers -WebSession $session)

Step "Done."
