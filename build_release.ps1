param(
    [switch]$InstallerOnly
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$versionMatch = Select-String -Path "app\config.py" -Pattern 'APP_VERSION\s*=\s*"([^"]+)"'
if (-not $versionMatch) {
    throw "Could not read APP_VERSION from app\config.py"
}
$AppVersion = $versionMatch.Matches[0].Groups[1].Value
$AppName = "Digital Service Pakistan Employee"

if (-not $InstallerOnly) {
    Write-Host "Building PyInstaller app version $AppVersion..."
    python -m PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --name "$AppName" `
        --icon "$Root\assets\app_icon.ico" `
        --add-data "$Root\assets;assets" `
        --hidden-import "win32timezone" `
        --distpath "dist" `
        --workpath "build" `
        --specpath "build" `
        "main.py"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE"
    }
}

$InnoCompiler = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $InnoCompiler) {
    $candidate = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (Test-Path $candidate) {
        $InnoCompiler = Get-Item $candidate
    }
}
if (-not $InnoCompiler) {
    throw "Inno Setup Compiler (ISCC.exe) was not found. Install Inno Setup 6 or add ISCC.exe to PATH."
}
$InnoCompilerPath = if ($InnoCompiler.Source) { $InnoCompiler.Source } else { $InnoCompiler.FullName }

Write-Host "Building installer version $AppVersion..."
& $InnoCompilerPath "/DMyAppVersion=$AppVersion" "installer\DigitalServicePakistanEmployee.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE"
}

$InstallerPath = Join-Path $Root "dist\installer\DigitalServicePakistanEmployeeSetup-$AppVersion.exe"
Write-Host "Done. Installer: $InstallerPath"