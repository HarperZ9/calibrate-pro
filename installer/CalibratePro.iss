#ifndef AppVersion
  #error AppVersion must be supplied with /DAppVersion
#endif
#ifndef StagedDir
  #error StagedDir must be supplied with /DStagedDir
#endif
#ifndef ReleaseDir
  #error ReleaseDir must be supplied with /DReleaseDir
#endif

#define AppName "Calibrate Pro"
#define AppPublisher "Zain Dana Harper"
#define AppExeName "CalibratePro.exe"

[Setup]
AppId={{A8A22043-566C-4DF6-9AC8-7C8F5A8B4157}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\Calibrate Pro
DefaultGroupName=Calibrate Pro
OutputDir={#ReleaseDir}
OutputBaseFilename=CalibratePro-{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#AppExeName}
WizardStyle=modern

[Files]
Source: "{#StagedDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Calibrate Pro"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\Calibrate Pro"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch Calibrate Pro"; Flags: nowait postinstall skipifsilent
