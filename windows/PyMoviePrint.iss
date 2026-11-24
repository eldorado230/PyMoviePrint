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
ChangesAssociations=yes
UninstallDisplayIcon={app}\PyMoviePrint.exe
WizardStyle=modern

[Tasks]
Name: explorer; Description: "Add 'Create video contact sheet' to the Windows Explorer context menu"; Flags: unchecked

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\PyMoviePrint"; Filename: "{app}\PyMoviePrint.exe"; WorkingDir: "{app}"

[Code]
const
  VerbLabel = 'Create video contact sheet';
  VerbOwner = 'PyMoviePrintOwner';

function MatchesValue(const Key, Name, Data: String): Boolean;
var
  Current: String;
begin
  Result := RegQueryStringValue(HKCU, Key, Name, Current) and (Current = Data);
end;

function OwnedVerb(const Key: String): Boolean;
var
  Command: String;
begin
  Result := RegQueryStringValue(HKCU, Key + '\command', '', Command)
    and (Command <> '') and MatchesValue(Key, VerbOwner, Command)
    and MatchesValue(Key, '', VerbLabel) and MatchesValue(Key, 'MultiSelectModel', 'Single');
end;

procedure RemoveVerb(const Key, Command: String);
begin
  if MatchesValue(Key + '\command', '', Command) then
    RegDeleteValue(HKCU, Key + '\command', '');
  if MatchesValue(Key, '', VerbLabel) then
    RegDeleteValue(HKCU, Key, '');
  if MatchesValue(Key, 'MultiSelectModel', 'Single') then
    RegDeleteValue(HKCU, Key, 'MultiSelectModel');
  if MatchesValue(Key, VerbOwner, Command) then
    RegDeleteValue(HKCU, Key, VerbOwner);
  RegDeleteKeyIfEmpty(HKCU, Key + '\command');
  RegDeleteKeyIfEmpty(HKCU, Key);
end;

procedure UpdateExplorerVerbs(Enable: Boolean);
var
  Extensions: TArrayOfString;
  Index: Integer;
  Key, Command, Previous: String;
begin
  SetArrayLength(Extensions, 6);
  Extensions[0] := '.mp4';
  Extensions[1] := '.avi';
  Extensions[2] := '.mov';
  Extensions[3] := '.mkv';
  Extensions[4] := '.flv';
  Extensions[5] := '.wmv';
  Command := '"' + ExpandConstant('{app}\PyMoviePrint.exe') + '" --preview "%1"';
  for Index := 0 to GetArrayLength(Extensions) - 1 do
  begin
    Key := 'Software\Classes\SystemFileAssociations\' + Extensions[Index] + '\shell\PyMoviePrint.ContactSheet';
    if OwnedVerb(Key) then
    begin
      RegQueryStringValue(HKCU, Key, VerbOwner, Previous);
      if not Enable then
        RemoveVerb(Key, Previous)
      else if Previous <> Command then
      begin
        if RegWriteStringValue(HKCU, Key, VerbOwner, Command) then
          if not RegWriteStringValue(HKCU, Key + '\command', '', Command) then
            RegWriteStringValue(HKCU, Key, VerbOwner, Previous);
      end;
    end
    else if Enable and not RegKeyExists(HKCU, Key) and not RegKeyExists(HKLM, Key) then
    begin
      if not (RegWriteStringValue(HKCU, Key, VerbOwner, Command)
        and RegWriteStringValue(HKCU, Key, '', VerbLabel)
        and RegWriteStringValue(HKCU, Key, 'MultiSelectModel', 'Single')
        and RegWriteStringValue(HKCU, Key + '\command', '', Command)) then
      begin
        RemoveVerb(Key, Command);
        Log('Could not register the Explorer menu for ' + Extensions[Index]);
      end;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    UpdateExplorerVerbs(WizardIsTaskSelected('explorer'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    UpdateExplorerVerbs(False);
end;
