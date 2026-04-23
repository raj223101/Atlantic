param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$ErrorActionPreference = "Stop"
$NodeRoot = Join-Path $PSScriptRoot ".tools-tar\node-v24.15.0-win-x64"
$NodeExe = Join-Path $NodeRoot "node.exe"

if (-not (Test-Path $NodeExe)) {
    throw "Local Node.js runtime not found at $NodeExe. Run .\setup-node-local.ps1 first."
}

& $NodeExe @Args
exit $LASTEXITCODE

