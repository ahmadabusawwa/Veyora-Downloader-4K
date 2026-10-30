#define AppVersion "2.0.3"
[Setup]
AppId={{CB5D7202-462E-4BDF-A6BD-92449F02E003}
AppName=Veyora Pro 2.0.3 Review
AppVersion={#AppVersion}
AppPublisher=Veyora Pro
DefaultDirName={localappdata}\Programs\Veyora Pro 2.0.3 Review
DefaultGroupName=Veyora Pro 2.0.3 Review
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
Name: "{group}\Veyora Pro 2.0.3 Review"; Filename: "{app}\Veyora-Pro.exe"
Name: "{autodesktop}\Veyora Pro 2.0.3 Review"; Filename: "{app}\Veyora-Pro.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\Veyora-Pro.exe"; Description: "Launch Veyora Pro"; Flags: nowait postinstall skipifsilent
; No UninstallDelete entries: settings, history, models and downloaded files are outside {app}.
