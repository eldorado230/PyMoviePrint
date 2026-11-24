#if (Ver >> 8) != 0x060403
  #error This prototype requires Inno Setup 6.4.3.
#endif

[Setup]
AppId={{A723B754-7B1E-4C1F-9F8B-64A1A9A411F2}
AppName=PyMoviePrint Windows Prototype
AppVersion={#PackageVersion}
AppPublisher=PyMoviePrint
DefaultDirName={localappdata}\Programs\PyMoviePrintPrototype
DefaultGroupName=PyMoviePrint Windows Prototype
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
Name: "{userprograms}\PyMoviePrint Windows Prototype"; Filename: "{app}\PyMoviePrint.exe"; WorkingDir: "{app}"
