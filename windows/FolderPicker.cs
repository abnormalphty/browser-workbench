using System;
using System.IO;
using System.Runtime.InteropServices;

namespace BrowserWorkbench
{
    /// <summary>Windows' own folder picker, the one Explorer uses (.NET Framework's FolderBrowserDialog is the
    /// old tree view). Returns the chosen folder, or null if the user cancelled.</summary>
    static class FolderPicker
    {
        const uint PickFolders = 0x20, ForceFileSystem = 0x40, NoChangeDirectory = 0x8, PathMustExist = 0x800;
        const uint FileSystemPath = 0x80058000;  // SIGDN_FILESYSPATH
        static readonly int Cancelled = unchecked((int)0x800704C7);  // HRESULT_FROM_WIN32(ERROR_CANCELLED)

        public static string Pick(IntPtr owner, string title, string startIn)
        {
            var dialog = (IFileDialog)new FileOpenDialog();
            try
            {
                dialog.GetOptions(out var options);
                dialog.SetOptions(options | PickFolders | ForceFileSystem | NoChangeDirectory | PathMustExist);
                dialog.SetTitle(title);
                dialog.SetOkButtonLabel("选择此文件夹");
                if (!string.IsNullOrEmpty(startIn) && Directory.Exists(startIn) &&
                    NativeShell.SHCreateItemFromParsingName(startIn, IntPtr.Zero, typeof(IShellItem).GUID, out var folder) == 0)
                    dialog.SetFolder(folder);
                var result = dialog.Show(owner);
                if (result == Cancelled) return null;
                Marshal.ThrowExceptionForHR(result);
                dialog.GetResult(out var item);
                item.GetDisplayName(FileSystemPath, out var path);
                return path;
            }
            finally
            {
                Marshal.ReleaseComObject(dialog);
            }
        }

        [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")]
        class FileOpenDialog { }

        // IModalWindow, then IFileDialog, in vtable order; only some are called.
        [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        interface IFileDialog
        {
            [PreserveSig] int Show(IntPtr parent);
            void SetFileTypes(uint count, IntPtr filters);
            void SetFileTypeIndex(uint index);
            void GetFileTypeIndex(out uint index);
            void Advise(IntPtr events, out uint cookie);
            void Unadvise(uint cookie);
            void SetOptions(uint options);
            void GetOptions(out uint options);
            void SetDefaultFolder(IShellItem folder);
            void SetFolder(IShellItem folder);
            void GetFolder(out IShellItem folder);
            void GetCurrentSelection(out IShellItem item);
            void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
            void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string name);
            void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
            void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string text);
            void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
            void GetResult(out IShellItem item);
            void AddPlace(IShellItem item, int placement);
            void SetDefaultExtension([MarshalAs(UnmanagedType.LPWStr)] string extension);
            void Close(int result);
            void SetClientGuid(ref Guid guid);
            void ClearClientData();
            void SetFilter(IntPtr filter);
        }

        [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
        internal interface IShellItem
        {
            void BindToHandler(IntPtr context, ref Guid handler, ref Guid interfaceId, out IntPtr result);
            void GetParent(out IShellItem parent);
            void GetDisplayName(uint kind, [MarshalAs(UnmanagedType.LPWStr)] out string name);
            void GetAttributes(uint mask, out uint attributes);
            void Compare(IShellItem other, uint hint, out int order);
        }

        static class NativeShell
        {
            [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
            public static extern int SHCreateItemFromParsingName(string path, IntPtr context,
                [MarshalAs(UnmanagedType.LPStruct)] Guid interfaceId, out IShellItem item);
        }
    }
}
