"""Core normalization and diff logic for the public archive."""
from __future__ import annotations
import hashlib, json, re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

STATE_SCHEMA_VERSION = 1

def now_iso(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def normalize_space(value): return re.sub(r'\s+', ' ', str(value or '')).strip()
def digest(value, length=24): return hashlib.sha256(value.encode('utf-8')).hexdigest()[:length]

def _id_from_permalink(url, key):
    if not url: return ''
    try:
        values = parse_qs(urlparse(url).query).get(key, [])
        return values[0] if values else ''
    except ValueError: return ''

def resolve_post_id(item):
    post_id = normalize_space(item.get('postId') or item.get('storyFbid'))
    if post_id: return post_id
    for candidate in (item.get('parentPostPermalink'), item.get('permalink')):
        candidate = normalize_space(candidate)
        for key in ('story_fbid','fbid'):
            post_id = _id_from_permalink(candidate, key)
            if post_id: return post_id
    return ''

def entity_id(item):
    item_type = normalize_space(item.get('itemType') or 'item').lower()
    if item_type == 'post':
        post_id = resolve_post_id(item)
        if post_id: return f'post:{post_id}'
        permalink = normalize_space(item.get('permalink') or item.get('parentPostPermalink'))
        if permalink: return f'post:url:{digest(permalink)}'
    else:
        comment_id = normalize_space(item.get('commentId') or item.get('replyCommentId'))
        if comment_id: return f'comment:{comment_id}'
        permalink = normalize_space(item.get('permalink'))
        if permalink and ('comment_id=' in permalink or 'reply_comment_id=' in permalink): return f'comment:url:{digest(permalink)}'
    source_key = normalize_space(item.get('entityKey'))
    if source_key: return f'{item_type}:source:{digest(source_key)}'
    fp='|'.join([item_type,normalize_space(item.get('author')),normalize_space(item.get('timestampExact') or item.get('timestampText')),normalize_space(item.get('parentPostPermalink')),normalize_space(item.get('bodyText') or item.get('text'))])
    return f'{item_type}:fp:{digest(fp)}'

def parent_entity_id(item):
    if normalize_space(item.get('itemType')).lower() == 'post': return ''
    post_id = resolve_post_id(item)
    if post_id: return f'post:{post_id}'
    link = normalize_space(item.get('parentPostPermalink'))
    return f'post:url:{digest(link)}' if link else ''

def normalize_item(item, observed_at):
    text = normalize_space(item.get('bodyText') or item.get('text'))
    return {'id':entity_id(item),'itemType':normalize_space(item.get('itemType') or 'item').lower(),'author':normalize_space(item.get('author')),'text':text,'textHash':digest(text,64),'timestampText':normalize_space(item.get('timestampText')),'timestampExact':normalize_space(item.get('timestampExact')),'permalink':normalize_space(item.get('permalink')),'parentPostPermalink':normalize_space(item.get('parentPostPermalink')),'parentId':parent_entity_id(item),'postId':resolve_post_id(item),'commentId':normalize_space(item.get('commentId') or item.get('replyCommentId')),'parentCommentId':normalize_space(item.get('parentCommentId')),'capturedAt':normalize_space(item.get('capturedAt')) or observed_at,'rawEntityKey':normalize_space(item.get('entityKey')),'rawId':normalize_space(item.get('id'))}

def initial_state(target_id): return {'schemaVersion':STATE_SCHEMA_VERSION,'targetId':target_id,'entities':{},'events':[],'snapshots':[]}
def _version(r,t): return {'text':r['text'],'textHash':r['textHash'],'firstSeen':t,'lastSeen':t,'timestampText':r.get('timestampText',''),'timestampExact':r.get('timestampExact',''),'permalink':r.get('permalink','')}
def _event(kind,t,r,**extra):
    e={'type':kind,'observedAt':t,'entityId':r.get('id',''),'itemType':r.get('itemType',''),'author':r.get('author',''),'parentId':r.get('parentId',''),'permalink':r.get('permalink','')}; e.update(extra); return e

def _richer(a,b):
    fields=('text','permalink','timestampExact','timestampText','author','commentId')
    sa=sum(bool(a.get(k)) for k in fields)+len(a.get('text',''))/10000; sb=sum(bool(b.get(k)) for k in fields)+len(b.get('text',''))/10000
    return b if sb>sa else a

def apply_snapshot(state, records:Iterable[dict[str,Any]], *, observed_at, snapshot_meta, complete, target_config):
    out=deepcopy(state); entities=out.setdefault('entities',{}); events=out.setdefault('events',[]); current={}; input_count=0
    for r in records:
        input_count+=1; current[r['id']] = _richer(current[r['id']],r) if r['id'] in current else r
    seen=set(current); prior=set(entities)
    for rid,r in current.items():
        old=entities.get(rid)
        if old is None:
            entities[rid]={**r,'firstSeen':observed_at,'lastSeen':observed_at,'status':'active','missingCount':0,'versions':[_version(r,observed_at)],'observationCount':1}; events.append(_event('new',observed_at,r,text=r['text'])); continue
        prior_status=old.get('status','active')
        if prior_status in {'missing_once','missing_recheck','confirmed_unavailable'}:
            old['status']='reappeared'; events.append(_event('reappeared',observed_at,r,text=r['text'],priorStatus=prior_status))
        else: old['status']='active'
        versions=old.setdefault('versions',[])
        if not versions or versions[-1].get('textHash')!=r['textHash']:
            before=versions[-1]['text'] if versions else ''; versions.append(_version(r,observed_at)); events.append(_event('edited',observed_at,r,beforeText=before,afterText=r['text']))
        else: versions[-1]['lastSeen']=observed_at
        for k,v in r.items():
            if v not in (None,'') or not old.get(k): old[k]=v
        old['lastSeen']=observed_at; old['missingCount']=0; old['observationCount']=int(old.get('observationCount',0))+1
    cfg=target_config.get('crawl',{}); allow_missing=bool(complete); threshold=max(1,int(cfg.get('missingRecheckThreshold',2)))
    if allow_missing:
        newly_absent=[]
        for rid in sorted(prior-seen):
            old=entities[rid]
            if old.get('status')=='confirmed_unavailable': old['missingCount']=int(old.get('missingCount',0))+1; continue
            count=int(old.get('missingCount',0))+1; old['missingCount']=count; before=old.get('status','active'); after='missing_once' if count==1 else 'missing_recheck'; old['status']=after
            if before!=after: events.append(_event(after,observed_at,{**old,'id':rid},lastSeen=old.get('lastSeen',''),missingCount=count,text=old.get('text','')))
            if count==1: newly_absent.append(old)
        absolute=max(1,int(cfg.get('bulkMissingAbsoluteThreshold',5))); ratio=float(cfg.get('bulkMissingRatioThreshold',.1)); total=max(1,len(prior))
        if len(newly_absent)>=absolute and len(newly_absent)/total>=ratio:
            events.append({'type':'bulk_missing','observedAt':observed_at,'count':len(newly_absent),'priorEntityCount':len(prior),'ratio':round(len(newly_absent)/total,4),'entityIds':[e['id'] for e in newly_absent],'note':'Previously observed entities were absent from this complete snapshot; causation is not attributed.'})
    out.setdefault('snapshots',[]).append({**snapshot_meta,'observedAt':observed_at,'complete':bool(complete),'inputItemCount':input_count,'uniqueEntityCount':len(current),'duplicateEntityCount':input_count-len(current),'missingDetectionApplied':allow_missing})
    return out

def summary(state):
    es=list(state.get('entities',{}).values()); ev=state.get('events',[])
    return {'entities':len(es),'posts':sum(e.get('itemType')=='post' for e in es),'comments':sum(e.get('itemType')!='post' for e in es),'active':sum(e.get('status') in {'active','reappeared'} for e in es),'missing':sum(e.get('status') in {'missing_once','missing_recheck'} for e in es),'confirmedUnavailable':sum(e.get('status')=='confirmed_unavailable' for e in es),'editedEntities':sum(len(e.get('versions',[]))>1 for e in es),'events':len(ev),'snapshots':len(state.get('snapshots',[]))}
def dumps(data): return json.dumps(data,indent=2,ensure_ascii=False)+'\n'
