using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;
using Microsoft.Win32;

namespace BrowserWorkbench
{
    sealed class BridgeError : Exception
    {
        public BridgeError(string message) : base(message) { }
    }

    /// <summary>The single app window. Shows the local workbench page, or a status page while the
    /// backend starts or after it stops. The page reaches native features through the bridge.</summary>
    sealed class MainForm : Form
    {
        const int MenuDataFolder = 0x1010, MenuLogs = 0x1020;  // WM_SYSCOMMAND keeps the low 4 bits

        readonly WebView2 webView = new WebView2 { Dock = DockStyle.Fill };
        readonly Backend backend;
        readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        /// <summary>Only files this window saved may be revealed on request from the page.</summary>
        readonly HashSet<string> revealable = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        int port;
        bool closingApproved, quitting, uiTestStarted;

        public MainForm()
        {
            Text = "Browser Workbench";
            Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
            StartPosition = FormStartPosition.Manual;
            BackColor = PageBackground;
            webView.DefaultBackgroundColor = PageBackground;
            Controls.Add(webView);
            backend = new Backend();
            backend.StateChanged += BackendChanged;
            Load += async (_, __) => await InitializeWebView();
            SystemEvents.UserPreferenceChanged += (_, __) => ApplyTitleBarTheme();
        }

        static bool DarkMode()
        {
            using (var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"))
                return key?.GetValue("AppsUseLightTheme") is int light && light == 0;
        }

        /// <summary>Same as --bg in style.css, so nothing flashes white before the page paints.</summary>
        static Color PageBackground => DarkMode() ? Color.FromArgb(0x19, 0x1c, 0x1b) : Color.FromArgb(0xf5, 0xf6, 0xf5);

        // MARK: Window

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            var menu = NativeMethods.GetSystemMenu(Handle, false);
            NativeMethods.AppendMenu(menu, NativeMethods.MenuSeparator, UIntPtr.Zero, null);
            NativeMethods.AppendMenu(menu, 0, (UIntPtr)MenuDataFolder, "打开数据文件夹");
            NativeMethods.AppendMenu(menu, 0, (UIntPtr)MenuLogs, "打开日志文件夹");
            ApplyTitleBarTheme();
            RestoreWindow();
        }

        protected override void WndProc(ref Message message)
        {
            if (message.Msg == NativeMethods.SystemCommand)
            {
                var command = message.WParam.ToInt64() & 0xFFF0;
                if (command == MenuDataFolder) { OpenFolder(AppPaths.DataDirectory); return; }
                if (command == MenuLogs) { OpenFolder(AppPaths.LogDirectory); return; }
            }
            base.WndProc(ref message);
        }

        void ApplyTitleBarTheme()
        {
            if (!IsHandleCreated) return;
            var dark = DarkMode() ? 1 : 0;
            NativeMethods.DwmSetWindowAttribute(Handle, 20, ref dark, sizeof(int));
        }

        int Scaled(int value) => value * DeviceDpi / 96;

        void RestoreWindow()
        {
            MinimumSize = new Size(Scaled(960), Scaled(620));
            try
            {
                var saved = File.ReadAllText(AppPaths.WindowState).Split(',').Select(int.Parse).ToArray();
                var bounds = new Rectangle(saved[0], saved[1], saved[2], saved[3]);
                if (Screen.AllScreens.Any(screen => screen.WorkingArea.IntersectsWith(bounds)))
                {
                    Bounds = bounds;
                    if (saved.Length > 4 && saved[4] == 1) WindowState = FormWindowState.Maximized;
                    return;
                }
            }
            catch (Exception) { }
            var area = Screen.FromPoint(Cursor.Position).WorkingArea;
            var size = new Size(Math.Min(Scaled(1280), area.Width), Math.Min(Scaled(820), area.Height));
            Bounds = new Rectangle(area.Left + (area.Width - size.Width) / 2, area.Top + (area.Height - size.Height) / 2, size.Width, size.Height);
        }

        void SaveWindow()
        {
            try
            {
                var bounds = WindowState == FormWindowState.Normal ? Bounds : RestoreBounds;
                Directory.CreateDirectory(Path.GetDirectoryName(AppPaths.WindowState));
                File.WriteAllText(AppPaths.WindowState, $"{bounds.X},{bounds.Y},{bounds.Width},{bounds.Height},{(WindowState == FormWindowState.Maximized ? 1 : 0)}");
            }
            catch (Exception) { }
        }

