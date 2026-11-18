"""Compact, resumable recovery triage archives (not another complete game export).

Explicitly excludes successfully decoded assets, original game binaries, and
network captures. Archives contain only read-only recovery metadata and small
reproducibility evidence, split to an absolute ZIP file size cap.
"""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
from collections import Counter
from zipfile import ZipFile, ZIP_DEFLATED

DEFAULT_LIMIT = 45 * 1024 * 1024
MAX_RECORD = 2 * 1024 * 1024


def issue_key(row):
    reason = row.get('error_type') or row.get('reason') or 'reader_identified_body_unimplemented'
    return (row.get('kind') or 'unknown', row.get('status') or 'unknown', str(reason))


def gather(recovery_dir):
    root = Path(recovery_dir).resolve()
    ledger = root/'Reports'/'AssetLedger.jsonl'
    records = []; groups = Counter(); skipped = 0
    if ledger.is_file():
        with ledger.open(encoding='utf-8') as fh:
            for line in fh:
                try: row = json.loads(line)
                except json.JSONDecodeError:
                    skipped += 1; continue
                if row.get('status') in ('decoded','indexed','preserved'):
                    continue
                brief = {k: row[k] for k in ('path','kind','status','error_type','error','reason','readers','root_reader_id','sha256','bytes','xnb_header','xnb') if k in row}
                records.append(brief); groups[issue_key(brief)] += 1
    sources = {}
    for rel in ('Recovery-Status.json','Code-Recovery/Errors.json','Code-Recovery/Assemblies.json','Code-Recovery/Combat-and-Protocol-Research-Queue.json','Code-Recovery/Verified-Client-Methods.json','Reports/Repair-Queue.json','Reports/Repair-Queue.md'):
        f=root/rel
        if f.is_file() and f.stat().st_size <= 3*1024*1024:
            sources[rel]=f.read_bytes()
    unresolved = root/'Reports'/'ModelTextureLinks.jsonl'
    if unresolved.is_file():
        with unresolved.open(encoding='utf-8') as fh:
            bad = [line for line in fh if '"unresolved"' in line]
        sources['Reports/UnresolvedMaterials.jsonl']=''.join(bad).encode('utf-8')
    return records,groups,sources,skipped


def export_review(recovery_dir, *, limit=DEFAULT_LIMIT, destination=None):
    """Produce individually readable ZIPs <= limit. Returns absolute file paths."""
    if limit < 64*1024:raise ValueError('ZIP size limit must be at least 64 KiB')
    root=Path(recovery_dir).resolve()
    dest=Path(destination or root/'Review-For-Analysis').resolve()
    if root not in dest.parents and root != dest: # external output is okay
        pass
    dest.mkdir(parents=True, exist_ok=True)
    for f in dest.glob('WoSB-Review-Part-*.zip'):f.unlink()
    records,groups,sources,skipped=gather(root)
    summary={'format':'wosb-failure-review-v4','source':str(root),
             'total_open_issues':len(records),'unreadable_ledger_lines':skipped,
             'issue_groups':[{'kind':k[0],'status':k[1],'reason':k[2],'count':v} for k,v in groups.most_common()],
             'warning':'Candidate method names and client-side values do not prove authoritative game-server mechanics.'}
    readme=('WoSB Workbench review-only bundle\n\n'
            'Contains ONLY failed/unsupported decoder records, unresolved material links,\n'
            'assembly warnings, and scan metadata. No complete success ledger, image collection,\n'
            'original game binaries, player data or packet contents are included.\n'
            'Every ZIP is independently readable; files are numbered for uploading in order.\n')
    data=[('README.txt',readme.encode('utf-8')),('Review-Summary.json',json.dumps(summary,indent=2).encode('utf-8'))]
    data.extend((name,blob) for name,blob in sources.items())
    # Split line-oriented failures by compressed-size batches; never lose large individual records.
    issue_lines=[json.dumps(rec,ensure_ascii=False).encode('utf-8')+b'\n' for rec in records]
    current=io.BytesIO();idx=1;archives=[]
    def emit():
        nonlocal current,idx
        if not current.tell():return
        p=dest/f'WoSB-Review-Part-{idx:03d}.zip'
        # Start with a conservative uncompressed upper bound so ZIP overhead cannot exceed limit.
        with ZipFile(p,'w',ZIP_DEFLATED,compresslevel=6) as z:
            if idx==1:
                for name,blob in data:
                    # Guard large metadata, but never silently discard evidence
                    if len(blob)>limit//3:
                        for j in range(0,len(blob),limit//5):
                            z.writestr(name+f'.chunk{j//(limit//5)+1:03d}',blob[j:j+limit//5])
                    else:z.writestr(name,blob)
            else:z.writestr('README.txt',readme)
            z.writestr('Failed-and-Unsupported.jsonl',current.getvalue())
        if p.stat().st_size>limit:
            p.unlink();raise RuntimeError('Review ZIP exceeds byte limit; try a smaller budget')
        archives.append(p);idx+=1;current=io.BytesIO()
    # Base first-part metadata is expected to be small; for oversized telemetry, callers lower limit explicitly.
    budget=max(8192,limit//2)
    for line in issue_lines:
        if len(line)>MAX_RECORD:line=json.dumps({'status':'truncated','reason':'oversized metadata record','bytes':len(line)}).encode()+b'\n'
        if current.tell()+len(line)>budget:emit()
        current.write(line)
    emit()
    if not archives:
        p=dest/'WoSB-Review-Part-001.zip'
        with ZipFile(p,'w',ZIP_DEFLATED) as z:
            for name,blob in data:z.writestr(name,blob)
            z.writestr('Failed-and-Unsupported.jsonl',b'')
        archives=[p]
    (dest/'Review-Index.json').write_text(json.dumps({'summary':summary,'parts':[{'filename':p.name,'bytes':p.stat().st_size} for p in archives]},indent=2),encoding='utf-8')
    return archives


def main(argv=None):
    p=argparse.ArgumentParser(description='Create small ZIPs containing only recovery failures and code warnings')
    p.add_argument('--recovery',required=True)
    p.add_argument('--max-mb',type=int,default=45)
    args=p.parse_args(argv)
    for file in export_review(args.recovery,limit=args.max_mb*1024*1024):print(file)

if __name__=='__main__':main()
