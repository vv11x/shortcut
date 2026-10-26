#define AppName "shortcut"
#define AppVersion "1.0.0"

[Setup]
AppId={{A6A5D91C-3C5D-4CB2-89C3-A9807B6A1699}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=vv11x
DefaultDirName={localappdata}\Programs\shortcut
DefaultGroupName=shortcut
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\release
OutputBaseFilename=shortcut-{#AppVersion}
SetupIconFile=..\assets\branding\shortcut.ico
UninstallDisplayIcon={app}\shortcut.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "其他快捷方式："; Flags: unchecked

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
Source: "..\dist\shortcut\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "restore-desktop.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*.txt"; DestDir: "{app}\licenses"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\shortcut"; Filename: "{app}\shortcut.exe"
Name: "{autoprograms}\shortcut\恢复桌面图标"; Filename: "{app}\restore-desktop.bat"; WorkingDir: "{app}"
Name: "{autodesktop}\shortcut"; Filename: "{app}\shortcut.exe"; Tasks: desktopicon

