"""Build static JSON indexes consumed by the archive website."""
import json
from pathlib import Path
from .core import dumps,initial_state,summary
ROOT=Path(__file__).resolve().parents[1]
def read(path): return json.loads(path.read_text(encoding='utf-8'))
def main():
    out=ROOT/'site'/'data'; target_out=out/'targets'; target_out.mkdir(parents=True,exist_ok=True); catalog=[]
    for path in sorted((ROOT/'targets').glob('*/target.json')):
        cfg=read(path); tid=cfg['id']; state_path=ROOT/'data'/tid/'state.json'; state=read(state_path) if state_path.exists() else initial_state(tid); entities=sorted(state.get('entities',{}).values(),key=lambda e:(e.get('lastSeen',''),e.get('firstSeen','')),reverse=True); events=sorted(state.get('events',[]),key=lambda e:e.get('observedAt',''),reverse=True); snaps=sorted(state.get('snapshots',[]),key=lambda s:s.get('observedAt',''),reverse=True); public={'target':cfg,'summary':summary(state),'entities':entities,'events':events,'snapshots':snaps}; (target_out/f'{tid}.json').write_text(dumps(public),encoding='utf-8'); catalog.append({'id':tid,'displayName':cfg['displayName'],'description':cfg.get('description',''),'platform':cfg.get('platform',''),'sourceUrls':cfg.get('sourceUrls',[]),'summary':public['summary'],'latestSnapshot':snaps[0].get('observedAt','') if snaps else ''})
    (out/'catalog.json').write_text(dumps({'targets':catalog}),encoding='utf-8'); print(f'Built site indexes for {len(catalog)} target(s)')
if __name__=='__main__': main()
