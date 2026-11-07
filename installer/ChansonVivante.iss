#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppName "ChansonVivante"
#define AppExeName "ChansonVivante.exe"

[Setup]
AppId={{A0E3A27C-7F8A-4B64-A7E6-8D5C7E94A1F2}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=ChansonVivante
DefaultDirName={localappdata}\Programs\ChansonVivante
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release\setup
OutputBaseFilename=ChansonVivante-Setup-{#AppVersion}
SetupIconFile=..\logo.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64
ArchitecturesAllowed=x64

[Languages]
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Crea un collegamento sul Desktop"; GroupDescription: "Collegamenti aggiuntivi:"; Flags: unchecked

[Files]
Source: "..\dist\ChansonVivante\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Avvia {#AppName}"; Flags: postinstall nowait skipifsilent
