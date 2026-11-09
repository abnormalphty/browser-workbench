; Windows installer for Browser Workbench, made with NSIS 3 (scripts/build_windows.sh, also on a Mac).
; Installs for the current user only: no administrator rights, nothing outside the user's own
; folders and registry. The user picks where the program goes and, on a first installation, where
; the data goes (HKCU\Software\BrowserWorkbench, DataLocation; the app reads it, windows/AppPaths.cs).
; The data itself is never touched; moving it later is done in the app.
; Silent: Setup.exe /S [/DATA=data folder] [/D=program folder] (/D last, without quotes).
Unicode true
ManifestDPIAware true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "FileFunc.nsh"
!include "WinMessages.nsh"

; Every one of these must be passed (true when any is missing).
!ifndef VERSION & SOURCE & ICON & WEBVIEW2_SETUP & OUTFILE
  !error "Pass /DVERSION, /DSOURCE (the staged app folder), /DICON, /DWEBVIEW2_SETUP and /DOUTFILE"
!endif

!define APP "Browser Workbench"
!define EXE "BrowserWorkbench.exe"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\BrowserWorkbench"
!define SETTINGS_KEY "Software\BrowserWorkbench"
!define DATA_FOLDER "BrowserWorkbench"
!define WEBVIEW2 "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

Name "${APP}"
Var DataRoot      ; where the data goes (its Data folder inside)
Var DataChosen    ; 1 when this installation decides it: the page was shown, or /DATA= given
Var RecordedRoot  ; the place recorded before this installation ("" if none)
Var OldInstDir    ; the program folder of an earlier installation
OutFile "${OUTFILE}"
InstallDir "$LOCALAPPDATA\Programs\${APP}"
InstallDirRegKey HKCU "${UNINSTALL_KEY}" "InstallLocation"
RequestExecutionLevel user
; The browser image is already compressed; LZMA only helps the rest.
SetCompressor /FINAL lzma
BrandingText "${APP} ${VERSION}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=0 "ProductName" "${APP}"
VIAddVersionKey /LANG=0 "ProductVersion" "${VERSION}"
VIAddVersionKey /LANG=0 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=0 "FileDescription" "${APP} 安装程序"
VIAddVersionKey /LANG=0 "CompanyName" "Browser Workbench contributors"
VIAddVersionKey /LANG=0 "LegalCopyright" "Browser Workbench contributors"

!define MUI_ICON "${ICON}"
!define MUI_UNICON "${ICON}"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\${EXE}"
!define MUI_FINISHPAGE_RUN_TEXT "打开 Browser Workbench"
!define MUI_UNCONFIRMPAGE_TEXT_TOP "将删除 Browser Workbench 程序。订阅、环境列表和传输的文件保存在“$DataRoot\Data”，各环境的登录状态保存在 Docker 里，都不会被删除。"

!define MUI_PAGE_HEADER_TEXT "选择安装位置"
!define MUI_PAGE_HEADER_SUBTEXT "程序和自带的浏览器组件装在哪里。"
!define MUI_DIRECTORYPAGE_TEXT_TOP "Browser Workbench 只为当前用户安装，不需要管理员权限。可以改到其他磁盘，例如 D:\${APP}；请选择你能写入的位置。"
!define MUI_DIRECTORYPAGE_TEXT_DESTINATION "安装位置"
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE InstallFolderLeave
!insertmacro MUI_PAGE_DIRECTORY

!define MUI_PAGE_HEADER_TEXT "选择数据存放位置"
!define MUI_PAGE_HEADER_SUBTEXT "订阅、环境和文件放在哪里。"
!define MUI_DIRECTORYPAGE_TEXT_TOP "这里存放订阅、环境列表和“电脑传入 / 环境下载”的文件。选了其他位置时，由工作台替你安装的 Docker Desktop 也会把浏览器组件和各环境的登录数据放在这里的 Docker 文件夹，会随使用增长到几 GB。以后可以在应用的“账号与资源 → 存储位置”里查看和移动。"
!define MUI_DIRECTORYPAGE_TEXT_DESTINATION "数据存放位置"
!define MUI_DIRECTORYPAGE_VARIABLE $DataRoot
; Next stays enabled when the drive has less room than the program needs: the data starts small.
!define MUI_DIRECTORYPAGE_VERIFYONLEAVE
!define MUI_PAGE_CUSTOMFUNCTION_PRE DataFolderPre
!define MUI_PAGE_CUSTOMFUNCTION_SHOW DataFolderShow
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE DataFolderLeave
!insertmacro MUI_PAGE_DIRECTORY

