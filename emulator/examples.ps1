# 1. Define your environment variables
$IP = "127.0.0.1" # <-- UPDATE THIS TO YOUR EMULATOR IP
$BaseUrl = "https://$($IP):8006/api2/json"

Test-NetConnection -ComputerName localhost -Port 8006

# Bypass SSL certificate validation checks
[System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }

# 2. Get a ticket
$AuthBody = @{ username = "root@pam"; password = "anything" }

try {
    Write-Host "Connecting to emulator at $BaseUrl..." -ForegroundColor Cyan
    $AuthResponse = Invoke-RestMethod -Uri "$BaseUrl/access/ticket" -Method Post -Body $AuthBody -TimeoutSec 5
} catch {
    Write-Error "Failed to connect to the emulator. Verify the IP, port, and that the emulator process is actively running."
    return # Stops execution immediately if the API is dead
}

# Extract tokens safely
$Ticket = $AuthResponse.data.ticket
$CSRF = $AuthResponse.data.CSRFPreventionToken

if (-not $Ticket) {
    Write-Error "Connected, but failed to retrieve an authentication ticket."
    return
}

Write-Host "Authenticated successfully! Running VM commands..." -ForegroundColor Green

# Define reusable session headers and cookies
$Headers = @{ "CSRFPreventionToken" = $CSRF }
$WebSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$WebSession.Cookies.Add((New-Object System.Net.Cookie("PVEAuthCookie", $Ticket, "/", $IP)))

# 3. Create VM 100
Write-Host "Creating VM 100..."
$VmBody = @{ vmid = 100; name = "my-vm"; cores = 2; memory = 2048 }
$null = Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu" -Method Post -Body $VmBody -Headers $Headers -WebSession $WebSession

# 4. List VMs
Write-Host "Listing current VMs:"
Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu" -Method Get -WebSession $WebSession | Format-Table

# 5. Start VM 100
Write-Host "Starting VM 100..."
$null = Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/100/status/start" -Method Post -Headers $Headers -WebSession $WebSession

# 6. Query VM 100 status
Write-Host "Querying VM 100 status:"
Invoke-RestMethod -Uri "$BaseUrl/nodes/pve/qemu/100/status/current" -Method Get -WebSession $WebSession | Format-List
