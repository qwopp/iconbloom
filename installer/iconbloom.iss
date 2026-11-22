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
; "force", because the copy that keeps icons fixed has no window to close politely; it is
; asked to stop first (StopKeepingIcons), so this is only the backup.
CloseApplications=force
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
; With "Fix reset icons automatically" on, keep fixing them: setup stopped that copy.
Filename: "{app}\Iconbloom.exe"; Parameters: "--fix-icons"; Flags: nowait; Check: KeepsIcons

[Code]
const
  EVENT_MODIFY_STATE = $0002;
  SYNCHRONIZE = $00100000;
  RUN_KEY = 'Software\Microsoft\Windows\CurrentVersion\Run';

var
  AlreadyInstalled: Boolean;

function WinOpenEvent(dwDesiredAccess: DWORD; bInheritHandle: BOOL; lpName: String): THandle;
  external 'OpenEventW@kernel32.dll stdcall';
function WinSetEvent(hEvent: THandle): BOOL;
  external 'SetEvent@kernel32.dll stdcall';
function WinCloseHandle(hObject: THandle): BOOL;
  external 'CloseHandle@kernel32.dll stdcall';
function WinOpenMutex(dwDesiredAccess: DWORD; bInheritHandle: BOOL; lpName: String): THandle;
  external 'OpenMutexW@kernel32.dll stdcall';
function WinWaitForSingleObject(hHandle: THandle; dwMilliseconds: DWORD): DWORD;
  external 'WaitForSingleObject@kernel32.dll stdcall';

// The copy that keeps icons fixed runs from {app}, so ask it to exit before its files
// are replaced or removed, and wait until it has (platform_win/watch.py names both: it
// owns the mutex until it exits).
procedure StopKeepingIcons();
var
  Event, Keeper: THandle;
begin
  Keeper := WinOpenMutex(SYNCHRONIZE, False, 'Local\Iconbloom.KeepingIcons');
  Event := WinOpenEvent(EVENT_MODIFY_STATE, False, 'Local\Iconbloom.StopKeepingIcons');
  if Event <> 0 then
  begin
    WinSetEvent(Event);
    WinCloseHandle(Event);
  end;
  if Keeper <> 0 then
  begin
    WinWaitForSingleObject(Keeper, 5000);
    WinCloseHandle(Keeper);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopKeepingIcons();
  Result := '';
end;

function KeepsIcons(): Boolean;
begin
  Result := RegValueExists(HKCU, RUN_KEY, 'Iconbloom');
end;

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
  StopKeepingIcons();
  // A copy still starting up when asked (or a window left open) would keep its files in
  // use. Setup has CloseApplications for that; the uninstaller closes them itself.
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM Iconbloom.exe', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  DataDir := ExpandConstant('{localappdata}\Iconbloom');
  if not DirExists(DataDir) then
    exit;
  if UninstallSilent() then
    exit;
  if MsgBox('Put all your original icons and taskbar settings back before uninstalling?' + #13#10 + #13#10 +
            'Choose No to keep your themed icons. Their icon files stay in ' + DataDir + '.',
            mbConfirmation, MB_YESNO) = IDYES then
  begin
    if Exec(ExpandConstant('{app}\Iconbloom.exe'), '--revert-all', '', SW_HIDE,
            ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then
      DelTree(DataDir, True, True, True)
    else
      MsgBox('Some icons could not be put back, for example because the permission prompt was ' +
             'declined. Your backups are kept in ' + DataDir + '.' + #13#10 + #13#10 +
             'To finish, reinstall Iconbloom, click Revert all, then uninstall again.',
             mbError, MB_OK);
  end;
end;

// "Fix reset icons automatically" would otherwise start an Iconbloom.exe that's gone.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKCU, RUN_KEY, 'Iconbloom');
end;
