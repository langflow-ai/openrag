param(
    [ValidateSet("report", "safe", "aggressive")]
    [string]$Mode = "report",
    [string]$Distro = "Ubuntu",
    [switch]$SkipCompact
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host "=== $Title ===" -ForegroundColor Cyan
}

function Assert-Admin {
    $current = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($current)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Administrator permission is required to compact VHDX. Please run PowerShell as Administrator."
    }
}

function Get-LxssDistroInfo([string]$TargetDistro) {
    $lxss = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss"
    $items = Get-ChildItem $lxss -ErrorAction SilentlyContinue
    foreach ($item in $items) {
        $p = Get-ItemProperty $item.PSPath
        if ($p.DistributionName -eq $TargetDistro) {
            return [PSCustomObject]@{
                DistributionName = $p.DistributionName
                BasePath         = $p.BasePath
                VhdxPath         = (Join-Path $p.BasePath "ext4.vhdx")
            }
        }
    }
    throw "Cannot find distro '$TargetDistro' in Lxss registry."
}

function Get-DockerSystemDfText {
    try {
        return (& docker system df 2>$null) -join [Environment]::NewLine
    } catch {
        return "Docker CLI is unavailable or Docker Desktop is not running."
    }
}

function Show-StorageReport([string]$TargetDistro) {
    Write-Section "Drive C usage"
    Get-PSDrive -Name C | Select-Object Name,
        @{Name="UsedGB";Expression={[math]::Round($_.Used/1GB,2)}},
        @{Name="FreeGB";Expression={[math]::Round($_.Free/1GB,2)}} |
        Format-Table -AutoSize

    Write-Section "WSL distro and ext4.vhdx"
    $info = Get-LxssDistroInfo -TargetDistro $TargetDistro
    if (Test-Path $info.VhdxPath) {
        $size = (Get-Item $info.VhdxPath).Length
        [PSCustomObject]@{
            Distro   = $info.DistributionName
            VhdxPath = $info.VhdxPath
            SizeGB   = [math]::Round($size/1GB,2)
        } | Format-Table -AutoSize
    } else {
        Write-Host "VHDX file not found: $($info.VhdxPath)" -ForegroundColor Yellow
    }

    Write-Section "Docker disk usage"
    Write-Host (Get-DockerSystemDfText)

    Write-Section "Top VHDX files in AppData"
    Get-ChildItem -Path "$env:USERPROFILE\AppData" -Recurse -Filter "*.vhdx" -ErrorAction SilentlyContinue |
        Select-Object FullName,@{Name="SizeGB";Expression={[math]::Round($_.Length/1GB,2)}} |
        Sort-Object SizeGB -Descending |
        Select-Object -First 10 |
        Format-Table -AutoSize
}

function Invoke-DockerCleanup([bool]$IncludeVolumes) {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        Write-Host "Skip Docker cleanup: docker CLI not found." -ForegroundColor Yellow
        return
    }

    Write-Section "Docker cleanup"
    Write-Host "docker container prune -f"
    docker container prune -f | Out-Host
    Write-Host "docker image prune -af"
    docker image prune -af | Out-Host
    Write-Host "docker network prune -f"
    docker network prune -f | Out-Host

    if ($IncludeVolumes) {
        Write-Host "docker volume prune -f"
        docker volume prune -f | Out-Host
    } else {
        Write-Host "Keeping volumes in safe mode." -ForegroundColor Yellow
    }
}

function Compact-WslVhdx([string]$TargetDistro) {
    Assert-Admin
    $info = Get-LxssDistroInfo -TargetDistro $TargetDistro
    if (-not (Test-Path $info.VhdxPath)) {
        throw "VHDX not found for compact: $($info.VhdxPath)"
    }

    Write-Section "Shutdown WSL"
    wsl --shutdown | Out-Host

    Write-Section "Compact VHDX with diskpart"
    $before = (Get-Item $info.VhdxPath).Length
    $escaped = $info.VhdxPath
    $dpScript = @"
select vdisk file="$escaped"
attach vdisk readonly
compact vdisk
detach vdisk
exit
"@
    $tmp = Join-Path $env:TEMP "compact-wsl-vhdx.txt"
    Set-Content -Path $tmp -Value $dpScript -Encoding ASCII
    diskpart /s $tmp | Out-Host
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
    $after = (Get-Item $info.VhdxPath).Length

    Write-Host ("VHDX before: {0} GB" -f [math]::Round($before/1GB,2))
    Write-Host ("VHDX after : {0} GB" -f [math]::Round($after/1GB,2))
    Write-Host ("Freed      : {0} GB" -f [math]::Round(($before-$after)/1GB,2)) -ForegroundColor Green
}

Write-Section "Start - mode: $Mode"

switch ($Mode) {
    "report" {
        Show-StorageReport -TargetDistro $Distro
    }
    "safe" {
        Show-StorageReport -TargetDistro $Distro
        Invoke-DockerCleanup -IncludeVolumes:$false
        if (-not $SkipCompact) {
            Compact-WslVhdx -TargetDistro $Distro
        } else {
            Write-Host "Skip compact by request." -ForegroundColor Yellow
        }
        Show-StorageReport -TargetDistro $Distro
    }
    "aggressive" {
        Show-StorageReport -TargetDistro $Distro
        Invoke-DockerCleanup -IncludeVolumes:$true
        if (-not $SkipCompact) {
            Compact-WslVhdx -TargetDistro $Distro
        } else {
            Write-Host "Skip compact by request." -ForegroundColor Yellow
        }
        Show-StorageReport -TargetDistro $Distro
    }
}

