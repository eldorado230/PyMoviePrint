#if (Ver >> 8) != 0x060403
  #error PyMoviePrint requires Inno Setup 6.4.3.
#endif

[Setup]
AppId={{139498E8-C648-4E75-839A-2B924CD6DC1C}
AppName=PyMoviePrint
AppVersion={#PackageVersion}
AppPublisher=PyMoviePrint
AppPublisherURL=https://github.com/eldorado230/PyMoviePrint
AppSupportURL=https://github.com/eldorado230/PyMoviePrint/issues
VersionInfoVersion={#PackageVersion}
VersionInfoProductName=PyMoviePrint
VersionInfoDescription=PyMoviePrint Windows Setup
DefaultDirName={localappdata}\Programs\PyMoviePrint
DefaultGroupName=PyMoviePrint
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
DisableProgramGroupPage=yes
OutputBaseFilename=PyMoviePrint-Setup
Compression=lzma2
SolidCompression=yes
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\PyMoviePrint.exe
WizardStyle=modern

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\PyMoviePrint"; Filename: "{app}\PyMoviePrint.exe"; WorkingDir: "{app}"
