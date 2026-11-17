# System One, Windows side: run ONCE from an elevated PowerShell, after filling the block below.
# It registers two logon tasks, adds the firewall rule and refreshes the port forward now.
#   1. "gitos System One (WSL keep-alive)": starts the distro at logon and keeps it up, so the systemd user unit runs.
#   2. "gitos System One (port forward)": at logon (after a delay) runs refresh-portproxy.ps1, elevated.
#   3. firewall rule "gitos System One (LAN)": inbound TCP on the port, from the addresses you name only.
# Skip the port forward and the firewall rule (steps 2 and 3) for a loopback-only server.
# Every @@...@@ marker is a placeholder that references/system-one.md (Machine setup) explains. Nothing here is a secret.
$ErrorActionPreference = "Stop"

$Distro        = "@@DISTRO@@"            # the WSL distro name, as `wsl -l` lists it
$Port          = "@@PORT@@"              # the server's TCP port
$WindowsUser   = "@@WINDOWS_USER@@"      # the logon user, your computer name, a backslash, your user name
$ScriptDir     = "@@SCRIPT_DIR@@"        # a folder to keep refresh-portproxy.ps1 in
$LanRemoteAddr = "@@LAN_REMOTE_ADDRESS@@" # LocalSubnet, or the client addresses / CIDR allowed to connect

New-Item -ItemType Directory -Force -Path $ScriptDir | Out-Null
Copy-Item -Force (Join-Path $PSScriptRoot "refresh-portproxy.ps1") (Join-Path $ScriptDir "refresh-portproxy.ps1")

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $WindowsUser

# 1. keep the distro up
$keepAction   = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d $Distro -- sleep infinity"
$keepSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$keepPrincipal = New-ScheduledTaskPrincipal -UserId $WindowsUser -LogonType Interactive
Register-ScheduledTask -TaskName "gitos System One (WSL keep-alive)" -Action $keepAction -Trigger $trigger `
    -Settings $keepSettings -Principal $keepPrincipal -Force `
    -Description "Starts the $Distro distro at logon and keeps it up, so the System One model server runs." | Out-Null

# 2. refresh the port forward at logon, elevated, after the distro has had time to start
$fwdTrigger = New-ScheduledTaskTrigger -AtLogOn -User $WindowsUser
$fwdTrigger.Delay = "PT45S"
$fwdAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}" -Distro "{1}" -Port {2}' -f (Join-Path $ScriptDir "refresh-portproxy.ps1"), $Distro, $Port)
$fwdSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
$fwdPrincipal = New-ScheduledTaskPrincipal -UserId $WindowsUser -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName "gitos System One (port forward)" -Action $fwdAction -Trigger $fwdTrigger `
    -Settings $fwdSettings -Principal $fwdPrincipal -Force | Out-Null

# 3. the firewall rule: inbound TCP on the port, limited to the addresses named above
Remove-NetFirewallRule -DisplayName "gitos System One (LAN)" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "gitos System One (LAN)" -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort $Port -RemoteAddress $LanRemoteAddr | Out-Null

# now: forward the port without waiting for the next logon
& (Join-Path $ScriptDir "refresh-portproxy.ps1") -Distro $Distro -Port $Port
