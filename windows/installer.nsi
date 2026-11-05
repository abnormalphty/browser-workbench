; Windows installer for Browser Workbench, made with NSIS 3 (scripts/build_windows.sh, also on a Mac).
; Installs for the current user only: no administrator rights, nothing outside the user's own
; folders and registry. The data folder (%LOCALAPPDATA%\BrowserWorkbench) is never touched.
Unicode true
ManifestDPIAware true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"
!include "FileFunc.nsh"

; Every one of these must be passed (true when any is missing).
!ifndef VERSION & SOURCE & ICON & WEBVIEW2_SETUP & OUTFILE
  !error "Pass /DVERSION, /DSOURCE (the staged app folder), /DICON, /DWEBVIEW2_SETUP and /DOUTFILE"
!endif

!define APP "Browser Workbench"
!define EXE "BrowserWorkbench.exe"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\BrowserWorkbench"
!define WEBVIEW2 "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"

Name "${APP}"
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
!define MUI_UNCONFIRMPAGE_TEXT_TOP "将删除 Browser Workbench 程序。浏览器环境、登录状态和订阅保存在“%LOCALAPPDATA%\BrowserWorkbench”和 Docker 里，不会被删除。"
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

Function .onInit
  ${IfNot} ${RunningX64}
  ${OrIfNot} ${AtLeastWin10}
    MessageBox MB_ICONSTOP "Browser Workbench 需要 64 位的 Windows 10 或 Windows 11。"
    Abort
  ${EndIf}
  SetRegView 64
FunctionEnd

Function un.onInit
  SetRegView 64
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

  Call EnsureWebView2
SectionEnd

Section "Uninstall"
  !insertmacro WaitUntilClosed
  Delete "$SMPROGRAMS\${APP}.lnk"
  Delete "$DESKTOP\${APP}.lnk"
  ; Only what the installer put there: never a recursive delete of the folder itself.
  RMDir /r "$INSTDIR\python"
  RMDir /r "$INSTDIR\backend"
  RMDir /r "$INSTDIR\runtime-image"
  RMDir /r "$INSTDIR\runtimes"
  Delete "$INSTDIR\*.exe"
  Delete "$INSTDIR\*.dll"
  Delete "$INSTDIR\*.config"
  Delete "$INSTDIR\*.ico"
  RMDir /r "$INSTDIR\licenses"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTALL_KEY}"
SectionEnd
