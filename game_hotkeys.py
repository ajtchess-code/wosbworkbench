"""Optional Windows-only global shortcut listener for user-controlled capture markers.

Uses RegisterHotKey: no keyboard logging, no hooks, no game process injection.
Registers while recording only, then unregisters on stop. Another program can
own a key combination; those registrations are gracefully skipped.
"""
from __future__ import annotations
import os
import threading

SHORTCUTS={
    0x70:'single-shot',  # Ctrl+Alt+F1
    0x71:'broadside',    # F2
    0x72:'stern',        # F3
    0x73:'side',         # F4
    0x74:'sails',        # F5
    0x75:'target-sunk',  # F6
    0x76:'sync-flash',   # F7
    0x77:'hit',          # F8
    0x78:'minor-fire',   # F9
    0x79:'large-fire',   # F10
}

class CaptureHotkeys:
    def __init__(self,callback):
        self.callback=callback;self.thread=None;self.thread_id=None
        self._ready=threading.Event();self._enabled=[]

    def start(self):
        if os.name!='nt':return False
        if self.thread and self.thread.is_alive():return True
        self._ready.clear()
        self.thread=threading.Thread(target=self._worker,name='WoSB-hotkeys',daemon=True)
        self.thread.start();self._ready.wait(timeout=4)
        return bool(self._enabled)

    def _worker(self):
        import ctypes
        from ctypes import wintypes
        user32=ctypes.windll.user32
        kernel32=ctypes.windll.kernel32
        self.thread_id=kernel32.GetCurrentThreadId()
        msg=wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg),None,0,0,0) # create thread message queue
        enabled=[]
        for vk,event in SHORTCUTS.items():
            key_id=41000+(vk-0x70)
            if user32.RegisterHotKey(None,key_id,0x0001|0x0002,vk):
                enabled.append((key_id,event))
        self._enabled=enabled;self._ready.set()
        try:
            while user32.GetMessageW(ctypes.byref(msg),None,0,0)>0:
                if msg.message==0x0312:  # WM_HOTKEY
                    idx=msg.wParam
                    event=next((e for i,e in enabled if i==idx),None)
                    if event:
                        try:self.callback(event)
                        except Exception:pass  # listener must remain alive
        finally:
            for key_id,_ in enabled:user32.UnregisterHotKey(None,key_id)
            self._enabled=[]
            self.thread_id=None
            self._ready.set()

    def stop(self):
        if os.name=='nt' and self.thread_id is not None:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self.thread_id,0x0012,0,0) # WM_QUIT
            if self.thread and self.thread.is_alive():self.thread.join(timeout=2)
        self._enabled=[];self.thread_id=None
