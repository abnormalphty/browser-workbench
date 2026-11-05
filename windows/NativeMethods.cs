using System;
using System.Runtime.InteropServices;

namespace BrowserWorkbench
{
    static class NativeMethods
    {
        [DllImport("shell32.dll")]
        public static extern int SHGetKnownFolderPath(ref Guid folder, uint flags, IntPtr token, out IntPtr path);

        // DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 10 2004 and later): a dark title bar in dark mode.
        [DllImport("dwmapi.dll")]
        public static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);

        [DllImport("user32.dll")]
        public static extern IntPtr GetSystemMenu(IntPtr window, bool revert);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        public static extern bool AppendMenu(IntPtr menu, uint flags, UIntPtr id, string text);

        public const uint MenuSeparator = 0x800;
        public const int SystemCommand = 0x112;  // WM_SYSCOMMAND
    }
}
