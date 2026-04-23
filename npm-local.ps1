param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
$NodeRoot = Join-Path $PSScriptRoot ".tools-tar\node-v24.15.0-win-x64"
$NodeExe = Join-Path $NodeRoot "node.exe"
$NpmCli = Join-Path $NodeRoot "node_modules\npm\bin\npm-cli.js"

if (-not (Test-Path $NodeExe)) {
    throw "Local Node.js runtime not found at $NodeExe. Run .\setup-node-local.ps1 first."
}
if (-not (Test-Path $NpmCli)) {
    throw "Local npm CLI not found at $NpmCli. Re-run .\setup-node-local.ps1 if needed."
}

& $NodeExe $NpmCli @Args
exit $LASTEXITCODE

