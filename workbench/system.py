"""What differs between macOS and Windows outside Docker: console windows of child
processes, opening a folder, the data folder's single-instance lock and the memory size."""
import ctypes
import os
import subprocess
import sys

# FILE_ATTRIBUTE_REPARSE_POINT: Windows symbolic links and junctions.
REPARSE_POINT = 0x400


def windows():
    return sys.platform == 'win32'


def quiet():
    """subprocess options: a child of the windowless Windows app would otherwise flash a console."""
    return {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)} if windows() else {}


def open_folder(path):
    if windows():
        os.startfile(str(path))  # opens it in File Explorer
    else:
        subprocess.Popen(['open', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def hold_lock(path):
    """Holds an exclusive lock on path while the returned file stays open; None if another process has it."""
    handle = open(path, 'a+')
    try:
        if windows():
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def memory_mb():
    """Physical memory of this computer, or None."""
    try:
        if windows():
            class MemoryStatus(ctypes.Structure):
                _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + \
                           [(name, ctypes.c_ulonglong) for name in ('total', 'available', 'total_page', 'available_page',
                                                                     'total_virtual', 'available_virtual', 'available_extended')]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return status.total // 1048576
        if sys.platform == 'darwin':
            output = subprocess.check_output(['sysctl', '-n', 'hw.memsize'], text=True, timeout=2, stderr=subprocess.DEVNULL)
            return int(output) // 1048576
    except (OSError, ValueError, subprocess.SubprocessError, AttributeError):
        pass
    return None
