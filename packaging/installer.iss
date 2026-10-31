#define AppVersion "2.0.3"
[Setup]
AppId={{6A1C89FC-1F56-4B25-B2DE-203004F00001}
AppName=Veyora Pro 2.0.3 Regression Review
AppVersion={#AppVersion}
AppPublisher=Veyora Pro
DefaultDirName={localappdata}\Programs\Veyora Pro 2.0.3 Regression Review
DefaultGroupName=Veyora Pro 2.0.3 Regression Review
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\setup
OutputBaseFilename=Veyora-Pro-{#AppVersion}-Setup
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
Name: "{group}\Veyora Pro 2.0.3 Regression Review"; Filename: "{app}\Veyora-Pro.exe"
Name: "{autodesktop}\Veyora Pro 2.0.3 Regression Review"; Filename: "{app}\Veyora-Pro.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\Veyora-Pro.exe"; Description: "Launch Veyora Pro"; Flags: nowait postinstall skipifsilent
; No UninstallDelete entries: settings, history, models and downloaded files are outside {app}.
