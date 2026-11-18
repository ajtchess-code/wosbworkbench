"""Application logging, crash capture and Windows DPI awareness.

The frozen Windows build has no console, so without this module an exception in
a button handler simply vanished. Everything is written to
%LOCALAPPDATA%\\WoSBWorkbench\\Logs (rotating), and the GUI shows a dialog with
"Copy details" and "Open logs" instead of failing silently.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import platform
import sys
import threading
import traceback
from datetime import datetime, timezone

LOGGER_NAME = 'wosb'
_configured = False


def log_dir():
    from workbench_db import home
    return home() / 'Logs'


def setup_logging(level=logging.INFO):
    """Idempotent: rotating file log (5 x 2 MB) plus stderr when one exists."""
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    if _configured:
        return logger
    folder = log_dir(); folder.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(folder / 'workbench.log', maxBytes=2 * 1024 * 1024,
                                                   backupCount=5, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)-7s %(threadName)s %(name)s: %(message)s'))
    logger.addHandler(handler)
    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setLevel(logging.WARNING)
        logger.addHandler(stream)
    logger.setLevel(level)
    _configured = True
    try:
        from workbench_db import VERSION
    except Exception:
        VERSION = '?'
    logger.info('WoSB Workbench %s starting · Python %s · %s', VERSION, platform.python_version(), platform.platform())
    return logger


def get(name=''):
    return logging.getLogger(LOGGER_NAME + ('.' + name if name else ''))


def write_crash_report(exc_type, exc, tb, *, context=''):
    """Write a standalone crash file and return (path, text)."""
    text = ''.join(traceback.format_exception(exc_type, exc, tb))
    try:
        from workbench_db import VERSION
    except Exception:
        VERSION = '?'
    header = (f'WoSB Workbench {VERSION} error report\n'
              f'Time (UTC): {datetime.now(timezone.utc).isoformat(timespec="seconds")}\n'
              f'Context: {context or "unspecified"}\n'
              f'Python {platform.python_version()} · {platform.platform()} · frozen={getattr(sys, "frozen", False)}\n\n')
    folder = log_dir(); folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('crash-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.txt')
    try:
        path.write_text(header + text, encoding='utf-8')
    except OSError:
        path = None
    get().error('Unhandled exception (%s)\n%s', context or 'unspecified', text)
    return path, header + text


def install_crash_handlers(root=None, *, show_dialog=None):
    """Hook sys/threading excepthooks and Tk's callback exception handler."""
    setup_logging()

    def handle(exc_type, exc, tb, context):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        path, text = write_crash_report(exc_type, exc, tb, context=context)
        if show_dialog and root is not None:
            try:
                root.after(0, lambda: show_dialog(str(exc) or exc_type.__name__, text, path))
            except Exception:
                pass

    sys.excepthook = lambda t, e, tb: handle(t, e, tb, 'main thread')
    threading.excepthook = lambda args: handle(args.exc_type, args.exc_value, args.exc_traceback,
                                               'thread ' + getattr(args.thread, 'name', '?'))
    if root is not None:
        root.report_callback_exception = lambda t, e, tb: handle(t, e, tb, 'UI callback')


def enable_dpi_awareness():
    """Per-monitor DPI awareness so Tk is not bitmap-scaled (blurry) on 125-200 % displays.

    Must run before the Tk root window is created. Returns the mode applied.
    """
    if os.name != 'nt':
        return 'not-windows'
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)   # PROCESS_PER_MONITOR_DPI_AWARE
        return 'per-monitor'
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return 'system'
    except (AttributeError, OSError):
        return 'unavailable'


def apply_tk_scaling(root):
    """Match Tk's point size to the monitor DPI after DPI awareness is on."""
    try:
        dpi = root.winfo_fpixels('1i')
        root.tk.call('tk', 'scaling', dpi / 72.0)
    except Exception:
        pass


def open_log_folder():
    folder = log_dir(); folder.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        os.startfile(str(folder))   # noqa: S606 - opens Explorer on our own folder
    return folder


def acquire_single_instance(name='WoSBWorkbenchMutex'):
    """Create a named mutex (lets the installer's AppMutex detect a running app).

    Returns (handle, already_running). Non-Windows: (None, False).
    """
    if os.name != 'nt':
        return None, False
    import ctypes
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
    already = ctypes.windll.kernel32.GetLastError() == 183   # ERROR_ALREADY_EXISTS
    return handle, already
