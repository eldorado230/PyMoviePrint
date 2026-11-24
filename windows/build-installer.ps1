[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$Iscc,
    [ValidateRange(3, 99)][int]$Revision = 3,
    [switch]$BuildUpgradeBaseline
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$cache = Join-Path $root 'build\windows-installer'
$venv = Join-Path $cache 'venv-system-ucrt'
$venvPython = Join-Path $venv 'Scripts\python.exe'
$work = Join-Path $cache ('package-' + [guid]::NewGuid().ToString('N'))
$output = Join-Path $root "dist\windows-installer-rc\revision-$Revision"
$isccFullPath = (Get-Command $Iscc -CommandType Application).Source
if (Test-Path -LiteralPath (Join-Path $output 'PyMoviePrint-Setup.exe')) {
    throw "An installer already exists for revision $Revision. Use a new revision to preserve it."
}
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
    $numpySource = Join-Path $cache 'numpy-1.26.4.tar.gz'
    $numpySourceHash = '2a02aba9ed12e4ac4eb3ea9421c420301a0c6460d9830d74a9df87efa4912010'
    if (-not (Test-Path -LiteralPath $numpySource)) {
        $numpyUrl = 'https://files.pythonhosted.org/packages/65/6e/09db70a523a96d25e115e71cc56a6f9031e7b8cd166c1ac8438307c14058/numpy-1.26.4.tar.gz'
        $download = Join-Path $work 'numpy-1.26.4.tar.gz'
        Invoke-WebRequest -Uri $numpyUrl -OutFile $download
        if ((Get-FileHash -LiteralPath $download).Hash.ToLowerInvariant() -ne $numpySourceHash) {
            throw 'Downloaded NumPy source does not match the pinned SHA-256.'
        }
        Move-Item -LiteralPath $download -Destination $numpySource
    }
    if ((Get-FileHash -LiteralPath $numpySource).Hash.ToLowerInvariant() -ne $numpySourceHash) {
        throw "NumPy source does not match the pinned SHA-256: $numpySource"
    }
    $wheelDirectory = Join-Path $work 'wheels'
    Invoke-Checked $venvPython @(
        '-m', 'pip', 'wheel', '--disable-pip-version-check', '--no-deps', '--wheel-dir', $wheelDirectory,
        '-Csetup-args=--vsenv', '-Csetup-args=-Dblas=none', '-Csetup-args=-Dlapack=none',
        '-Csetup-args=-Dallow-noblas=true', $numpySource
    )
    $numpyWheel = Get-Item -LiteralPath (Join-Path $wheelDirectory 'numpy-1.26.4-cp311-cp311-win_amd64.whl')
    Invoke-Checked $venvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '--force-reinstall', '--no-deps', $numpyWheel.FullName)
    Invoke-Checked $venvPython @('-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'windows\build-requirements.txt')
    $dist = Join-Path $work 'dist'
    Invoke-Checked $venvPython @(
        '-m','PyInstaller','--noconfirm','--onedir','--windowed','--name','PyMoviePrint',
        '--icon',(Join-Path $root 'assets\movieprint-studio-v1.ico'),
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
    $manifest.numpy.source_sha256 = $numpySourceHash
    $manifest.numpy.wheel_sha256 = (Get-FileHash -LiteralPath $numpyWheel.FullName).Hash.ToLowerInvariant()
    $manifest | Add-Member -NotePropertyName installer_compiler_version -NotePropertyValue '6.4.3'
    $manifest | Add-Member -NotePropertyName installer_compiler_sha256 -NotePropertyValue (Get-FileHash -LiteralPath $isccFullPath).Hash.ToLowerInvariant()
    $manifest | Add-Member -NotePropertyName installer_revision -NotePropertyValue ''
    $script = Join-Path $PSScriptRoot 'PyMoviePrint.iss'
    if ($BuildUpgradeBaseline) {
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
    Copy-Item -LiteralPath $numpySource -Destination (Join-Path $output 'numpy-1.26.4.tar.gz')
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
