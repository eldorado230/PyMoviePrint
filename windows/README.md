# Windows installer prototype

This proof of concept starts from PyMoviePrint v1.1.1 and targets Windows x64. The installed app retains the v1.1.1 version. Two installer-only revision numbers exercise the upgrade. The installer keeps its binaries in `%LOCALAPPDATA%\Programs\PyMoviePrintPrototype` and keeps settings and logs in the separate `%LOCALAPPDATA%\PyMoviePrintPrototype` folder. Uninstall leaves that private data and user projects intact.

## Build

Use x64 Python 3.11 and Inno Setup 6.4.3. The [official Inno Setup 6.4.3 package](https://github.com/jrsoftware/issrc/releases/tag/is-6_4_3) supports installation into a temporary folder with `/PORTABLE=1`. Pass the compiler path explicitly. The build verifies the pinned FFmpeg archive before extracting it and writes the installer, dependency manifest, and optionally an upgrade baseline under `dist/windows-installer`.

```powershell
.\windows\build-installer.ps1 -Python 'C:\path\to\python.exe' -Iscc 'C:\path\to\ISCC.exe' -BuildUpgradeBaseline
```

The installer contains a PyInstaller one-directory GUI, Python, the app dependencies, and private FFmpeg, FFprobe, and FFplay executables with their shared libraries. It makes no changes to the user's PATH or file associations. The installed launcher chooses the private media executables explicitly.

## Acceptance

Run the prototype workflow on a disposable Windows desktop. It launches the installers with an Administrators-disabled token, checks the per-user uninstall registration, and starts the installed app with external Python and FFmpeg absent from its PATH. The test checks a 25-thumbnail preview, a decoded PNG, the installed FFplay process with an audio/video fixture, preserved settings after upgrade, and project preservation through uninstall. The hosted test uses an SDL dummy audio device. A listening check and a fresh end-user Windows image are separate from the hosted test.

## Redistribution review

The installer is for internal evaluation. `dependency-manifest.json` records build-time package versions, declared licence metadata, copied notices, the pinned FFmpeg revision and recipes, the FFmpeg configure output, and hashes of the shipped media binaries. Direct versions and the archive are pinned. Transitive resolution and the installer bytes are not fully reproducible.

The media tools use the upstream shared LGPL build with `--enable-version3` and without `--enable-gpl` or `--enable-nonfree`. The upstream LGPLv3 notice and source/build pointers accompany the prototype. Before public distribution, review corresponding-source delivery for the exact archive and embedded dependencies, the separate OpenCV video runtime and other wheel contents, and the Inno Setup tooling terms. Decide separately about code signing and Explorer integration. See [FFmpeg's licensing guidance](https://ffmpeg.org/legal.html), the [PyInstaller licence exception](https://pyinstaller.org/en/stable/license.html), and [Inno Setup licensing](https://jrsoftware.org/isorder.php).

Thanks to [primeinc](https://github.com/primeinc/PyMoviePrint) for the earlier packaging investigation and the pinned upstream FFmpeg archive lead.
