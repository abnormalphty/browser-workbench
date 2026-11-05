using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;

namespace BrowserWorkbench
{
    enum BackendState { Stopped, Starting, Ready, Failed }

    sealed class Summary
    {
        public int Running, Paused, Starting;
        public int Active => Running + Paused + Starting;
    }

    /// <summary>Runs the Python backend and reports when it is reachable. Same contract as the
    /// Mac app: one WORKBENCH_READY line names the port, and closing stdin asks it to exit.</summary>
    sealed class Backend
    {
        readonly SynchronizationContext ui = SynchronizationContext.Current;
        readonly object gate = new object();
        Process process;
        StreamWriter log;
        bool lockedOut, stopping;
        const int ExitLocked = 3;  // EXIT_LOCKED in workbench/desktop.py
        int launchCount;
        readonly List<Action> stopWaiters = new List<Action>();

        public BackendState State { get; private set; } = BackendState.Stopped;
        public int Port { get; private set; }
        public string Failure { get; private set; }
        public event Action StateChanged;

        public readonly string ControlToken = NewToken();

        static string NewToken()
        {
            var bytes = new byte[32];
            using (var random = RandomNumberGenerator.Create()) random.GetBytes(bytes);
            return Convert.ToBase64String(bytes).Replace('+', '-').Replace('/', '_').TrimEnd('=');
        }

        void Set(BackendState state, int port = 0, string failure = null)
        {
            if (State == state && Port == port && Failure == failure) return;
            State = state; Port = port; Failure = failure;
            StateChanged?.Invoke();
        }

        void OnUi(Action action) => ui.Post(_ => action(), null);

        public void Start()
        {
            if (process != null) return;
            lockedOut = false;
            stopping = false;
            Set(BackendState.Starting);
            try
            {
                Directory.CreateDirectory(AppPaths.DataDirectory);
                Directory.CreateDirectory(AppPaths.LogDirectory);
            }
            catch (Exception error)
            {
                Set(BackendState.Failed, failure: "无法创建数据文件夹：" + error.Message);
                return;
            }
            if (!File.Exists(AppPaths.Python))
            {
                Set(BackendState.Failed, failure: "应用内的运行组件不完整，请重新安装 Browser Workbench。");
                return;
            }
            OpenLog();

            var extra = new Dictionary<string, string>
            {
                ["WORKBENCH_CONTROL_TOKEN"] = ControlToken,
                ["WORKBENCH_MODE"] = "desktop",
                ["WORKBENCH_APP_VERSION"] = AppPaths.Version,
            };
            if (AppPaths.ImageArchive != null) extra["WORKBENCH_IMAGE_ARCHIVE"] = AppPaths.ImageArchive;
            var started = new Process
            {
                StartInfo = AppPaths.PythonProcess(new[] { "-m", "workbench.desktop", "--data-dir", AppPaths.DataDirectory, "--exit-on-stdin-eof" }, extra),
                EnableRaisingEvents = true,
            };
            started.OutputDataReceived += (_, e) => { if (e.Data != null) { WriteLog(e.Data); OnUi(() => Handle(e.Data)); } };
            started.ErrorDataReceived += (_, e) => { if (e.Data != null) WriteLog(e.Data); };
            started.Exited += (_, __) =>
            {
                // Let the last output lines (WORKBENCH_ERROR) be handled before the exit: the parameterless
                // WaitForExit also waits for the asynchronous readers to reach the end of the output.
                try { started.WaitForExit(); } catch (Exception) { }
                int code;
                try { code = started.ExitCode; } catch (InvalidOperationException) { code = -1; }
                OnUi(() => DidExit(started, code));
            };
            try
            {
                started.Start();
            }
            catch (Exception error)
            {
                Set(BackendState.Failed, failure: "后台服务无法启动：" + error.Message);
                return;
            }
            started.BeginOutputReadLine();
            started.BeginErrorReadLine();
            process = started;
            var launch = ++launchCount;
            // Python normally answers within seconds; never leave the window spinning forever.
            Task.Delay(TimeSpan.FromSeconds(90)).ContinueWith(_ => OnUi(() =>
            {
                if (launchCount != launch || State != BackendState.Starting || process == null) return;
                Stop(() => Set(BackendState.Failed, failure: "后台服务启动超时。可以点重试；如果反复出现，请查看日志。"));
            }));
        }

