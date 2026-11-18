"""Explicit opt-in verified update downloads, never silent client-code execution."""
from fsutil import replace_with_retry
import hashlib
import json
import os
import re
import ssl
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from workbench_db import VERSION,home

MAX_MANIFEST = 256*1024
MAX_INSTALLER = 700*1024*1024

def allowed_url(url):
    parts=urlsplit(url)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password:
        raise ValueError('Release URL must be a normal HTTPS URL')
    return url

def version_tuple(version):
    if not re.fullmatch(r'\d+(?:\.\d+){1,3}',str(version)):
        raise ValueError('Invalid update version')
    return tuple(map(int,version.split('.')))

def fetch_manifest(url,timeout=15):
    url=allowed_url(url)
    request=urllib.request.Request(url,headers={'User-Agent':'WoSBWorkbench/'+VERSION})
    with urllib.request.urlopen(request,timeout=timeout,context=ssl.create_default_context()) as response:
        if urlsplit(response.geturl()).scheme!='https':raise ValueError('Unsafe manifest redirect')
        content=response.read(MAX_MANIFEST+1)
    if len(content)>MAX_MANIFEST:raise ValueError('Manifest too large')
    manifest=json.loads(content.decode('utf-8'))
    if not isinstance(manifest,dict):raise ValueError('Manifest must be an object')
    version_tuple(manifest.get('version',''))
    installer=allowed_url(manifest.get('installer_url',''))
    if not installer.lower().split('?',1)[0].endswith('.exe'):
        raise ValueError('Update must be a Windows installer .exe')
    if not re.fullmatch('[a-fA-F0-9]{64}',manifest.get('sha256','')):
        raise ValueError('Installer SHA-256 required')
    # The SHA-256 arrives in the same manifest, so on its own it only proves the
    # download matches the manifest. A bundled publisher key makes the feed
    # tamper-evident: an unsigned or re-signed manifest is rejected.
    from update_signing import bundled_public_key, verify_manifest
    key=bundled_public_key()
    if key is not None:
        if not verify_manifest(manifest,key):
            raise ValueError('Release manifest signature is missing or invalid; update rejected')
        manifest['_signature_verified']=True
    else:
        manifest['_signature_verified']=False
    return manifest

def download_verified(manifest,on_progress=None,folder=None):
    url=allowed_url(manifest['installer_url']);version=manifest['version']
    version_tuple(version)
    out=Path(folder or (home()/'Updates'))
    out.mkdir(parents=True,exist_ok=True)
    target=out/('WoSBWorkbench-'+version+'-Setup.exe')
    temp=out/('WoSBWorkbench-'+version+'-Setup.exe.partial')
    hashed=hashlib.sha256();size=0
    request=urllib.request.Request(url,headers={'User-Agent':'WoSBWorkbench/'+VERSION})
    try:
        with urllib.request.urlopen(request,timeout=60,context=ssl.create_default_context()) as res:
            if urlsplit(res.geturl()).scheme!='https':raise ValueError('Unsafe installer redirect')
            total=int(res.headers.get('Content-Length','0'))
            if total>MAX_INSTALLER:raise ValueError('Installer exceeds safety limit')
            with temp.open('wb') as output:
                while True:
                    part=res.read(1024*1024)
                    if not part:break
                    size+=len(part)
                    if size>MAX_INSTALLER:raise ValueError('Installer exceeds safety limit')
                    output.write(part);hashed.update(part)
                    if on_progress:on_progress(size,total)
        if hashed.hexdigest().lower()!=manifest['sha256'].lower():
            raise ValueError('SHA-256 mismatch. Update rejected.')
        replace_with_retry(temp,target)
        return target
    except Exception:
        temp.unlink(missing_ok=True)
        raise
