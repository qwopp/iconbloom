; Inno Setup script for Iconbloom: per-user install, no admin rights needed.
;
;   iscc /DAppVersion=0.1.0 installer\iconbloom.iss
;
; Expects the PyInstaller one-folder build in dist\Iconbloom.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; Never change it: Windows knows the installed app by it, and updates find it through it.
#define AppGuid "6F1C6B0E-2F7A-4C59-9B8E-6A3E2B1F9C41"

[Setup]
; Close a running Iconbloom before replacing its files (the updater has usually closed it).
CloseApplications=yes
AppId={{{#AppGuid}}
AppName=Iconbloom
AppVersion={#AppVersion}
AppPublisher=Iconbloom contributors
AppPublisherURL=https://github.com/qwopp/iconbloom
AppSupportURL=https://github.com/qwopp/iconbloom/issues
DefaultDirName={localappdata}\Programs\Iconbloom
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Iconbloom-Setup-{#AppVersion}
SetupIconFile=iconbloom.ico
UninstallDisplayIcon={app}\Iconbloom.exe
UninstallDisplayName=Iconbloom
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE

; Shortcuts are made on the first install only. Updates leave them alone, so one you
; moved, deleted or restyled stays the way you left it.
[Tasks]
Name: "desktopicon"; Description: "Put an Iconbloom shortcut on my desktop"; Flags: unchecked; Check: IsFirstInstall

[Files]
Source: "..\dist\Iconbloom\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\Iconbloom"; Filename: "{app}\Iconbloom.exe"; Check: IsFirstInstall
Name: "{userdesktop}\Iconbloom"; Filename: "{app}\Iconbloom.exe"; Tasks: desktopicon; Check: IsFirstInstall

[Run]
Filename: "{app}\Iconbloom.exe"; Description: "Open Iconbloom"; Flags: nowait postinstall skipifsilent
; In-app updates install silently; reopen Iconbloom when they finish.
Filename: "{app}\Iconbloom.exe"; Flags: nowait; Check: WizardSilent

[Code]
var
  AlreadyInstalled: Boolean;

// Looked up before anything is installed: by the time [Icons] runs, this install's own
// uninstall entry may already exist.
function InitializeSetup(): Boolean;
begin
  AlreadyInstalled := RegKeyExists(HKA,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppGuid}}_is1');
  Result := True;
end;

function IsFirstInstall(): Boolean;
begin
  Result := not AlreadyInstalled;
end;

// Shortcuts themed by Iconbloom point at icon files in its data folder. Offer
// to put every original icon back first, so nothing is left pointing at
// files that are about to go away.
function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
  DataDir: String;
begin
  Result := True;
  DataDir := ExpandConstant('{localappdata}\Iconbloom');
  if not DirExists(DataDir) then
    exit;
  if UninstallSilent() then
    exit;
  if MsgBox('Put all your original icons back before uninstalling?' + #13#10 + #13#10 +
            'Choose No to keep your themed icons. Their icon files stay in ' + DataDir + '.',
            mbConfirmation, MB_YESNO) = IDYES then
  begin
    if Exec(ExpandConstant('{app}\Iconbloom.exe'), '--revert-all', '', SW_HIDE,
            ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
      DelTree(DataDir, True, True, True)
    else
      MsgBox('Some icons could not be restored automatically. Your backups are kept in ' +
             DataDir + '.', mbError, MB_OK);
  end;
end;
