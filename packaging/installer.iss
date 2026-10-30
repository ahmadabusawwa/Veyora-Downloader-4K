#define AppVersion "2.0.0"
[Setup]
AppId={{2C64AD91-899D-44ED-BDC8-77AA65AB119F}
AppName=Veyora Pro
AppVersion={#AppVersion}
AppPublisher=Veyora Pro
DefaultDirName={localappdata}\Programs\Veyora Pro
DefaultGroupName=Veyora Pro
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\setup
OutputBaseFilename=Veyora-Pro-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Veyora-Pro.exe
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
DisableProgramGroupPage=yes
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Files]
Source: "..\dist\Veyora-Pro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Veyora Pro"; Filename: "{app}\Veyora-Pro.exe"
Name: "{autodesktop}\Veyora Pro"; Filename: "{app}\Veyora-Pro.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\Veyora-Pro.exe"; Description: "Launch Veyora Pro"; Flags: nowait postinstall skipifsilent
; No UninstallDelete entries: settings, history, models and downloaded files are outside {app}.
