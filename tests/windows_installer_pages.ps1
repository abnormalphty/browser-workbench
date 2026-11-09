# Clicks through the installer's pages the way a person would (run by .github/workflows/windows.yml):
# a program folder that already holds someone else's file, then a data folder that does too, each
# answered with the subfolder the installer offers. Saves a picture of every page and question, checks
# where things went, and that uninstalling leaves the other files alone. Needs no Docker.
param(
  [Parameter(Mandatory = $true)] [string] $Setup,
  [Parameter(Mandatory = $true)] [string] $Base,
  [Parameter(Mandatory = $true)] [string] $Out
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

// Window messages to another process's dialogs; C# 5, so Windows PowerShell can compile it too.
public static class Win
{
    public delegate bool EnumProc(IntPtr window, IntPtr data);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc callback, IntPtr data);
    [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr parent, EnumProc callback, IntPtr data);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr window, StringBuilder name, int size);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "SendMessageTimeoutW")]
    static extern IntPtr SendText(IntPtr window, uint message, IntPtr length, StringBuilder text, uint flags, uint timeout, out IntPtr result);
    [DllImport("user32.dll", CharSet = CharSet.Unicode, EntryPoint = "SendMessageTimeoutW")]
    static extern IntPtr SendString(IntPtr window, uint message, IntPtr unused, string text, uint flags, uint timeout, out IntPtr result);
    [DllImport("user32.dll", EntryPoint = "SendMessageTimeoutW")]
    static extern IntPtr SendValue(IntPtr window, uint message, IntPtr wParam, IntPtr lParam, uint flags, uint timeout, out IntPtr result);
    [DllImport("user32.dll")] static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr dialog, int id);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr window, out RECT rect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr window, IntPtr dc, uint flags);
    struct RECT { public int Left, Top, Right, Bottom; }
    const uint AbortIfHung = 2;

    public static string Class(IntPtr window)
    {
        var name = new StringBuilder(256);
        GetClassName(window, name, name.Capacity);
        return name.ToString();
    }

    // WM_GETTEXT: GetWindowText cannot read controls of another process.
    public static string Text(IntPtr window)
    {
        var text = new StringBuilder(4096);
        IntPtr result;
        SendText(window, 0x000D, (IntPtr)text.Capacity, text, AbortIfHung, 5000, out result);
        return text.ToString();
    }

    public static void SetText(IntPtr window, string text)
    {
        IntPtr result;
        SendString(window, 0x000C, IntPtr.Zero, text, AbortIfHung, 5000, out result);  // WM_SETTEXT
    }

    public static bool Checked(IntPtr window)
    {
        IntPtr result;
        SendValue(window, 0x00F0, IntPtr.Zero, IntPtr.Zero, AbortIfHung, 5000, out result);  // BM_GETCHECK
        return result == (IntPtr)1;
    }

    public static void Uncheck(IntPtr window)
    {
        IntPtr result;
        SendValue(window, 0x00F1, IntPtr.Zero, IntPtr.Zero, AbortIfHung, 5000, out result);  // BM_SETCHECK
    }

    // Posted, not sent: the button's handler may open a question and wait for an answer.
    public static void Press(IntPtr dialog, int button)
    {
        PostMessage(dialog, 0x0111, (IntPtr)button, GetDlgItem(dialog, button));  // WM_COMMAND, BN_CLICKED
    }

    public static List<IntPtr> Dialogs(int process)
    {
        var found = new List<IntPtr>();
        EnumWindows(delegate (IntPtr window, IntPtr data)
        {
            uint owner;
            GetWindowThreadProcessId(window, out owner);
            if (owner == process && IsWindowVisible(window) && Class(window) == "#32770") found.Add(window);
            return true;
        }, IntPtr.Zero);
        return found;
    }

    public static List<IntPtr> Children(IntPtr parent)
    {
        var found = new List<IntPtr>();
        EnumChildWindows(parent, delegate (IntPtr window, IntPtr data) { found.Add(window); return true; }, IntPtr.Zero);
        return found;
    }

    public static int[] Bounds(IntPtr window)
    {
        RECT rect;
        GetWindowRect(window, out rect);
        return new[] { rect.Left, rect.Top, rect.Right, rect.Bottom };
    }
}
'@

