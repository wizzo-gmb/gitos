# Forwards TCP <Port> on this PC into the WSL2 distro that runs the System One server.
# The WSL2 address changes whenever WSL restarts, so setup-windows.ps1 runs this at every logon
# (an elevated scheduled task). It carries no machine-specific value: the distro and the port arrive as parameters.
param(
    [Parameter(Mandatory = $true)][string]$Distro,
    [Parameter(Mandatory = $true)][int]$Port
)
$ip = $null
for ($i = 0; $i -lt 30 -and -not $ip; $i++) {
    $ip = (wsl.exe -d $Distro -- hostname -I).Trim().Split(" ")[0]
    if (-not $ip) { Start-Sleep -Seconds 2 }
}
if (-not $ip) { exit 1 }
netsh interface portproxy delete v4tov4 listenport=$Port listenaddress=0.0.0.0 | Out-Null
netsh interface portproxy add v4tov4 listenport=$Port listenaddress=0.0.0.0 connectport=$Port connectaddress=$ip | Out-Null
