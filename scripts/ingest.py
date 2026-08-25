"""Ingest one crawler export into the multi-target archive."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from .core import apply_snapshot, dumps, initial_state, normalize_item, now_iso, summary
ROOT=Path(__file__).resolve().parents[1]
def load_json(path): return json.loads(path.read_text(encoding='utf-8'))
def target_config(target_id):
    path=ROOT/'targets'/target_id/'target.json'
    if not path.exists(): raise SystemExit(f'Unknown target {target_id!r}: {path} does not exist')
    return load_json(path)
def sanitize_timestamp(value): return re.sub(r'[^0-9A-Za-z._-]+','-',value.strip()).strip('-') or 'snapshot'
def preserve_raw(target_id, source, raw, exported_at):
    sha=hashlib.sha256(raw).hexdigest(); folder=ROOT/'archive'/target_id/'raw'; folder.mkdir(parents=True,exist_ok=True); dest=folder/f'{sanitize_timestamp(exported_at)}-{sha[:12]}.json'
    if not dest.exists(): dest.write_bytes(raw)
    dest.with_suffix(dest.suffix+'.sha256').write_text(f'{sha}  {dest.name}\n',encoding='utf-8'); return dest,sha
def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('source',type=Path); p.add_argument('--target',required=True); p.add_argument('--complete',action='store_true',help='Declare a complete comparable snapshot; required for missing detection.'); a=p.parse_args()
    config=target_config(a.target); raw=a.source.read_bytes(); payload=json.loads(raw.decode('utf-8')); items=payload.get('items')
    if not isinstance(items,list): raise SystemExit('Export does not contain an items array')
    observed=str(payload.get('exportedAt') or now_iso()); archived,sha=preserve_raw(a.target,a.source,raw,observed); folder=ROOT/'data'/a.target; folder.mkdir(parents=True,exist_ok=True); state_path=folder/'state.json'; state=load_json(state_path) if state_path.exists() else initial_state(a.target)
    normalized=[normalize_item(i,observed) for i in items if isinstance(i,dict)]; meta={'sourceFile':archived.relative_to(ROOT).as_posix(),'rawSha256':sha,'exportSchemaVersion':payload.get('schemaVersion'),'exportedAt':observed,'targetAuthor':payload.get('targetAuthor',''),'declaredItemCount':payload.get('itemCount'),'collectionLimit':payload.get('collectionLimit',{})}
    state=apply_snapshot(state,normalized,observed_at=observed,snapshot_meta=meta,complete=a.complete,target_config=config); state_path.write_text(dumps(state),encoding='utf-8'); print(json.dumps(summary(state),indent=2))
    if not a.complete: print('Missing-item detection was NOT run. Use --complete only for full comparable crawls.')
if __name__=='__main__': main()
