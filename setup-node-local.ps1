param(
    [string]$Version = "24.15.0"
)

$ErrorActionPreference = "Stop"

$ToolsZipRoot = Join-Path $PSScriptRoot ".tools"
$ToolsExtractRoot = Join-Path $PSScriptRoot ".tools-tar"
$ZipPath = Join-Path $ToolsZipRoot "node-v$Version-win-x64.zip"
$ExtractDir = Join-Path $ToolsExtractRoot "node-v$Version-win-x64"
$NodeExe = Join-Path $ExtractDir "node.exe"
$NpmPackageJson = Join-Path $ExtractDir "node_modules\npm\package.json"
$DownloadUrl = "https://nodejs.org/dist/v$Version/node-v$Version-win-x64.zip"

New-Item -ItemType Directory -Force -Path $ToolsZipRoot | Out-Null
New-Item -ItemType Directory -Force -Path $ToolsExtractRoot | Out-Null

if (-not (Test-Path $ZipPath)) {
    Write-Host "Downloading Node.js v$Version from $DownloadUrl"
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $ZipPath
} else {
    Write-Host "Using existing archive $ZipPath"
}

if ((Test-Path $NodeExe) -and (Test-Path $NpmPackageJson)) {
    Write-Host "Local Node.js is already ready at $ExtractDir"
} else {
    Write-Host "Extracting Node.js with tar.exe into $ToolsExtractRoot"
    tar -xf $ZipPath -C $ToolsExtractRoot
}

& $NodeExe --version
& $NodeExe (Join-Path $ExtractDir "node_modules\npm\bin\npm-cli.js") --version
