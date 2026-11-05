using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;

namespace BrowserWorkbench
{
    /// <summary>Where the app keeps its files. Overridable for tests so they never touch real data.</summary>
    static class AppPaths
    {
        static string Custom(string name)
        {
            var value = Environment.GetEnvironmentVariable(name);
            return string.IsNullOrEmpty(value) ? null : value;
        }

        static string Root => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "BrowserWorkbench");

        public static string DataDirectory => Custom("BROWSER_WORKBENCH_DATA_DIR") ?? Path.Combine(Root, "Data");
        public static string LogDirectory => Custom("BROWSER_WORKBENCH_LOG_DIR") ?? Path.Combine(Root, "Logs");
        public static string WebViewDirectory => Custom("BROWSER_WORKBENCH_WEBVIEW_DIR") ?? Path.Combine(Root, "WebView2");
        public static string WindowState => Path.Combine(Root, "window.txt");
        public static string DownloadsDirectory => Custom("BROWSER_WORKBENCH_DOWNLOADS_DIR") ?? KnownDownloads();
        public static string BackendLog => Path.Combine(LogDirectory, "backend.log");

        public static string Install => AppDomain.CurrentDomain.BaseDirectory;
        public static string Python => Path.Combine(Install, "python", "python.exe");
        public static string Backend => Path.Combine(Install, "backend");

        public static string ImageArchive
        {
            get
            {
                var path = Path.Combine(Install, "runtime-image", "browser-runtime.tar.gz");
                return File.Exists(path) ? path : null;
            }
        }

        public static string Version =>
            Assembly.GetExecutingAssembly().GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion ?? "0";

        /// <summary>The bundled interpreter, isolated from any Python the user installed.</summary>
        public static ProcessStartInfo PythonProcess(IEnumerable<string> arguments, IDictionary<string, string> extraEnvironment)
        {
            var all = new List<string> { "-E", "-s", "-B", "-X", "utf8" };
            all.AddRange(arguments);
            var info = new ProcessStartInfo(Python, JoinArguments(all))
            {
                WorkingDirectory = Backend,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = new UTF8Encoding(false),
                StandardErrorEncoding = new UTF8Encoding(false),
            };
            var names = new List<string>();
            foreach (string key in info.EnvironmentVariables.Keys) names.Add(key);
            foreach (var key in names)
                if (key.StartsWith("PYTHON", StringComparison.OrdinalIgnoreCase)) info.EnvironmentVariables.Remove(key);
            foreach (var pair in extraEnvironment) info.EnvironmentVariables[pair.Key] = pair.Value;
            return info;
        }

        /// <summary>Command line quoting as the Microsoft C runtime parses it back.</summary>
        public static string JoinArguments(IEnumerable<string> arguments)
        {
            var line = new StringBuilder();
            foreach (var argument in arguments)
            {
                if (line.Length > 0) line.Append(' ');
                if (argument.Length > 0 && argument.IndexOfAny(new[] { ' ', '\t', '"' }) < 0)
                {
                    line.Append(argument);
                    continue;
                }
                line.Append('"');
                var backslashes = 0;
                foreach (var c in argument)
                {
                    if (c == '\\') { backslashes++; continue; }
                    if (c == '"') line.Append('\\', backslashes * 2 + 1);
                    else line.Append('\\', backslashes);
                    backslashes = 0;
                    line.Append(c);
                }
                line.Append('\\', backslashes * 2);
                line.Append('"');
            }
            return line.ToString();
        }

        static string KnownDownloads()
        {
            var downloads = new Guid("374DE290-123F-4565-9164-39C4925E467B");
            if (NativeMethods.SHGetKnownFolderPath(ref downloads, 0, IntPtr.Zero, out var pointer) == 0)
            {
                try { return Marshal.PtrToStringUni(pointer); }
                finally { Marshal.FreeCoTaskMem(pointer); }
            }
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "Downloads");
        }
    }
}
