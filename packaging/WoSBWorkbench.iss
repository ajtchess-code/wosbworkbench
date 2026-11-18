; WoSB Workbench installer (Inno Setup 6). Built by packaging\Build-Windows.ps1, which passes
;   /DMyAppVersion=<workbench_db.VERSION>   (single source of truth for the version)
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif
#define MyAppName "WoSB Workbench"
#define MyAppExeName "WoSBWorkbench.exe"

[Setup]
AppId={{C8EE0D05-893C-4E89-9AE3-46D7B1048334}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
AppPublisher=Local WoSB research
DefaultDirName={localappdata}\Programs\WoSBWorkbench
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\Installer
OutputBaseFilename=WoSBWorkbench-{#MyAppVersion}-Setup
SetupIconFile=..\assets\wosb-workbench.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
; Close a running Workbench (it holds a named mutex) instead of failing on locked files.
AppMutex=WoSBWorkbenchMutex
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
ShowLanguageDialog=no
; 64-bit app (64-bit Python build): {commonpf}/{sys} resolve to the 64-bit folders. Needs Inno Setup 6.3+.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[InstallDelete]
; PyInstaller one-folder builds keep libraries in _internal. Clearing it on upgrade stops
; stale libraries from an older build shadowing new ones. User data lives elsewhere
; (%LOCALAPPDATA%\WoSBWorkbench) and is never touched here.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\WoSBWorkbench\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\WoSB Workbench"; Filename: "{app}\{#MyAppExeName}"
Name: "{autoprograms}\WoSB Workbench (logs folder)"; Filename: "{localappdata}\WoSBWorkbench\Logs"; Flags: foldershortcut
Name: "{autodesktop}\WoSB Workbench"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch WoSB Workbench"; Flags: nowait postinstall skipifsilent
Filename: "https://ffmpeg.org/download.html"; Description: "Open the FFmpeg download page (video recording)"; Flags: postinstall shellexec skipifsilent unchecked; Check: ToolMissing('ffmpeg')
Filename: "https://www.wireshark.org/download.html"; Description: "Open the Wireshark/TShark download page (packet capture)"; Flags: postinstall shellexec skipifsilent unchecked; Check: ToolMissing('tshark')
Filename: "https://npcap.com/#download"; Description: "Open the Npcap download page (capture driver)"; Flags: postinstall shellexec skipifsilent unchecked; Check: ToolMissing('npcap')

[Code]
var
  ToolsPage: TOutputMsgMemoWizardPage;
  DeleteUserData: Boolean;

function OnPath(const Exe: string): Boolean;
var
  Paths, Dir: string;
  P: Integer;
begin
  Result := False;
  Paths := GetEnv('PATH') + ';';
  while (not Result) and (Length(Paths) > 0) do
  begin
    P := Pos(';', Paths);
    Dir := Trim(Copy(Paths, 1, P - 1));
    Delete(Paths, 1, P);
    if (Dir <> '') and FileExists(AddBackslash(Dir) + Exe) then Result := True;
  end;
end;

function ToolFound(const Name: string): Boolean;
begin
  if Name = 'ffmpeg' then
    Result := OnPath('ffmpeg.exe') or FileExists(ExpandConstant('{localappdata}\Microsoft\WinGet\Links\ffmpeg.exe'))
  else if Name = 'tshark' then
    Result := OnPath('tshark.exe') or FileExists(ExpandConstant('{commonpf}\Wireshark\tshark.exe'))
  else if Name = 'npcap' then
    Result := DirExists(ExpandConstant('{sys}\Npcap'))
  else
    Result := False;
end;

function ToolMissing(const Name: string): Boolean;
begin
  Result := not ToolFound(Name);
end;

function Mark(const Name, Purpose: string): string;
begin
  if ToolFound(Name) then Result := '  [found]    ' + Purpose
  else Result := '  [missing]  ' + Purpose;
end;

procedure InitializeWizard;
begin
  ToolsPage := CreateOutputMsgMemoPage(wpSelectTasks, 'Optional helper tools',
    'WoSB Workbench works without these; they enable recording and capture features.',
    'Missing tools can be installed later. Download links are offered on the last page, and Settings → Run setup wizard re-checks them.',
    Mark('ffmpeg', 'FFmpeg — gameplay video recording and evidence clips') + #13#10 +
    Mark('tshark', 'Wireshark / TShark — passive packet capture and auto-capture') + #13#10 +
    Mark('npcap', 'Npcap — capture driver used by TShark') + #13#10#13#10 +
    '  Optional for datamining: .NET SDK + "dotnet tool install --global ilspycmd" (C# decompile).');
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  DeleteUserData := False;
  if UninstallSilent then Exit;
  DeleteUserData := MsgBox('Also delete your WoSB Workbench data?' + #13#10#13#10 +
    'This removes your wiki database, recovery reports, captures and settings in' + #13#10 +
    ExpandConstant('{localappdata}\WoSBWorkbench') + #13#10#13#10 +
    'Choose No to keep them for a later reinstall (recommended).',
    mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and DeleteUserData then
    DelTree(ExpandConstant('{localappdata}\WoSBWorkbench'), True, True, True);
end;
