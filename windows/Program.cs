using System;
using System.Threading;
using System.Windows.Forms;

namespace BrowserWorkbench
{
    static class Program
    {
        const string InstanceName = @"Local\BrowserWorkbench";

        [STAThread]
        static void Main()
        {
            // One window per user session: a second launch brings the first one forward.
            using (var instance = new Mutex(true, InstanceName, out var first))
            using (var activate = new EventWaitHandle(false, EventResetMode.AutoReset, InstanceName + "-Activate"))
            {
                if (!first)
                {
                    activate.Set();
                    return;
                }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.SetUnhandledExceptionMode(UnhandledExceptionMode.CatchException);
                Application.ThreadException += (_, e) => Report(e.Exception);
                AppDomain.CurrentDomain.UnhandledException += (_, e) => Report(e.ExceptionObject as Exception);
                var form = new MainForm();
                var listener = new Thread(() =>
                {
                    try
                    {
                        while (activate.WaitOne())
                        {
                            try { form.BeginInvoke(new Action(form.BringForward)); }
                            catch (InvalidOperationException) { }  // the window is not created yet or already closing
                        }
                    }
                    catch (ObjectDisposedException) { }  // the app is exiting
                }) { IsBackground = true, Name = "activate" };
                listener.Start();
                Application.Run(form);
                GC.KeepAlive(instance);
            }
        }

        /// <summary>An unexpected error goes to the log folder, so a problem on someone else's PC can be traced.</summary>
        public static void Report(Exception error)
        {
            try
            {
                System.IO.Directory.CreateDirectory(AppPaths.LogDirectory);
                System.IO.File.AppendAllText(System.IO.Path.Combine(AppPaths.LogDirectory, "shell-error.log"),
                    $"--- {DateTime.Now:yyyy-MM-dd HH:mm:ss} Browser Workbench {AppPaths.Version}{Environment.NewLine}{error}{Environment.NewLine}");
                MessageBox.Show("Browser Workbench 遇到意外错误，详情已记录在日志文件夹的 shell-error.log 中。\n\n" + error?.Message,
                    "Browser Workbench", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
            catch (Exception) { }
        }
    }
}