!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

; Files must not be replaced while the app runs (it holds this mutex).
!macro WaitUntilClosed
  check_running:
  System::Call 'kernel32::OpenMutexW(i 0x00100000, i 0, w "Local\BrowserWorkbench") p .r0'
  ${If} $0 <> 0
    System::Call 'kernel32::CloseHandle(p r0)'
    MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Browser Workbench 正在运行。请先关闭它的窗口，再点“重试”。" IDRETRY check_running
    Abort
  ${EndIf}
!macroend

; Program files the installer puts in a folder; the same list goes on upgrades and uninstalling.
; Never a recursive delete of the folder itself.
!macro RemoveProgram FOLDER
  RMDir /r "${FOLDER}\python"
  RMDir /r "${FOLDER}\backend"
  RMDir /r "${FOLDER}\runtime-image"
  RMDir /r "${FOLDER}\runtimes"
  Delete "${FOLDER}\*.exe"
  Delete "${FOLDER}\*.dll"
  Delete "${FOLDER}\*.config"
  Delete "${FOLDER}\*.ico"
  RMDir /r "${FOLDER}\licenses"
  RMDir "${FOLDER}"
!macroend

!macro ReadDataRoot
  ReadRegStr $RecordedRoot HKCU "${SETTINGS_KEY}" "DataLocation"
  StrCpy $DataRoot $RecordedRoot
  ${If} $DataRoot == ""
    StrCpy $DataRoot "$LOCALAPPDATA\${DATA_FOLDER}"
  ${EndIf}
!macroend

