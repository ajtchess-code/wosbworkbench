"""External updater: apply a locally selected WoSB Workbench release ZIP after exit."""
from __future__ import annotations
import argparse
import datetime
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from offline_updates import apply_verified_update


def _wait_windows(pid: int, timeout: int) -> bool:
    """Wait on a real process handle. Returns True once the process has exited.

    ``os.kill(pid, 0)`` must NOT be used on Windows: signal 0 equals
    CTRL_C_EVENT there, so CPython calls GenerateConsoleCtrlEvent(pid), which
    either fails immediately (making the updater think the GUI already exited
    while WoSBWorkbench.exe is still locked) or delivers Ctrl+C to a console
    group. Waiting on a SYNCHRONIZE handle is the documented approach.
    """
    import ctypes
    from ctypes import wintypes
    SYNCHRONIZE = 0x00100000
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    WAIT_OBJECT_0 = 0
    WAIT_TIMEOUT = 0x102
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # ERROR_INVALID_PARAMETER (87): no such process, i.e. it already exited.
        if ctypes.get_last_error() == 87:
            return True
        raise OSError('Cannot open Workbench process '+str(pid)+' (error '+str(ctypes.get_last_error())+')')
    try:
        result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
    finally:
        kernel32.CloseHandle(handle)
    if result == WAIT_OBJECT_0:
        return True
    if result == WAIT_TIMEOUT:
        return False
    raise OSError('WaitForSingleObject failed for process '+str(pid))


def _pid_alive_posix(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    return True


def wait_for_exit(pid: int, timeout: int = 180, *, settle: float = 1.0):
    if pid <= 0:return
    if os.name == 'nt':
        if not _wait_windows(pid, timeout):
            raise TimeoutError('Workbench did not close within '+str(timeout)+' seconds')
    else:
        until=time.monotonic()+timeout
        while _pid_alive_posix(pid):
            if time.monotonic() >= until:
                raise TimeoutError('Workbench did not close within '+str(timeout)+' seconds')
            time.sleep(.5)
    # Give Windows a moment to release image-file locks held by the exited
    # process (and the PyInstaller bootloader parent) before files are replaced.
    if settle > 0:
        time.sleep(settle)


def main():
    p=argparse.ArgumentParser(description='WoSB Workbench offline ZIP patch installer')
    p.add_argument('--zip',required=True)
    p.add_argument('--install-dir',required=True)
    p.add_argument('--backup-dir',required=True)
    p.add_argument('--current-version',required=True)
    p.add_argument('--wait-pid',type=int,default=0)
    p.add_argument('--launch',required=True,help='WoSBWorkbench.exe or desktop_main.py')
    p.add_argument('--log',required=True)
    p.add_argument('--public-key',default='',help='Hex Ed25519 publisher key; required signature when given')
    a=p.parse_args()
    file=Path(a.log)
    file.parent.mkdir(parents=True,exist_ok=True)
    def note(message):
        with file.open('a',encoding='utf-8') as log:
            log.write(datetime.datetime.now().isoformat(timespec='seconds')+' '+message+'\n')
    try:
        note('Waiting for Workbench process '+str(a.wait_pid))
        wait_for_exit(a.wait_pid)
        note('Applying local ZIP update')
        info=apply_verified_update(a.zip,a.install_dir,a.backup_dir,a.current_version,log=note,
                                   public_key=a.public_key or None,require_signature=bool(a.public_key))
        note('Applied update '+info.version+' successfully')
        launch=Path(a.install_dir)/a.launch
        if not launch.is_file():
            note('Updated, but launch target does not exist: '+str(launch))
            return 0
        if launch.suffix.lower()=='.py':
            subprocess.Popen([sys.executable,str(launch)],cwd=str(Path(a.install_dir)),close_fds=True)
        else:
            subprocess.Popen([str(launch)],cwd=str(Path(a.install_dir)),close_fds=True)
        note('Relaunched Workbench')
        return 0
    except Exception as exc:
        note('UPDATE FAILED: '+repr(exc))
        note(traceback.format_exc())
        return 1

if __name__=='__main__':sys.exit(main())
