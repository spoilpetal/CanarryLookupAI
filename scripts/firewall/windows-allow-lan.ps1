# Run PowerShell as Administrator. Allows CanarryLookup only from Windows' LocalSubnet.
param([int]$Port = 8080)
$ErrorActionPreference = 'Stop'
$Name = 'CanarryLookup AI (LAN)'
Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName $Name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -RemoteAddress LocalSubnet -Profile Private
Write-Host "Allowed TCP $Port from LocalSubnet on Private networks. Public profile remains unchanged."
Write-Host "To undo: Remove-NetFirewallRule -DisplayName '$Name'"
