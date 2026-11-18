param(
 [Parameter(Mandatory=$true)][string]$Installer,
 [Parameter(Mandatory=$true)][string]$PublicInstallerHttpsUrl,
 [string]$Version='3.4.0',
 [string]$Notes='WoSB Workbench update'
)
$ErrorActionPreference='Stop'
if (!(Test-Path -LiteralPath $Installer)) { throw 'Installer does not exist' }
if ($PublicInstallerHttpsUrl -notmatch '^https://') { throw 'HTTPS installer URL required' }
$manifest=[ordered]@{
 version=$Version
 installer_url=$PublicInstallerHttpsUrl
 sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $Installer).Hash.ToLowerInvariant()
 notes=$Notes
}
$path=Join-Path (Split-Path -Parent (Resolve-Path -LiteralPath $Installer)) 'update.json'
$json=$manifest | ConvertTo-Json
$utf8NoBom=New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($path,$json,$utf8NoBom)
Write-Host "Update manifest written to: $path"
Write-Host 'Publish the update.json manifest and Setup.exe to your chosen HTTPS release host.'
