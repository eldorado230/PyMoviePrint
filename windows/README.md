# Windows installer release candidate

PyMoviePrint v1.2.0 targets Windows 10 and 11 x64. It installs per user to `%LOCALAPPDATA%\Programs\PyMoviePrint` and stores settings and logs in `%LOCALAPPDATA%\PyMoviePrint`. On first launch it copies valid settings from `%LOCALAPPDATA%\PyMoviePrintPrototype` if no official settings file exists. The prototype installation and its settings remain available. Uninstall preserves settings and user projects.

## Build

Use x64 Python 3.11, Microsoft Visual Studio 2022 C++ Build Tools with a Windows SDK, and Inno Setup 6.4.3. The [official Inno Setup 6.4.3 package](https://github.com/jrsoftware/issrc/releases/tag/is-6_4_3) supports installation into a temporary folder with `/PORTABLE=1`. Pass the compiler path explicitly. The build verifies the pinned FFmpeg archive and NumPy source and writes the unsigned installer, its SHA-256, the dependency manifest, the NumPy source, and optionally a test upgrade baseline under `dist/windows-installer-rc/revision-3` by default. Windows may show an unrecognised publisher or SmartScreen warning.

```powershell
.\windows\build-installer.ps1 -Python 'C:\path\to\python.exe' -Iscc 'C:\path\to\ISCC.exe' -BuildUpgradeBaseline
```

The installer contains a PyInstaller one-directory GUI, Python, the app dependencies, and private FFmpeg, FFprobe, and FFplay executables with their shared libraries. The installed launcher chooses its private media executables explicitly. The optional **Create video contact sheet** Explorer action opens one selected video and builds an editable preview. It is off by default and available under **Show more options** on Windows 11. It leaves the default video app and the user's PATH alone.

## Acceptance

The Windows installer workflow runs on a disposable hosted desktop. It launches the installers with an Administrators-disabled token, checks per-user registration, and starts the installed app with external Python and FFmpeg absent from its PATH. It exercises migration from prototype settings, a 25-thumbnail preview, PNG decoding, FFplay with an audio/video fixture, upgrade, and preservation of user data after uninstall. Listening on a fresh end-user Windows image remains a separate acceptance check.

## Redistribution review

The installer is for private evaluation. `dependency-manifest.json` records build-time package versions and notices, standalone FFmpeg build configuration and binary hashes, and the exact OpenCV FFmpeg plugin and its upstream source references. The installer also includes the Intel IPP notices required by the OpenCV wheel. Direct versions and the FFmpeg archive are pinned. Transitive package resolution can vary between builds.

NumPy 1.26.4 is built from the pinned upstream source with its internal linear algebra routines. The package uses the system Universal CRT on Windows 10 and 11. The manifest lists the Visual C++ runtime files carried with Python and the native binaries that import them. Public distribution is subject to the applicable [Microsoft Visual C++ redistribution terms](https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files) and [CPython runtime notice](https://github.com/python/cpython/blob/v3.11.14/PC/crtlicense.txt).

The standalone tools use the shared LGPLv3 build. The OpenCV wheel ships a separate plugin built with FFmpeg 4.4.3, libvpx 1.12.0 and AOM 3.5.0. Public distribution still requires a complete corresponding-source package for the shipped components, including the libraries linked into the standalone FFmpeg DLLs. See [FFmpeg's licensing guidance](https://ffmpeg.org/legal.html), the [OpenCV plugin build recipe](https://github.com/opencv/opencv_3rdparty/tree/7dd0d4f1d6fe75f05f3d3b5e38cbc96c1a2d2809/ffmpeg), and the [PyInstaller licence exception](https://pyinstaller.org/en/stable/license.html).

Thanks to [primeinc](https://github.com/primeinc/PyMoviePrint) for the earlier packaging investigation and the pinned upstream FFmpeg archive lead.
