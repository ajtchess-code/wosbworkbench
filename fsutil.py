"""Filesystem helpers shared by the desktop app."""
import os


def replace_with_retry(source, target, attempts=12):
    """os.replace that tolerates Windows sharing violations.

    On Windows a file cannot be replaced while another process has it open
    (the GUI polling a status file, antivirus, the search indexer), which
    raises PermissionError / WinError 5 or 32. Retry with a short backoff
    (about 3 s in total) before giving up.
    """
    import time as _time
    delay = 0.02
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            _time.sleep(delay)
            delay = min(delay * 2, 0.5)
