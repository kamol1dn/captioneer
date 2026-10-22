<#
.SYNOPSIS
  Signs the Skleyka panel and installs the signed result.

.DESCRIPTION
  Same recipe as "multicam switch"\scripts\sign-panel.ps1: CEP 12 on this
  machine verifies signatures even with PlayerDebugMode set, so the panel is
  signed with a local self-signed certificate and unpacked into the CEP
  extensions folder. Signing covers exact bytes; re-run after any panel edit.

  Only panel\ is signed. The ExtendScript the bridge runs lives in
  skleyka\jsx\ and travels with each command, so it never needs re-signing.
#>

param(
    [string]$SignCmd = 'D:\coding\multicam switch\scripts\tools\ZXPSignCmd.exe',
    [switch]$NoTimestamp
)

$ErrorActionPreference = 'Stop'

$source = (Resolve-Path (Join-Path $PSScriptRoot '..\panel')).Path
$certDir = Join-Path $PSScriptRoot '.cert'
$certPath = Join-Path $certDir 'skleyka.p12'
$buildDir = Join-Path $PSScriptRoot '.build'
$zxpPath = Join-Path $buildDir 'skleyka.zxp'
$target = Join-Path $env:APPDATA 'Adobe\CEP\extensions\com.gashtak.skleyka'

# Self-signed development certificate: not a secret, it exists only because
# CEP refuses unsigned packages.
$certPassword = 'gashtak-skleyka-dev'

if (-not (Test-Path $SignCmd)) { throw "ZXPSignCmd.exe not found at $SignCmd" }

$manifestPath = Join-Path $source 'CSXS\manifest.xml'
try { [xml](Get-Content $manifestPath -Raw) | Out-Null }
catch { throw "manifest.xml is not valid XML: $($_.Exception.Message)" }

if (-not (Test-Path $certPath)) {
    New-Item -ItemType Directory -Path $certDir -Force | Out-Null
    & $SignCmd -selfSignedCert US CA 'Gashtak' 'Gashtak Skleyka Dev' $certPassword $certPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $certPath)) { throw 'Certificate generation failed.' }
}

if (Test-Path $buildDir) { Remove-Item $buildDir -Recurse -Force }
New-Item -ItemType Directory -Path $buildDir -Force | Out-Null
$staging = Join-Path $buildDir 'panel'
Copy-Item -Path $source -Destination $staging -Recurse -Force
# Dot-files can be skipped by a recursive copy; .debug opens the remote
# debugging ports (8093 headless, 8094 panel).
Copy-Item (Join-Path $source '.debug') (Join-Path $staging '.debug') -Force

$signArgs = @('-sign', $staging, $zxpPath, $certPath, $certPassword)
if (-not $NoTimestamp) { $signArgs += @('-tsa', 'http://timestamp.digicert.com') }
& $SignCmd @signArgs
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $zxpPath)) {
    if (-not $NoTimestamp) {
        Write-Warning 'Signing failed. Retrying without the timestamp authority.'
        & $SignCmd -sign $staging $zxpPath $certPath $certPassword
    }
    if (-not (Test-Path $zxpPath)) { throw 'Signing failed.' }
}

$zipCopy = Join-Path $buildDir 'skleyka.zip'
Copy-Item $zxpPath $zipCopy -Force
if (Test-Path $target) { Remove-Item $target -Recurse -Force }
New-Item -ItemType Directory -Path $target -Force | Out-Null
Expand-Archive -Path $zipCopy -DestinationPath $target -Force
if (-not (Test-Path (Join-Path $target 'META-INF\signatures.xml'))) { throw 'Installed package is not signed.' }

Write-Host "Installed signed panel to $target" -ForegroundColor Green
Write-Host 'Fully quit Premiere Pro and reopen it. The bridge starts on its own;'
Write-Host 'Window > Extensions > Gashtak Skleyka shows its status.'
