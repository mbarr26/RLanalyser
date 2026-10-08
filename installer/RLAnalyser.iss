; Inno Setup script for RL Analyser. Build with build.ps1 (it passes /DAppVersion=...).
; A per-user install (no admin rights needed). Settings, the replay cache and AI models live in
; %LOCALAPPDATA%\RLAnalyser, outside the install folder, so updates and reinstalls keep them.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

; The app's identity for upgrades (keep it the same for every release). Tests override it with
; /DAppIdGuid=... so a test install can never replace or unregister a real one.
#ifndef AppIdGuid
  #define AppIdGuid "{{6E1B6A52-3F0C-4C9B-9B5E-7A3D2C1F8E40}"
#endif

[Setup]
AppId={#AppIdGuid}
AppName=RL Analyser
AppVersion={#AppVersion}
AppPublisher=RL Analyser
DefaultDirName={localappdata}\Programs\RL Analyser
DefaultGroupName=RL Analyser
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=RLAnalyser-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\RL Analyser.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\RL Analyser\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\RL Analyser"; Filename: "{app}\RL Analyser.exe"
Name: "{autodesktop}\RL Analyser"; Filename: "{app}\RL Analyser.exe"; Tasks: desktopicon

[Run]
; Normal install: a "Launch RL Analyser" checkbox on the last page
Filename: "{app}\RL Analyser.exe"; Description: "Launch RL Analyser"; Flags: nowait postinstall skipifsilent
; In-app update (the app starts Setup with /SILENT): relaunch the new version automatically
Filename: "{app}\RL Analyser.exe"; Flags: nowait; Check: WizardSilent
