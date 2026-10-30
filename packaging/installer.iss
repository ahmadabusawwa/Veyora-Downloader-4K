#define AppVersion "2.0.3"
[Setup]
AppId={{7AA3F132-88B0-4ED0-B8D0-203031FA0011}
AppName=Veyora Pro 2.0.3 Repair Review
AppVersion={#AppVersion}
AppPublisher=Veyora Pro
DefaultDirName={localappdata}\Programs\Veyora Pro 2.0.3 Repair Review
DefaultGroupName=Veyora Pro 2.0.3 Repair Review
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
Name: "{group}\Veyora Pro 2.0.3 Repair Review"; Filename: "{app}\Veyora-Pro.exe"
Name: "{autodesktop}\Veyora Pro 2.0.3 Repair Review"; Filename: "{app}\Veyora-Pro.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\Veyora-Pro.exe"; Description: "Launch Veyora Pro"; Flags: nowait postinstall skipifsilent
; No UninstallDelete entries: settings, history, models and downloaded files are outside {app}.