Function .onInit
  ${IfNot} ${RunningX64}
  ${OrIfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP "Browser Workbench 需要 64 位的 Windows 10 或 Windows 11。"
    Abort
  ${EndIf}
  SetRegView 64
  ReadRegStr $OldInstDir HKCU "${UNINSTALL_KEY}" "InstallLocation"
  !insertmacro ReadDataRoot
  StrCpy $DataChosen 0
  ; Like the page: only where no data is in use yet (data in use is moved in the app).
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 "/DATA=" $1
  ${IfNot} ${Errors}
  ${AndIf} $1 != ""
  ${AndIfNot} ${FileExists} "$DataRoot\Data\workbench.sqlite3"
    StrCpy $DataRoot $1
    StrCpy $DataChosen 1
  ${EndIf}
FunctionEnd

Function un.onInit
  SetRegView 64
  !insertmacro ReadDataRoot
FunctionEnd

; $R0 = folder. $R1 = 1 if it exists and holds anything.
Function HasContent
  StrCpy $R1 0
  ClearErrors
  FindFirst $0 $1 "$R0\*.*"
  ${DoWhile} $1 != ""
    ${If} $1 != "."
    ${AndIf} $1 != ".."
      StrCpy $R1 1
      ${ExitDo}
    ${EndIf}
    FindNext $0 $1
  ${Loop}
  FindClose $0
FunctionEnd

; $R0 = folder. Aborts the page if this user cannot write there without administrator rights.
; A folder made for the test goes again: cancelling the installer leaves nothing behind.
Function CheckWritable
  StrCpy $R2 0
  ${IfNot} ${FileExists} "$R0\*.*"
    StrCpy $R2 1
  ${EndIf}
  ClearErrors
  CreateDirectory "$R0"
  FileOpen $0 "$R0\.browser-workbench-write-test" w
  ${If} ${Errors}
    ${If} $R2 == 1
      RMDir "$R0"
    ${EndIf}
    MessageBox MB_ICONEXCLAMATION "不能写入这个位置（可能需要管理员权限）：$\r$\n$R0$\r$\n$\r$\n请选择其他文件夹，例如 D:\${APP}。"
    Abort
  ${EndIf}
  FileClose $0
  Delete "$R0\.browser-workbench-write-test"
  ${If} $R2 == 1
    RMDir "$R0"
  ${EndIf}
FunctionEnd

; $R2 = 1 if folder $R0 is folder $R1 or inside it (compared as Windows does, ignoring case).
Function IsInside
  StrCpy $R2 0
  StrLen $0 $R1
  StrCpy $1 $R0 $0
  ${If} $1 == $R1
    StrCpy $2 $R0 1 $0
    StrCpy $3 $R1 1 -1
    ${If} $2 == ""
    ${OrIf} $2 == "\"
    ${OrIf} $3 == "\"
      StrCpy $R2 1
    ${EndIf}
  ${EndIf}
FunctionEnd

Function InstallFolderLeave
  ; A folder of its own: upgrades and the uninstaller delete the program files they find in it.
  StrCpy $R0 $INSTDIR
  Call HasContent
  ${If} $R1 == 1
  ${AndIfNot} ${FileExists} "$INSTDIR\${EXE}"
    ${IfNot} ${Cmd} `MessageBox MB_OKCANCEL|MB_ICONINFORMATION "这个文件夹里已有其他文件。程序会装在其中新建的“${APP}”文件夹：$\r$\n$INSTDIR\${APP}" IDOK`
      Abort
    ${EndIf}
    StrCpy $INSTDIR "$INSTDIR\${APP}"
  ${EndIf}
  StrCpy $R0 $INSTDIR
  Call CheckWritable
FunctionEnd

Function DataFolderPre
  ; Data already in use stays where it is: the app moves it (it stops the environments first).
  ${If} ${FileExists} "$DataRoot\Data\workbench.sqlite3"
    Abort
  ${EndIf}
  StrCpy $DataChosen 1
FunctionEnd

Function DataFolderShow
  ; The space shown would be the program's; the free space there is what matters.
  FindWindow $0 "#32770" "" $HWNDPARENT
  GetDlgItem $1 $0 1023
  ShowWindow $1 ${SW_HIDE}
FunctionEnd

Function DataFolderLeave
  GetInstDirError $R3
  ; Not on another computer: the data needs a disk of this one (the app refuses the same, storage.py).
  StrCpy $1 $DataRoot 2
  StrCpy $2 $DataRoot 3
  System::Call 'kernel32::GetDriveTypeW(w r2) i .r3'
  ${If} $1 == "\\"
  ${OrIf} $3 == 4
    MessageBox MB_ICONEXCLAMATION "请选择这台电脑自己磁盘上的文件夹，不要选网络位置。"
    Abort
  ${EndIf}
  ; A whole drive (Browse gives D:\) gets a folder of its own.
  StrCpy $1 $DataRoot 1 1
  StrCpy $2 $DataRoot "" 2
  ${If} $1 == ":"
    ${If} $2 == ""
    ${OrIf} $2 == "\"
      StrCpy $DataRoot $DataRoot 2
      ${IfNot} ${FileExists} "$DataRoot\*.*"
        MessageBox MB_ICONEXCLAMATION "找不到 $DataRoot 盘。请选择这台电脑上的一个文件夹。"
        Abort
      ${EndIf}
      ${IfNot} ${Cmd} `MessageBox MB_OKCANCEL|MB_ICONINFORMATION "数据会放在 $DataRoot 盘上新建的“${DATA_FOLDER}”文件夹：$\r$\n$DataRoot\${DATA_FOLDER}" IDOK`
        Abort
      ${EndIf}
      StrCpy $DataRoot "$DataRoot\${DATA_FOLDER}"
      StrCpy $R3 0
    ${EndIf}
  ${EndIf}
  ${If} $R3 == 1
    MessageBox MB_ICONEXCLAMATION "这个位置不能用。请选择这台电脑上的一个文件夹，例如 D:\${DATA_FOLDER}。"
    Abort
  ${EndIf}
  ; Never inside the program folder, which upgrades and the uninstaller clear.
  StrCpy $R0 $DataRoot
  StrCpy $R1 $INSTDIR
  Call IsInside
  ${If} $R2 == 1
    MessageBox MB_ICONEXCLAMATION "数据不要放进程序文件夹：升级或卸载时它可能被删掉。请选择其他位置。"
    Abort
  ${EndIf}
  ; Workbench data there already (an earlier installation): used as it is. Any other folder that holds
  ; something gets a subfolder, except the app's own places (the same rule as moving in the app, storage.py).
  ${IfNot} ${FileExists} "$DataRoot\Data\workbench.sqlite3"
  ${AndIf} $DataRoot != "$LOCALAPPDATA\${DATA_FOLDER}"
  ${AndIf} $DataRoot != $RecordedRoot
    StrCpy $R0 $DataRoot
    Call HasContent
    ${If} $R1 == 1
      ${IfNot} ${Cmd} `MessageBox MB_OKCANCEL|MB_ICONINFORMATION "这个文件夹里已有其他文件。数据会放在其中新建的“${DATA_FOLDER}”文件夹：$\r$\n$DataRoot\${DATA_FOLDER}" IDOK`
        Abort
      ${EndIf}
      StrCpy $DataRoot "$DataRoot\${DATA_FOLDER}"
    ${EndIf}
  ${EndIf}
  StrCpy $R0 $DataRoot
  Call CheckWritable
FunctionEnd

; Windows 11 and most Windows 10 PCs already have the WebView2 runtime; install it otherwise.
Function EnsureWebView2
  ReadRegStr $0 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\${WEBVIEW2}" "pv"
  ${If} $0 == ""
  ${OrIf} $0 == "0.0.0.0"
    ReadRegStr $0 HKCU "Software\Microsoft\EdgeUpdate\Clients\${WEBVIEW2}" "pv"
  ${EndIf}
  ${If} $0 == ""
  ${OrIf} $0 == "0.0.0.0"
    DetailPrint "正在安装 Microsoft Edge WebView2 运行库（需要联网）…"
    InitPluginsDir
    File "/oname=$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe" "${WEBVIEW2_SETUP}"
    ExecWait '"$PLUGINSDIR\MicrosoftEdgeWebview2Setup.exe" /silent /install' $1
    DetailPrint "WebView2 安装程序已结束（$1）"
  ${EndIf}
FunctionEnd

Section "Install"
  !insertmacro WaitUntilClosed
  ; Installed somewhere else before: that copy goes, so only one remains (its data is elsewhere).
  ${If} $OldInstDir != ""
  ${AndIf} $OldInstDir != $INSTDIR
  ${AndIf} ${FileExists} "$OldInstDir\${EXE}"
    !insertmacro RemoveProgram "$OldInstDir"
  ${EndIf}
  SetOutPath "$INSTDIR"
  ; Program files of an earlier version go first; user data lives elsewhere.
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\backend"
  RMDir /r "$INSTDIR\runtime-image"
  RMDir /r "$INSTDIR\runtimes"
  File /r /x "runtime-image" "${SOURCE}/*"
  SetOutPath "$INSTDIR\runtime-image"
  SetCompress off
  File /nonfatal /r "${SOURCE}/runtime-image/*"
  SetCompress auto
  SetOutPath "$INSTDIR"
  WriteUninstaller "$INSTDIR\Uninstall.exe"

  CreateShortcut "$SMPROGRAMS\${APP}.lnk" "$INSTDIR\${EXE}"
  CreateShortcut "$DESKTOP\${APP}.lnk" "$INSTDIR\${EXE}"

  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayName" "${APP}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "Publisher" "Browser Workbench contributors"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\${EXE}"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL_KEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr HKCU "${UNINSTALL_KEY}" "QuietUninstallString" '"$INSTDIR\Uninstall.exe" /S'
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
  WriteRegDWORD HKCU "${UNINSTALL_KEY}" "EstimatedSize" $0
  ${If} $DataChosen == 1
    WriteRegStr HKCU "${SETTINGS_KEY}" "DataLocation" "$DataRoot"
  ${EndIf}

  Call EnsureWebView2
SectionEnd

Section "Uninstall"
  !insertmacro WaitUntilClosed
  Delete "$SMPROGRAMS\${APP}.lnk"
  Delete "$DESKTOP\${APP}.lnk"
  ; Only what the installer put there. The data place stays recorded, so a reinstallation finds the data.
  !insertmacro RemoveProgram "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
SectionEnd
