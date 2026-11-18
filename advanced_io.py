"""Bounded atomic report writes, preserving the previous valid output on failure."""
from __future__ import annotations
import json,os,tempfile
from pathlib import Path


def write_json_atomic(path,report,*,limit=160*1024*1024):
    payload=json.dumps(report,indent=2,ensure_ascii=False).encode('utf-8')
    if len(payload)>limit:raise ValueError('JSON report exceeds size limit')
    dest=Path(path);dest.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('wb',dir=dest.parent,delete=False,suffix='.partial') as f:
        tmp=Path(f.name)
        try:
            f.write(payload);f.flush();os.fsync(f.fileno())
        except BaseException:
            tmp.unlink(missing_ok=True);raise
    try:os.replace(tmp,dest)
    except BaseException:tmp.unlink(missing_ok=True);raise
    return dest