        /// <summary>Ends the backend: closing its stdin is the request, killing it the fallback.</summary>
        public void Stop(Action completion = null)
        {
            var current = process;
            if (current == null)
            {
                completion?.Invoke();
                return;
            }
            if (completion != null) stopWaiters.Add(completion);
            if (stopping) return;
            stopping = true;
            try { current.StandardInput.Close(); } catch (Exception) { }
            // Only this process: by now a restart may already have launched a new one.
            Task.Delay(TimeSpan.FromSeconds(8)).ContinueWith(_ =>
            {
                try { if (!current.HasExited) current.Kill(); } catch (Exception) { }
            });
        }

        public void Restart() => Stop(Start);

        void Handle(string line)
        {
            if (line.StartsWith("WORKBENCH_READY ", StringComparison.Ordinal))
            {
                try
                {
                    var json = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(line.Substring(16));
                    if (json != null && json.TryGetValue("port", out var port))
                        Set(BackendState.Ready, Convert.ToInt32(port));
                }
                catch (Exception) { }
            }
            else if (line.StartsWith("WORKBENCH_ERROR ", StringComparison.Ordinal) && line.Contains("locked"))
            {
                lockedOut = true;
            }
        }

        void DidExit(Process exited, int code)
        {
            if (exited != process) return;
            process = null;
            var wasStopping = stopping;
            stopping = false;
            if (wasStopping) Set(BackendState.Stopped);
            else if (lockedOut || code == ExitLocked) Set(BackendState.Failed, failure: "另一个 Browser Workbench 正在使用同一个数据文件夹。请先关闭另一个窗口，再点重试。");
            else Set(BackendState.Failed, failure: $"后台服务意外停止（代码 {code}）。浏览器环境不受影响，可以点重试重新连接。");
            lock (gate) { log?.Dispose(); log = null; }
            var waiters = stopWaiters.ToArray();
            stopWaiters.Clear();
            foreach (var waiter in waiters) waiter();
        }

        // Native control API (separate secret from the page token)

        async Task<Dictionary<string, object>> Control(string path, HttpMethod method, TimeSpan timeout)
        {
            if (State != BackendState.Ready) return null;
            try
            {
                // Straight to this computer: never through a proxy configured in Windows settings.
                using (var client = new HttpClient(new HttpClientHandler { UseProxy = false }) { Timeout = timeout })
                using (var request = new HttpRequestMessage(method, $"http://127.0.0.1:{Port}/control/{path}"))
                {
                    request.Headers.Add("X-Workbench-Control", ControlToken);
                    using (var response = await client.SendAsync(request).ConfigureAwait(true))
                    {
                        if (!response.IsSuccessStatusCode) return null;
                        var text = await response.Content.ReadAsStringAsync().ConfigureAwait(true);
                        return new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(text);
                    }
                }
            }
            catch (Exception)
            {
                return null;
            }
        }

        static int Number(Dictionary<string, object> json, string key) =>
            json != null && json.TryGetValue(key, out var value) && value != null ? Convert.ToInt32(value) : 0;

        public async Task<Summary> SummaryAsync()
        {
            var json = await Control("summary", HttpMethod.Get, TimeSpan.FromSeconds(15));
            if (json == null) return null;
            return new Summary { Running = Number(json, "running"), Paused = Number(json, "paused"), Starting = Number(json, "starting") };
        }

        public async Task<bool> StopAllEnvironmentsAsync()
        {
            var json = await Control("stop-all", HttpMethod.Post, TimeSpan.FromSeconds(120));
            return json != null && json.TryGetValue("ok", out var ok) && ok is bool done && done;
        }

        // Log

        void OpenLog()
        {
            lock (gate)
            {
                try
                {
                    var path = AppPaths.BackendLog;
                    if (File.Exists(path) && new FileInfo(path).Length > 5_000_000)
                    {
                        File.Delete(path + ".1");
                        File.Move(path, path + ".1");
                    }
                    log = new StreamWriter(new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite), new UTF8Encoding(false)) { AutoFlush = true };
                    log.WriteLine();
                    log.WriteLine($"--- {DateTime.Now:yyyy-MM-dd HH:mm:ss} Browser Workbench {AppPaths.Version} ---");
                }
                catch (Exception)
                {
                    log = null;
                }
            }
        }

        void WriteLog(string line)
        {
            lock (gate)
            {
                try { log?.WriteLine(line); } catch (Exception) { }
            }
        }
    }
}
