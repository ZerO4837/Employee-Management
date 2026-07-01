#define MyAppName "Digital Service Pakistan Employee"
#ifndef MyAppVersion
#define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "Digital Service Pakistan"
#define MyAppExeName "Digital Service Pakistan Employee.exe"

[Setup]
AppId={{7F3EA8D6-4560-4C48-8B3B-91E4DB9D0A41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\Digital Service Pakistan\Employee Management
DefaultGroupName=Digital Service Pakistan
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=DigitalServicePakistanEmployeeSetup-{#MyAppVersion}
SetupIconFile=..\assets\app_icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\Digital Service Pakistan Employee\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent unchecked
; Silent auto-updates run with /VERYSILENT, so the wizard's own "completed"
; page never shows. This launches the app in a lightweight notice-only mode
; to pop a desktop "update complete, please reopen" alert. Gated to silent
; runs so a normal manual (wizard) install - which already has its own
; completion page and Launch checkbox above - doesn't double up.
Filename: "{app}\{#MyAppExeName}"; Parameters: "--update-notice"; Flags: nowait; Check: IsSilentUpdate

[Code]
function IsSilentUpdate(): Boolean;
begin
  Result := WizardSilent();
end;