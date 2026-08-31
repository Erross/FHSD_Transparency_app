"""Record a direct/manual visibility verification for one entity."""
import argparse
from pathlib import Path
from .core import now_iso
from .io_utils import read_json,write_json_gz
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser(); p.add_argument('--target',required=True); p.add_argument('--entity',required=True); g=p.add_mutually_exclusive_group(required=True); g.add_argument('--confirm-unavailable',action='store_true'); g.add_argument('--confirm-visible',action='store_true'); p.add_argument('--evidence-url',default=''); p.add_argument('--note',default=''); a=p.parse_args(); path=ROOT/'data'/a.target/'state.json.gz'
    if not path.exists(): raise SystemExit('Target has no ingested state')
    state=read_json(path); e=state.get('entities',{}).get(a.entity)
    if e is None: raise SystemExit(f'Unknown entity: {a.entity}')
    at=now_iso(); before=e.get('status','active'); kind='confirmed_unavailable' if a.confirm_unavailable else 'directly_confirmed_visible'; e['status']='confirmed_unavailable' if a.confirm_unavailable else ('reappeared' if before!='active' else 'active')
    if a.confirm_visible: e['missingCount']=0; e['lastSeen']=at
    state.setdefault('events',[]).append({'type':kind,'observedAt':at,'entityId':a.entity,'itemType':e.get('itemType',''),'author':e.get('author',''),'parentId':e.get('parentId',''),'permalink':e.get('permalink',''),'priorStatus':before,'evidenceUrl':a.evidence_url,'note':a.note,'verification':'manual_or_direct_check'}); write_json_gz(path,state)
if __name__=='__main__': main()
