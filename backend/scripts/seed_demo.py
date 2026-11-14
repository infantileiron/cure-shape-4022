import math,random,json
from sqlalchemy import select,func
from src.config.database import Base,engine,Session
from src.models import User,CurveDataset,AlignmentPolicy,ShapeStudy,ShapeRun,ClusterReview,Report,BackfillBatch
from src.services.analysis import analyze
from src.services import backfills as backfill_service
from src.schemas.backfill import BackfillBatchInput,SegmentInput
from src.utils.security import hash_password
from src.utils.time import now
from src.utils.serialization import serialize

def seed():
 Base.metadata.create_all(engine)
 with Session() as db:
  for role in ('admin','analyst','viewer'):
   if not db.get(User,role):db.add(User(id=role,email=role+'@tanyuan.demo',password=hash_password('Curve2026!'),role=role))
  rng=random.Random(2403);times=[float(i*2) for i in range(64)];curves=[]
  for k in range(48):
   group=k//12;shift=(k%4-1.5)*2;amplitude=72+group*5+(k%3)*2;center=[42,64,48,56][group]+shift;slope=[.12,.09,.18,.105][group]
   values=[amplitude/(1+math.exp(-slope*(t-center)))+8+math.sin(t/12)*.35+rng.gauss(0,.2) for t in times]
   if group==3:values[22+k%5]+=18
   curves.append({'curve_id':f'TY-{k+1:02}','label':f'模拟配方{group+1}·养护件{k+1:02}','values':[round(v,6) for v in values]})
  if not db.get(CurveDataset,'demo-data'):db.add(CurveDataset(id='demo-data',name='滩原·48条固化养护曲线',source='tanyuan_cure_20261112.json',times=times,curves=curves,created_at=now()));db.flush()
  for id,name,mode,w,t in [('demo-policy','每曲线标准化·窗口6·阈值0.16','zscore',6,.16),('demo-raw','原始量级·窗口6·阈值4','raw',6,4)]:
   if not db.get(AlignmentPolicy,id):db.add(AlignmentPolicy(id=id,name=name,normalization=mode,window=w,threshold=t,created_at=now()))
  db.flush()
  if not db.get(ShapeStudy,'demo-study'):
   snapshot={'dataset':serialize(db.get(CurveDataset,'demo-data')),'policy':serialize(db.get(AlignmentPolicy,'demo-policy'))}
   db.add(ShapeStudy(id='demo-study',name='48件养护样·形态归并初审',dataset_id='demo-data',policy_id='demo-policy',snapshot=snapshot,created_at=now()))
  db.flush()
  if not db.get(ShapeRun,'demo-run'):db.add(ShapeRun(id='demo-run',study_id='demo-study',status='completed',result=analyze(db.get(ShapeStudy,'demo-study').snapshot),error='',created_at=now()));db.flush()
  if not db.get(ClusterReview,'demo-review'):
   clusters=db.get(ShapeRun,'demo-run').result['tree']['clusters'];names=[{'cluster_id':c['cluster_id'],'name':('缓升固化' if i==0 else '延迟上升' if i==1 else '尖峰待核' if i==2 else '曲线族')+'·'+c['cluster_id']} for i,c in enumerate(clusters)]
   db.add(ClusterReview(id='demo-review',run_id='demo-run',version=1,names=names,note='以完整路径、距离矩阵和complete-link树复核；形态簇不是强度或质量等级，尖峰与时移需回到模拟原始读数解释。',decision='accepted',author='analyst@tanyuan.demo',created_at=now()));db.flush()
  if not db.get(Report,'demo-report'):db.add(Report(id='demo-report',run_id='demo-run',review_id='demo-review',title='滩原养护样·形态归并复核稿',published_by='admin@tanyuan.demo',created_at=now()))
  db.flush()
  _seed_backfills(db,times)
  db.commit();return {m.__tablename__:db.scalar(select(func.count()).select_from(m)) for m in (User,CurveDataset,AlignmentPolicy,ShapeStudy,ShapeRun,ClusterReview,Report,BackfillBatch)}

def _seed_backfills(db,times):
 # 幂等：按自然名称判断，已存在则不覆盖用户补传
 if not db.scalar(select(BackfillBatch).where(BackfillBatch.name=='仪器分段补传·收数中演示')):
  b=backfill_service.create(db,BackfillBatchInput(
   name='仪器分段补传·收数中演示',source='tanyuan_replay_cure_20261114.json',times=times,
   curves=[{'curve_id':'BF-01','label':'补传演示·养护件1'},{'curve_id':'BF-02','label':'补传演示·养护件2'},{'curve_id':'BF-03','label':'补传演示·养护件3'}]))
  bid=b['id']
  base=[round(10+60/(1+math.exp(-.11*(t-44))),4) for t in times]
  # 乱序：先到后半段，再到前半段；再重复前半段（同值，保留来源不增读数）
  backfill_service.receive_segment(db,bid,SegmentInput(batch_no='REPLAY-01',curve_id='BF-01',start_index=32,values=base[32:]))
  backfill_service.receive_segment(db,bid,SegmentInput(batch_no='REPLAY-02',curve_id='BF-01',start_index=0,values=base[:32]))
  backfill_service.receive_segment(db,bid,SegmentInput(batch_no='REPLAY-03',curve_id='BF-01',start_index=0,values=base[:32]))
  # BF-02 仅收前40点，保留缺点；BF-03 完全未收
  backfill_service.receive_segment(db,bid,SegmentInput(batch_no='REPLAY-01',curve_id='BF-02',start_index=0,values=[v+2 for v in base[:40]]))
  # 异值补传整次拒绝，留下冲突记录，已收数据不变
  try:backfill_service.receive_segment(db,bid,SegmentInput(batch_no='REPLAY-BAD',curve_id='BF-01',start_index=0,values=[base[0]+9.9]))
  except Exception:pass
 # 齐点并发布的完整演示，以及从它继续归并的续批
 if not db.scalar(select(BackfillBatch).where(BackfillBatch.name=='仪器分段补传·齐点发布演示')):
  p=backfill_service.create(db,BackfillBatchInput(
   name='仪器分段补传·齐点发布演示',source='tanyuan_replay_cure_20261113.json',times=times,
   curves=[{'curve_id':'BF-A1','label':'补传齐点·养护件1'},{'curve_id':'BF-A2','label':'补传齐点·养护件2'}]))
  pid=p['id']
  vals1=[round(12+70/(1+math.exp(-.12*(t-50))),4) for t in times]
  vals2=[round(9+64/(1+math.exp(-.09*(t-62))),4) for t in times]
  # 每曲线拆成4个乱序片段
  for cid,vals in (('BF-A1',vals1),('BF-A2',vals2)):
   for s in (48,0,32,16):
    backfill_service.receive_segment(db,pid,SegmentInput(batch_no='FULL-01',curve_id=cid,start_index=s,values=vals[s:s+16]))
  backfill_service.publish(db,pid)
  backfill_service.create(db,BackfillBatchInput(
   name='仪器分段补传·续批演示',source='tanyuan_replay_cure_20261114b.json',times=times,
   curves=[{'curve_id':'BF-A1','label':'补传齐点·养护件1'},{'curve_id':'BF-A3','label':'续批新增·养护件3'}],
   parent_batch_id=pid))
if __name__=='__main__':print(json.dumps(seed(),ensure_ascii=False))
