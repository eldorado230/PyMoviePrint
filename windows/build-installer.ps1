[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$Iscc,
    [ValidateRange(1, 99)][int]$Revision = 2,
    [switch]$BuildUpgradeBaseline
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$cache = Join-Path $root 'build\windows-installer'
$venv = Join-Path $cache 'venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'
$work = Join-Path $cache ('package-' + [guid]::NewGuid().ToString('N'))
$output = Join-Path $root 'dist\windows-installer-rc'
$isccFullPath = (Get-Command $Iscc -CommandType Application).Source
New-Item -ItemType Directory -Force -Path $work, $output | Out-Null

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Executable failed with exit code $LASTEXITCODE" }
}

Push-Location $root
try {
    Invoke-Checked $Python @('-c', 'import struct, sys; assert sys.version_info[:2] == (3, 11) and struct.calcsize("P") == 8')
    if (-not (Test-Path -LiteralPath $venvPython)) {
        Invoke-Checked $Python @('-m', 'venv', $venv)
    }
    Invoke-Checked $venvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'windows\build-requirements.txt')
    $dist = Join-Path $work 'dist'
    Invoke-Checked $venvPython @(
        '-m','PyInstaller','--noconfirm','--onedir','--windowed','--name','PyMoviePrint',
        '--paths',$root,'--specpath',$work,'--workpath',(Join-Path $work 'work'),'--distpath',$dist,
        '--collect-all','customtkinter','--collect-all','tkinterdnd2',
        '--hidden-import','video_processing','--hidden-import','image_grid',
        '--hidden-import','state_manager','--hidden-import','project_io',
        '--hidden-import','workspace_tools','--hidden-import','face_analysis',
        '--hidden-import','movieprint_maker','--hidden-import','version',
        '--add-data',((Join-Path $root 'assets\movieprint-studio-v1.png') + ';assets'),
        (Join-Path $PSScriptRoot 'installer_entry.py')
    )
    $app = Join-Path $dist 'PyMoviePrint'
    Invoke-Checked $venvPython @('windows\stage_runtime.py', $app, $cache)
    $version = & $venvPython -c 'import version; print(version.__version__)'
    if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw 'Could not read app version' }
    $manifestPath = Join-Path $app 'dependency-manifest.json'
    $manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
    $manifest | Add-Member -NotePropertyName installer_compiler_version -NotePropertyValue '6.4.3'
    $manifest | Add-Member -NotePropertyName installer_compiler_sha256 -NotePropertyValue (Get-FileHash -LiteralPath $isccFullPath).Hash.ToLowerInvariant()
    $manifest | Add-Member -NotePropertyName installer_revision -NotePropertyValue ''
    $script = Join-Path $PSScriptRoot 'PyMoviePrint.iss'
    if ($BuildUpgradeBaseline) {
        if ($Revision -lt 2) { throw 'A baseline requires a revision of at least 2' }
        $manifest.installer_revision = "$version.$($Revision - 1)"
        $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
        Invoke-Checked $isccFullPath @(
            '/Qp', "/DAppSource=$app", "/DPackageVersion=$($manifest.installer_revision)", "/O$output",
            '/FPyMoviePrint-Setup-Baseline', $script
        )
    }
    $manifest.installer_revision = "$version.$Revision"
    $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    Invoke-Checked $isccFullPath @('/Qp', "/DAppSource=$app", "/DPackageVersion=$($manifest.installer_revision)", "/O$output", $script)
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $output 'dependency-manifest.json') -Force
    $setup = Get-Item -LiteralPath (Join-Path $output 'PyMoviePrint-Setup.exe')
    Write-Host "$($setup.FullName) ($($setup.Length) bytes)"
    $installerSha256 = (Get-FileHash -LiteralPath $setup.FullName).Hash.ToLowerInvariant()
    "$installerSha256  $($setup.Name)" | Set-Content -LiteralPath ($setup.FullName + '.sha256') -Encoding ascii
    Write-Host "SHA-256 $installerSha256"
} finally {
    Pop-Location
    $resolvedWork = (Resolve-Path -LiteralPath $work).Path
    if ((Split-Path -Parent $resolvedWork) -eq $cache -and (Split-Path -Leaf $resolvedWork) -like 'package-*') {
        Remove-Item -LiteralPath $resolvedWork -Recurse -Force
    }
}