        public void BringForward()
        {
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            Show();
            Activate();
            BringToFront();
        }

        static void OpenFolder(string path)
        {
            try
            {
                Directory.CreateDirectory(path);
                Process.Start(new ProcessStartInfo("explorer.exe", AppPaths.JoinArguments(new[] { path })) { UseShellExecute = true });
            }
            catch (Exception) { }
        }

        static void OpenExternal(string url) =>
            Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });

        // MARK: Quitting

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            if (closingApproved || e.CloseReason == CloseReason.WindowsShutDown || e.CloseReason == CloseReason.TaskManagerClosing)
            {
                // Logging off: the backend goes, environments stop with Docker Desktop itself.
                quitting = true;
                if (!closingApproved) SaveWindow();
                backend.Stop();
                base.OnFormClosing(e);
                return;
            }
            e.Cancel = true;
            if (!quitting) _ = QuitAsync(null);
            base.OnFormClosing(e);
        }

        /// <summary>Closing the window quits; while environments run the user decides whether they stop.</summary>
        async Task QuitAsync(bool? stopEnvironments)
        {
            quitting = true;
            var summary = backend.State == BackendState.Ready ? await backend.SummaryAsync() : null;
            if (summary != null && summary.Active > 0)
            {
                var choice = stopEnvironments;
                if (choice == null)
                {
                    using (var dialog = new QuitDialog(summary.Active))
                    {
                        dialog.ShowDialog(this);
                        choice = dialog.StopEnvironments;
                    }
                }
                if (choice == null)
                {
                    quitting = false;
                    return;
                }
                if (choice == true)
                {
                    ShowStatus("正在停止浏览器环境…", "登录状态会保留，完成后自动退出。");
                    await backend.StopAllEnvironmentsAsync();
                }
            }
            SaveWindow();
            backend.Stop(() =>
            {
                closingApproved = true;
                Close();
            });
        }

        // MARK: Pages

        async Task InitializeWebView()
        {
            try
            {
                var environment = await CoreWebView2Environment.CreateAsync(null, AppPaths.WebViewDirectory);
                await webView.EnsureCoreWebView2Async(environment);
            }
            catch (WebView2RuntimeNotFoundException)
            {
                MessageBox.Show(this, "Browser Workbench 需要 Microsoft Edge WebView2 运行库。点“确定”后会打开微软的下载页面，安装后重新打开 Browser Workbench。",
                    "缺少 WebView2", MessageBoxButtons.OK, MessageBoxIcon.Information);
                OpenExternal("https://go.microsoft.com/fwlink/p/?LinkId=2124703");
                closingApproved = true;
                Close();
                return;
            }
            catch (Exception error)
            {
                Program.Report(error);
                closingApproved = true;
                Close();
                return;
            }
            var core = webView.CoreWebView2;
            core.Settings.AreDevToolsEnabled = Environment.GetEnvironmentVariable("BROWSER_WORKBENCH_DEVTOOLS") == "1";
            core.Settings.IsStatusBarEnabled = false;
            core.Settings.IsPasswordAutosaveEnabled = false;
            core.Settings.IsGeneralAutofillEnabled = false;
            await core.AddScriptToExecuteOnDocumentCreatedAsync(BridgeScript());
            core.WebMessageReceived += WebMessageReceived;
            core.NavigationStarting += NavigationStarting;
            core.NavigationCompleted += (_, e) => { if (e.IsSuccess && IsWorkbench(core.Source)) RunUITestIfRequested(); };
            core.NewWindowRequested += NewWindowRequested;
            core.DownloadStarting += DownloadStarting;
            core.PermissionRequested += PermissionRequested;
            core.ProcessFailed += (_, e) => { if (port != 0 && e.ProcessFailedKind == CoreWebView2ProcessFailedKind.RenderProcessExited) LoadWorkbench(port); };
            ShowStatus("正在启动 Browser Workbench…", "第一次启动可能需要几秒。");
            backend.Start();
        }

        void BackendChanged()
        {
            if (webView.CoreWebView2 == null) return;
            switch (backend.State)
            {
                case BackendState.Starting: ShowStatus("正在启动 Browser Workbench…", "第一次启动可能需要几秒。"); break;
                case BackendState.Ready: LoadWorkbench(backend.Port); break;
                case BackendState.Failed: ShowStatus("Browser Workbench 没有启动", backend.Failure, isError: true); break;
                case BackendState.Stopped: if (!quitting) ShowStatus("后台服务已停止", "浏览器环境不受影响，可以点重试重新连接。", isError: true); break;
            }
        }

        void LoadWorkbench(int newPort)
        {
            port = newPort;
            webView.CoreWebView2.Navigate($"http://127.0.0.1:{port}/");
        }

        void ShowStatus(string message, string detail, bool isError = false)
        {
            port = 0;
            webView.CoreWebView2?.NavigateToString(StatusPage.Html(message, detail, isError));
        }

        bool IsWorkbench(string uri) => port != 0 && uri != null && uri.StartsWith($"http://127.0.0.1:{port}/", StringComparison.Ordinal);

        /// <summary>Runs page JavaScript only while our own workbench page is showing.</summary>
        void NotifyPage(string name, Dictionary<string, object> detail)
        {
            if (port == 0) return;
            _ = webView.CoreWebView2.ExecuteScriptAsync($"window.dispatchEvent(new CustomEvent({json.Serialize(name)},{{detail:{json.Serialize(detail)}}}))");
        }

        // MARK: Navigation

        void NavigationStarting(object sender, CoreWebView2NavigationStartingEventArgs e)
        {
            var uri = e.Uri ?? "";
            if (uri.StartsWith("workbench-native://", StringComparison.OrdinalIgnoreCase))
            {
                e.Cancel = true;
                if (uri.StartsWith("workbench-native://retry", StringComparison.OrdinalIgnoreCase)) backend.Restart();
                else if (uri.StartsWith("workbench-native://logs", StringComparison.OrdinalIgnoreCase)) OpenFolder(AppPaths.LogDirectory);
                return;
            }
            if (IsWorkbench(uri) || uri.StartsWith("data:", StringComparison.Ordinal) || uri.StartsWith("about:", StringComparison.Ordinal)) return;
            // Web links open in the user's browser; dropped files (file://) never replace the page.
            e.Cancel = true;
            if (e.IsUserInitiated && (uri.StartsWith("https://", StringComparison.OrdinalIgnoreCase) || uri.StartsWith("http://", StringComparison.OrdinalIgnoreCase)))
                OpenExternal(uri);
        }

        void NewWindowRequested(object sender, CoreWebView2NewWindowRequestedEventArgs e)
        {
            e.Handled = true;  // never a second window
            var uri = e.Uri ?? "";
            if ((uri.StartsWith("https://", StringComparison.OrdinalIgnoreCase) || uri.StartsWith("http://", StringComparison.OrdinalIgnoreCase)) && !IsWorkbench(uri))
                OpenExternal(uri);
        }

        void PermissionRequested(object sender, CoreWebView2PermissionRequestedEventArgs e)
        {
            // The page's clipboard reads go through the bridge; nothing here needs camera, location and the like.
            e.State = IsWorkbench(e.Uri) && e.PermissionKind == CoreWebView2PermissionKind.ClipboardRead
                ? CoreWebView2PermissionState.Allow : CoreWebView2PermissionState.Deny;
        }

        // MARK: Downloads ("下载到电脑")

        void DownloadStarting(object sender, CoreWebView2DownloadStartingEventArgs e)
        {
            if (!IsWorkbench(e.DownloadOperation.Uri))
            {
                e.Cancel = true;
                return;
            }
            var folder = AppPaths.DownloadsDirectory;
            Directory.CreateDirectory(folder);
            var target = UniquePath(folder, SafeFileName(Path.GetFileName(e.ResultFilePath)));
            e.ResultFilePath = target;
            e.Handled = true;  // no download flyout: the page shows its own message
            var operation = e.DownloadOperation;
            operation.StateChanged += (_, __) =>
            {
                if (operation.State == CoreWebView2DownloadState.Completed)
                {
                    revealable.Add(target);
                    NotifyPage("workbench-native-download", new Dictionary<string, object> { ["ok"] = true, ["name"] = Path.GetFileName(target), ["path"] = target });
                }
                else if (operation.State == CoreWebView2DownloadState.Interrupted)
                {
                    try { File.Delete(target); } catch (Exception) { }
                    NotifyPage("workbench-native-download", new Dictionary<string, object> { ["ok"] = false, ["name"] = Path.GetFileName(target) });
                }
            };
        }

        static string SafeFileName(string name)
        {
            var cleaned = new string((name ?? "").Select(c => Path.GetInvalidFileNameChars().Contains(c) ? '_' : c).ToArray()).Trim().TrimStart('.');
            return cleaned.Length == 0 ? "下载文件" : cleaned;
        }

        static string UniquePath(string folder, string name)
        {
            var stem = Path.GetFileNameWithoutExtension(name);
            var extension = Path.GetExtension(name);
            var candidate = Path.Combine(folder, name);
            for (var index = 2; File.Exists(candidate); index++)
                candidate = Path.Combine(folder, $"{stem} ({index}){extension}");
            return candidate;
        }

        // MARK: Native bridge: window.workbenchBridge.call(type, data) → Promise

        string BridgeScript()
        {
            var native = json.Serialize(new Dictionary<string, object> { ["version"] = AppPaths.Version, ["platform"] = "windows" });
            return "(() => {\n" +
                "  if (window !== window.top || !window.chrome || !window.chrome.webview) return;\n" +
                "  const pending = new Map(); let next = 0;\n" +
                "  window.chrome.webview.addEventListener('message', event => {\n" +
                "    const reply = event.data;\n" +
                "    if (!reply || reply.kind !== 'reply' || !pending.has(reply.id)) return;\n" +
                "    const {resolve, reject} = pending.get(reply.id); pending.delete(reply.id);\n" +
                "    reply.error ? reject(new Error(reply.error)) : resolve(reply.result);\n" +
                "  });\n" +
                "  window.workbenchBridge = Object.freeze({call(type, data = {}) {\n" +
                "    return new Promise((resolve, reject) => {\n" +
                "      const id = ++next; pending.set(id, {resolve, reject});\n" +
                "      window.chrome.webview.postMessage({...data, kind: 'request', id, type});\n" +
                "    });\n" +
                "  }});\n" +
                $"  window.workbenchNative = Object.freeze({native});\n" +
                "})();";
        }

        async void WebMessageReceived(object sender, CoreWebView2WebMessageReceivedEventArgs e)
        {
            if (!IsWorkbench(e.Source)) return;
            Dictionary<string, object> message;
            try { message = json.Deserialize<Dictionary<string, object>>(e.WebMessageAsJson); }
            catch (Exception) { return; }
            if (message == null || !message.TryGetValue("kind", out var kind)) return;
            if ((kind as string) == "ui-test-result")
            {
                WriteUITestResult(message);
                return;
            }
            if ((kind as string) != "request" || !message.TryGetValue("id", out var id)) return;
            object result = null;
            string error = null;
            try { result = await HandleRequest(message.TryGetValue("type", out var type) ? type as string : null, message); }
            catch (BridgeError failure) { error = failure.Message; }
            catch (Exception) { error = "native request failed"; }
            if (webView.CoreWebView2 != null)
                webView.CoreWebView2.PostWebMessageAsJson(json.Serialize(new Dictionary<string, object> { ["kind"] = "reply", ["id"] = id, ["result"] = result, ["error"] = error }));
        }

        async Task<object> HandleRequest(string type, Dictionary<string, object> body)
        {
            switch (type)
            {
                case "clipboard.read":
                    return WithClipboard(ReadClipboard);
                case "clipboard.writeText":
                    if (!(body.TryGetValue("text", out var text) && text is string value)) throw new BridgeError("bad request");
                    WithClipboard(() =>
                    {
                        if (value.Length == 0) Clipboard.Clear();
                        else Clipboard.SetText(value, TextDataFormat.UnicodeText);
                        return true;
                    });
                    return Ok();
                case "openExternal":
                    if (!(body.TryGetValue("url", out var url) && url is string link) ||
                        !(link.StartsWith("https://", StringComparison.OrdinalIgnoreCase) || link.StartsWith("http://", StringComparison.OrdinalIgnoreCase)))
                        throw new BridgeError("bad request");
                    OpenExternal(link);
                    return Ok();
                case "revealFile":
                    if (!(body.TryGetValue("path", out var path) && path is string file) || !revealable.Contains(file)) throw new BridgeError("forbidden");
                    Process.Start(new ProcessStartInfo("explorer.exe", "/select," + AppPaths.JoinArguments(new[] { file })) { UseShellExecute = true });
                    return Ok();
                default:
                    if (type != null && type.StartsWith("test.", StringComparison.Ordinal)) return await HandleUITest(type, body);
                    throw new BridgeError("unknown request");
            }
        }

        static Dictionary<string, object> Ok() => new Dictionary<string, object> { ["ok"] = true };

        /// <summary>Another program may hold the clipboard for a moment; retry briefly.</summary>
        static T WithClipboard<T>(Func<T> action)
        {
            for (var attempt = 0; ; attempt++)
            {
                try { return action(); }
                catch (ExternalException) when (attempt < 5) { System.Threading.Thread.Sleep(50); }
            }
        }

        /// <summary>Same priority as the page's own clipboard code: an image first, then text.</summary>
        static Dictionary<string, object> ReadClipboard()
        {
            var result = new Dictionary<string, object>();
            if (Clipboard.ContainsFileDropList())
            {
                // Explorer copies are files, never a picture of their icon.
                result["files"] = Clipboard.GetFileDropList().Cast<string>().Select(Path.GetFileName).ToArray();
                return result;
            }
            var data = Clipboard.GetDataObject();
            if (data != null && data.GetDataPresent("PNG") && data.GetData("PNG") is MemoryStream png)
            {
                result["image"] = Convert.ToBase64String(png.ToArray());
            }
            else if (Clipboard.ContainsImage())
            {
                using (var image = Clipboard.GetImage())
                using (var stream = new MemoryStream())
                {
                    image.Save(stream, ImageFormat.Png);
                    result["image"] = Convert.ToBase64String(stream.ToArray());
                }
            }
            if (Clipboard.ContainsText(TextDataFormat.UnicodeText)) result["text"] = Clipboard.GetText(TextDataFormat.UnicodeText);
            return result;
        }

        // MARK: Developer self-test (the variables are never set for users)

        /// <summary>BROWSER_WORKBENCH_UI_TEST=script.js runs once the workbench page has loaded, with the
        /// page's globals in scope; its result and snapshots go to BROWSER_WORKBENCH_UI_TEST_OUT.</summary>
        static string UITestOutput
        {
            get
            {
                var script = Environment.GetEnvironmentVariable("BROWSER_WORKBENCH_UI_TEST");
                var output = Environment.GetEnvironmentVariable("BROWSER_WORKBENCH_UI_TEST_OUT");
                return string.IsNullOrEmpty(script) || string.IsNullOrEmpty(output) ? null : output;
            }
        }

        void RunUITestIfRequested()
        {
            var output = UITestOutput;
            if (uiTestStarted || output == null) return;
            uiTestStarted = true;
            Directory.CreateDirectory(output);
            var script = File.ReadAllText(Environment.GetEnvironmentVariable("BROWSER_WORKBENCH_UI_TEST"));
            _ = webView.CoreWebView2.ExecuteScriptAsync(
                "(async () => {\n" + script + "\n})().then(" +
                "result => window.chrome.webview.postMessage({kind: 'ui-test-result', ok: true, result}), " +
                "error => window.chrome.webview.postMessage({kind: 'ui-test-result', ok: false, error: String(error && error.stack || error)}));");
        }

        void WriteUITestResult(Dictionary<string, object> message)
        {
            var output = UITestOutput;
            if (output == null) return;
            message.Remove("kind");
            File.WriteAllText(Path.Combine(output, "result.json"), json.Serialize(message));
        }

        async Task<object> HandleUITest(string type, Dictionary<string, object> body)
        {
            var output = UITestOutput ?? throw new BridgeError("forbidden");
            switch (type)
            {
                case "test.snapshot":
                    if (!(body.TryGetValue("name", out var name) && name is string file) || !System.Text.RegularExpressions.Regex.IsMatch(file, "^[a-z0-9-]{1,40}$"))
                        throw new BridgeError("bad request");
                    using (var stream = File.Create(Path.Combine(output, file + ".png")))
                        await webView.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, stream);
                    return Ok();
                case "test.quit":
                    var stop = body.TryGetValue("stopEnvironments", out var value) && value is bool flag && flag;
                    BeginInvoke(new Action(() => _ = QuitAsync(stop)));
                    return Ok();
                default:
                    throw new BridgeError("unknown request");
            }
        }
    }
}
