import unittest
from scripts.core import apply_snapshot,initial_state,normalize_item
CONFIG={'crawl':{'requiresCompleteSnapshotForMissing':True,'missingRecheckThreshold':2,'bulkMissingAbsoluteThreshold':2,'bulkMissingRatioThreshold':.25}}
def post(pid,text): return {'itemType':'post','author':'School Watchlist','postId':pid,'bodyText':text,'permalink':f'https://facebook.example/post/{pid}'}
def comment(cid,text,pid='p1'): return {'itemType':'comment','author':'Commenter','commentId':cid,'postId':pid,'bodyText':text,'permalink':f'https://facebook.example/post/{pid}?comment_id={cid}'}
class Tests(unittest.TestCase):
 def apply(self,state,items,t,complete=False): return apply_snapshot(state,[normalize_item(i,t) for i in items],observed_at=t,snapshot_meta={'rawSha256':t},complete=complete,target_config=CONFIG)
 def test_identity(self):
  s=self.apply(initial_state('school-watchlist'),[post('p1','hello'),comment('c1','world')],'t1'); self.assertIn('post:p1',s['entities']); self.assertIn('comment:c1',s['entities']); self.assertEqual('post:p1',s['entities']['comment:c1']['parentId'])
 def test_edit(self):
  s=self.apply(initial_state('x'),[post('p1','first')],'t1'); s=self.apply(s,[post('p1','second')],'t2'); self.assertEqual(2,len(s['entities']['post:p1']['versions'])); self.assertEqual('edited',s['events'][-1]['type'])
 def test_incomplete_safe(self):
  s=self.apply(initial_state('x'),[post('p1','1'),post('p2','2')],'t1',True); s=self.apply(s,[post('p1','1')],'t2',False); self.assertEqual('active',s['entities']['post:p2']['status'])
 def test_missing_reappear(self):
  s=self.apply(initial_state('x'),[post('p1','1'),post('p2','2')],'t1',True); s=self.apply(s,[post('p1','1')],'t2',True); self.assertEqual('missing_once',s['entities']['post:p2']['status']); s=self.apply(s,[post('p1','1')],'t3',True); self.assertEqual('missing_recheck',s['entities']['post:p2']['status']); s=self.apply(s,[post('p1','1'),post('p2','2')],'t4',True); self.assertEqual('reappeared',s['entities']['post:p2']['status'])
 def test_bulk_neutral(self):
  s=self.apply(initial_state('x'),[post('p1','1'),comment('c1','a'),comment('c2','b'),comment('c3','c')],'t1',True); s=self.apply(s,[post('p1','1')],'t2',True); bulk=[e for e in s['events'] if e['type']=='bulk_missing']; self.assertEqual(1,len(bulk)); self.assertIn('causation is not attributed',bulk[0]['note'])
if __name__=='__main__': unittest.main()