New-Item -ItemType Directory -Force $Out | Out-Null
$checks = New-Object System.Collections.Generic.List[object]
function Check([string] $name, [bool] $ok, [string] $detail = '') {
  $checks.Add([pscustomobject]@{ ok = $ok; name = $name; detail = $detail })
  Write-Host (($(if ($ok) { 'ok    ' } else { 'FAIL  ' })) + $name + $(if ($detail) { "  $detail" } else { '' }))
}
function Wait-For([scriptblock] $probe, [int] $seconds, [string] $what) {
  $end = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $end) {
    $value = & $probe
    $found = if ($value -is [IntPtr]) { $value -ne [IntPtr]::Zero } elseif ($value -is [bool]) { $value } else { $null -ne $value }
    if ($found) { return $value }
    Start-Sleep -Milliseconds 300
  }
  throw "timed out waiting for $what"
}
function Save-Picture([IntPtr] $window, [string] $name) {
  Start-Sleep -Milliseconds 600  # let the page finish painting
  $b = [Win]::Bounds($window)
  $bitmap = New-Object System.Drawing.Bitmap ([Math]::Max(1, $b[2] - $b[0])), ([Math]::Max(1, $b[3] - $b[1]))
  $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
  $dc = $graphics.GetHdc()
  [Win]::PrintWindow($window, $dc, 2) | Out-Null  # PW_RENDERFULLCONTENT
  $graphics.ReleaseHdc($dc)
  $graphics.Dispose()
  $bitmap.Save((Join-Path $Out "$name.png"), [System.Drawing.Imaging.ImageFormat]::Png)
  $bitmap.Dispose()
}
function All-Text([IntPtr] $window) { ([Win]::Children($window) | ForEach-Object { [Win]::Text($_) }) -join ' | ' }

$programParent = Join-Path $Base '已有文件的 程序位置'
$dataParent = Join-Path $Base '已有文件的 数据位置'
New-Item -ItemType Directory -Force $programParent, $dataParent | Out-Null
Set-Content -Encoding utf8 (Join-Path $programParent '别人的文件.txt') 'not the installer''s'
Set-Content -Encoding utf8 (Join-Path $dataParent '别人的文件.txt') 'not the installer''s'
$program = Join-Path $programParent 'Browser Workbench'
$dataRoot = Join-Path $dataParent 'BrowserWorkbench'

