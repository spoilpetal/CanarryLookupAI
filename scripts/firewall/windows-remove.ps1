# Run PowerShell as Administrator.
Remove-NetFirewallRule -DisplayName 'CanarryLookup AI (LAN)' -ErrorAction SilentlyContinue
Write-Host 'CanarryLookup LAN firewall rule removed.'
