; Prism's Windows installer (Inno Setup 6). Built by packaging/build.py after
; the .zip, from the same dist\Prism folder; never run by hand without it:
;
;   ISCC.exe /DAppVersion=1.8.9 /DFlavour=complete /DAppName=Prism
;            /DAppDirName=Prism /DAppExeName=Prism.exe /DAppPublisher=Alphakore
;            /DAppURL=https://alphakore.org /DBundleDir=...\dist\Prism
;            /DOutputDir=...\dist /DOutputBase=Prism-1.8.9-windows-x64-setup
;            packaging\windows\prism.iss
;
; Every value comes from app_meta.py and flavour.IDENTITY through build.py;
; nothing here says which version it is (tests/test_windows_installer.py).
;
; PER USER, ON PURPOSE. The in-app updater (updater.py, apply_update.py)
; renames the whole program folder aside and moves the new version into its
; place, and stages beside it. That needs a folder the person can write
; without asking for admin rights, so the install goes to
; %LOCALAPPDATA%\Programs\<name> and Setup never asks for elevation.
;
; THE UNINSTALLER LIVES OUTSIDE THE PROGRAM FOLDER. An in-app update replaces
; the program folder with exactly the files in the update manifest; an
; unins000.exe inside it would be gone after the first update, leaving an
; "Installed apps" entry that cannot uninstall. It would also make Prism's own
; Settings > Uninstall refuse to remove the folder (uninstall.py accepts only
; Prism's own entries). So the program folder holds exactly what the .zip
; holds, and the uninstaller sits in a folder beside it.
;
; User data (%USERPROFILE%\.prism, see paths.user_dir) is never named here:
; uninstalling removes the program, never what the person made or saved.

#ifndef AppVersion
  #error AppVersion is not set: build this with packaging/build.py
#endif
#ifndef Flavour
  #error Flavour is not set: build this with packaging/build.py
#endif

; One AppId per flavour, never changed and never reused: it is the key
; Windows files the install under, so the same flavour installed again
; upgrades in place, and two flavours install side by side.
#if Flavour == "complete"
  #define AppGuid "{{A9F3B880-46D3-441D-B7E4-E95A8DEDC8C6}"
#elif Flavour == "studio"
  #define AppGuid "{{164D1A89-98DC-4F3C-9897-28AF43848731}"
#elif Flavour == "sales"
  #define AppGuid "{{441C6F76-B957-4AA6-B807-D8A9D63E3F8D}"
#elif Flavour == "engineering"
  #define AppGuid "{{05646D25-6DF8-4ECA-8DBA-8F69EA686059}"
#else
  #error Unknown Flavour
#endif

[Setup]
AppId={#AppGuid}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppDirName}
; No folder choice: the uninstaller removes the program's own files from this
; folder, so it must never be a folder that also holds the person's files.
DisableDirPage=yes
DisableProgramGroupPage=yes
UninstallFilesDir={localappdata}\Programs\{#AppDirName}-uninstall
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile=..\icons\prism.ico
WizardStyle=modern
OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
; LZMA2 at its strongest, one solid stream across all ~3,300 files. Two block
; threads: each uses two cores, which is the whole 4-core runner. The
; compressor runs as its own 64-bit process so ultra64 has the memory it needs.
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=2

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; Installing over an older version: start from a clean program tree, exactly
; as an in-app update does, so no file the new version dropped stays behind.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[UninstallDelete]
; What Setup did not put there itself: files an in-app update added, and what
; the updater leaves beside the program (its previous version, a rolled-back
; one, its marker and its staging folder). Prism's own entries only; the
; folder itself goes only once it is empty.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\.prism_update_pending"
Type: dirifempty; Name: "{app}"
Type: filesandordirs; Name: "{app}.old"
Type: filesandordirs; Name: "{app}.failed-update"
Type: dirifempty; Name: "{localappdata}\Programs\.prism-update-staging"