$process = Start-Process $Setup -PassThru
try {
  # The installer's own window has the page title (1037); questions are other dialogs of the process.
  $main = Wait-For { [Win]::Dialogs($process.Id) | Where-Object { [Win]::GetDlgItem($_, 1037) -ne [IntPtr]::Zero } | Select-Object -First 1 } 60 'the installer window'
  function Question { [Win]::Dialogs($process.Id) | Where-Object { $_ -ne $main } | Select-Object -First 1 }
  function Title { [Win]::Text([Win]::GetDlgItem($main, 1037)) }
  # The title changes before the page is built: give the old page time to go.
  function Page-Field { Start-Sleep -Milliseconds 1500; Wait-For { [Win]::Children($main) | Where-Object { [Win]::Class($_) -eq 'Edit' -and [Win]::IsWindowVisible($_) } | Select-Object -First 1 } 20 'the folder field' }

  Wait-For { (Title) -eq '选择安装位置' } 30 'the program folder page' | Out-Null
  $field = Page-Field
  $default = [Win]::Text($field)
  Check 'program page offers the usual folder' ($default -eq (Join-Path $env:LOCALAPPDATA 'Programs\Browser Workbench')) $default
  Save-Picture $main 'installer-1-program-folder'
  [Win]::SetText($field, $programParent)
  [Win]::Press($main, 1)
  $question = Wait-For { Question } 30 'the question about the program folder'
  $text = All-Text $question
  Save-Picture $question 'installer-2-program-subfolder'
  Check 'a folder holding other files gets a subfolder for the program' ($text.Contains($program)) $text
  [Win]::Press($question, 1)

  Wait-For { (Title) -eq '选择数据存放位置' } 30 'the data folder page' | Out-Null
  $field = Page-Field
  $default = [Win]::Text($field)
  Check 'data page offers the usual folder' ($default -eq (Join-Path $env:LOCALAPPDATA 'BrowserWorkbench')) $default
  $required = [Win]::Children($main) | Where-Object { [Win]::IsWindowVisible($_) -and [Win]::Text($_) -like '*所需空间*' }
  Check 'data page shows free space, not the program size' ($null -eq $required) (All-Text $main)
  Save-Picture $main 'installer-3-data-folder'
  [Win]::SetText($field, $dataParent)
  [Win]::Press($main, 1)
  $question = Wait-For { Question } 30 'the question about the data folder'
  $text = All-Text $question
  Save-Picture $question 'installer-4-data-subfolder'
  Check 'a folder holding other files gets a subfolder for the data' ($text.Contains($dataRoot)) $text
  [Win]::Press($question, 1)

  # Installing: the button turns into Finish when done.
  Wait-For { [Win]::Text([Win]::GetDlgItem($main, 1)) -like '完成*' } 900 'the installation' | Out-Null
  Save-Picture $main 'installer-5-finish'
  $run = [Win]::Children($main) | Where-Object { [Win]::Class($_) -eq 'Button' -and [Win]::Text($_) -eq '打开 Browser Workbench' } | Select-Object -First 1
  Check 'finish page offers to open the app' ($null -ne $run)
  if ($run) { [Win]::Uncheck($run) }  # the self-test opens it later, with its own settings
  [Win]::Press($main, 1)
  if (-not $process.WaitForExit(60000)) { throw 'the installer did not close' }
}
catch {
  Check 'installer pages' $false $_.Exception.Message
  foreach ($window in [Win]::Dialogs($process.Id)) { Save-Picture $window ('installer-error-' + $window.ToInt64()); Write-Host (All-Text $window) }
  if (-not $process.HasExited) { $process.Kill() }
}

Check 'program installed in the subfolder' (Test-Path (Join-Path $program 'BrowserWorkbench.exe')) $program
$location = (Get-ItemProperty 'HKCU:\Software\BrowserWorkbench' -ErrorAction SilentlyContinue).DataLocation
Check 'the data place is recorded for the app' ($location -eq $dataRoot) "$location"
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Browser Workbench.lnk'))
Check 'Start menu shortcut opens the chosen folder' ($shortcut.TargetPath -eq (Join-Path $program 'BrowserWorkbench.exe')) $shortcut.TargetPath

# The uninstaller copies itself elsewhere and returns at once: wait for the program to go.
if (Test-Path (Join-Path $program 'Uninstall.exe')) { Start-Process (Join-Path $program 'Uninstall.exe') -ArgumentList '/S' -Wait }
$gone = $false
for ($i = 0; $i -lt 60 -and -not $gone; $i++) { Start-Sleep 1; $gone = -not (Test-Path (Join-Path $program 'BrowserWorkbench.exe')) }
Check 'uninstalling removes the program' $gone
Check "uninstalling keeps other files in the program's parent folder" (Test-Path (Join-Path $programParent '别人的文件.txt'))
Check 'uninstalling keeps the files in the data folder' (Test-Path (Join-Path $dataParent '别人的文件.txt'))
$location = (Get-ItemProperty 'HKCU:\Software\BrowserWorkbench' -ErrorAction SilentlyContinue).DataLocation
Check 'uninstalling keeps the data place for a reinstallation' ($location -eq $dataRoot) "$location"

$checks | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Out 'installer-pages.json')
$failed = @($checks | Where-Object { -not $_.ok })
if ($failed.Count) { throw ('installer pages: ' + (($failed | ForEach-Object name) -join ', ')) }
Write-Host 'all installer page checks passed'
