# Windows installer

The final Windows installer for PyMoviePrint v1.2.0 is revision `1.2.0.4`.

PyMoviePrint v1.2.0 targets Windows 10 and 11 x64. It installs per user to `%LOCALAPPDATA%\Programs\PyMoviePrint` and stores settings and logs in `%LOCALAPPDATA%\PyMoviePrint`. On first launch it copies valid settings from `%LOCALAPPDATA%\PyMoviePrintPrototype` if no official settings file exists. The prototype installation and its settings remain available. Uninstall preserves settings and user projects.

## Build

Use x64 Python 3.11, Microsoft Visual Studio 2022 C++ Build Tools with a Windows SDK, and Inno Setup 6.4.3. The [official Inno Setup 6.4.3 package](https://github.com/jrsoftware/issrc/releases/tag/is-6_4_3) supports installation into a temporary folder with `/PORTABLE=1`. Pass the compiler path explicitly. The build verifies the pinned FFmpeg archive and NumPy source and writes the unsigned installer, its SHA-256, the dependency manifest, the NumPy source, and optionally a test upgrade baseline under `dist/windows-installer-rc/revision-3` by default. Windows may show an unrecognised publisher or SmartScreen warning.

```powershell
.\windows\build-installer.ps1 -Python 'C:\path\to\python.exe' -Iscc 'C:\path\to\ISCC.exe' -BuildUpgradeBaseline
```

The installer contains a PyInstaller one-directory GUI, Python, the app dependencies, and private FFmpeg, FFprobe, and FFplay executables with their shared libraries. The installed launcher chooses its private media executables explicitly. The optional **Create video contact sheet** Explorer action opens one selected video and builds an editable preview. It is off by default and available under **Show more options** on Windows 11. It leaves the default video app and the user's PATH alone.

## Acceptance

The Windows installer workflow runs on a disposable hosted desktop. It launches the installers with an Administrators-disabled token, checks per-user registration, and starts the installed app with external Python and FFmpeg absent from its PATH. It exercises migration from prototype settings, a 25-thumbnail preview, PNG decoding, FFplay with an audio/video fixture, upgrade, and preservation of user data after uninstall. Listening on a fresh end-user Windows image remains a separate acceptance check.

## Retained distribution files

Keep the dependency manifest, corresponding-source packages, and third-party notices with the installer.

Thanks to [primeinc](https://github.com/primeinc/PyMoviePrint) for the earlier packaging investigation and the pinned upstream FFmpeg archive lead.
