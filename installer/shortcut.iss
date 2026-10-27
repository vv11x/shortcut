#define AppName "shortcut"
#define AppVersion "1.1.41"
#define AppExeName "shortcut.exe"
#ifndef DistributionDirectory
  #error Use installer/build.ps1 to provide DistributionDirectory.
#endif

[Setup]
AppId={{38C12D13-AB04-4E78-9FD7-6177838AB0AB}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=vv11x
AppPublisherURL=https://github.com/vv11x/shortcut
AppSupportURL=https://github.com/vv11x/shortcut/issues
AppUpdatesURL=https://github.com/vv11x/shortcut/releases/latest
DefaultDirName={localappdata}\Programs\shortcut
DefaultGroupName=shortcut
DisableProgramGroupPage=yes
DisableDirPage=yes
UsePreviousAppDir=yes
PrivilegesRequired=lowest
SetupArchitecture=x64
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
OutputDir=F:\shortcut-output\dist
OutputBaseFilename=shortcut-v{#AppVersion}
SetupIconFile=..\assets\branding\shortcut.ico
UninstallDisplayName=shortcut {#AppVersion}
UninstallDisplayIcon={app}\shortcut.exe
LicenseFile=..\LICENSE
WizardStyle=modern
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
VersionInfoVersion=1.1.41.0
VersionInfoCompany=vv11x
VersionInfoDescription=shortcut Windows desktop organizer
VersionInfoCopyright=Copyright (C) 2026 vv11x

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "{#DistributionDirectory}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\shortcut"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{autoprograms}\shortcut\恢复桌面图标"; Filename: "{app}\{#AppExeName}"; Parameters: "--restore-desktop"; WorkingDir: "{app}"
Name: "{autodesktop}\shortcut"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 shortcut"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent
