param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectUrl,

    [Parameter(Mandatory = $true)]
    [string]$AnonKey,

    [Parameter(Mandatory = $true)]
    [string]$EmployeeSyncSecret
)

$ErrorActionPreference = "Stop"
$CleanUrl = $ProjectUrl.Trim().TrimEnd("/")
$CleanUrl = $CleanUrl -replace "/rest/v1$", ""
$TargetDir = Join-Path $env:LOCALAPPDATA "Digital Service Pakistan\Employee Management"
$TargetPath = Join-Path $TargetDir "supabase_config.json"

New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
$config = [ordered]@{
    enabled = $true
    url = $CleanUrl
    anon_key = $AnonKey.Trim()
    admin_secret = ""
    employee_sync_secret = $EmployeeSyncSecret.Trim()
}
$config | ConvertTo-Json | Set-Content -Path $TargetPath -Encoding UTF8
Write-Host "Employee cloud config written to: $TargetPath"