"""补传批次规则集成测试：独立目录，用 SQLite 内存库跑真实 SQLAlchemy 模型与服务。
运行：python3 -I test_backfill.py
"""
import os,sys,threading,concurrent.futures
sys.path.insert(0,'/home/node/.local/lib/python3.11/site-packages')
sys.path.insert(0,'/workspace/backend')
os.environ['DATABASE_URL']='sqlite+pysqlite:///:memory:'
os.environ['SEED_DEMO']='false'

# 单连接内存库（StaticPool 保证各 Session 共享同一内存库）；
# with_for_update 在 sqlite 上是 no-op，并发测试用应用级互斥串行验证语义，PG 上由行锁保证
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import src.config.database as dbmod
engine=create_engine('sqlite+pysqlite:///:memory:',
 connect_args={'check_same_thread':False},
 poolclass=StaticPool)
dbmod.engine=engine
dbmod.Session=sessionmaker(bind=engine,expire_on_commit=False)
from src.config.database import Base,Session
import src.models
from src.models import BackfillBatch,CurveDataset
Base.metadata.create_all(engine)

from src.schemas.backfill import BackfillBatchInput,SegmentInput
from src.services import backfills as svc
from fastapi import HTTPException

TIMES=[float(i*2) for i in range(64)]
def curves(n):return [{'curve_id':f'C{k+1:02}','label':f'曲线{k+1}'} for k in range(n)]
def batch_input(name,parent=None,n=3):
 return BackfillBatchInput(name=name,source='instrument-replay.json',times=TIMES,curves=curves(n),parent_batch_id=parent)
def seg(batch_no,cid,start,values):return SegmentInput(batch_no=batch_no,curve_id=cid,start_index=start,values=values)

passed=[];failed=[]
def check(name,cond,detail=''):
 (passed if cond else failed).append(name)
 print(('PASS' if cond else 'FAIL'),name,detail)

def expect_http(fn,status=None):
 try:fn()
 except HTTPException as e:
  if status and e.status_code!=status:raise AssertionError(f'状态码期望{status}实际{e.status_code}: {e.detail}')
  return e
 raise AssertionError('预期 HTTPException 未抛出')

# 1. 预登记：无读数、64点时间轴
with Session() as db:
 b=svc.create(db,batch_input('批次A'))
 bid=b['id']
 check('预登记状态为collecting',b['status']=='collecting')
 check('预登记无片段',b['segment_count']==0)
 check('预登记每曲线缺64点',all(m['missing_indexes']==list(range(64)) for m in b['missing']))
 check('预登记时间轴64点',len(b['times'])==64)

# 2. 时间轴校验
with Session() as db:
 bad=BackfillBatchInput(name='坏时间轴',source='x.json',times=[1.0]*64,curves=curves(2))
 expect_http(lambda:svc.create(db,bad),422)
 bad2=BackfillBatchInput(name='坏曲线ID',source='x.json',times=TIMES,
   curves=[{'curve_id':'1bad','label':'x'},{'curve_id':'OK2','label':'y'}])
 expect_http(lambda:svc.create(db,bad2),422)
 dup=BackfillBatchInput(name='重复ID',source='x.json',times=TIMES,
   curves=[{'curve_id':'OK1','label':'x'},{'curve_id':'OK1','label':'y'}])
 expect_http(lambda:svc.create(db,dup),422)

# 3. 乱序片段接收：先发后半段，再发前半段
with Session() as db:
 svc.receive_segment(db,bid,seg('B01','C01',32,[100.0]*32))
 r=svc.detail(db,bid)
 check('乱序：先收32-63点',r['received_point_count']['C01']==32)
 check('乱序：缺点为0-31',r['missing'][0]['missing_indexes']==list(range(32)))
 svc.receive_segment(db,bid,seg('B02','C01',0,[50.0]*32))
 r=svc.detail(db,bid)
 check('乱序：补齐后C01齐点',r['received_point_count']['C01']==64)
 check('齐点曲线不再出现在missing',all(m['curve_id']!='C01' for m in r['missing']))

# 4. 重复片段：不增加读数，来源保留
with Session() as db:
 before=svc.detail(db,bid)
 svc.receive_segment(db,bid,seg('B02','C01',0,[50.0]*32))  # 完全重复
 after=svc.detail(db,bid)
 check('重复片段不增加读点数',after['received_point_count']['C01']==before['received_point_count']['C01']==64)
 check('重复片段登记为新segment',after['segment_count']==before['segment_count']+1)
 src0=after['point_sources']['C01']['0']
 check('同点保留全部来源(2条)',len(src0)==2 and {s['batch_no'] for s in src0}=={'B02'})

# 5. 重叠同值：保留全部来源；异值冲突整次拒绝
with Session() as db:
 # 点30/31已为50，送入100 -> 异值冲突（同一片段内32/33的100同值也不会落库，整次拒绝）
 expect_http(lambda:svc.receive_segment(db,bid,seg('B03','C01',30,[100.0,100.0,100.0,100.0])),409)
 r=svc.detail(db,bid)
 check('异值冲突已登记',r['conflict'] is not None and len(r['conflict']['conflicts'])==2)
 check('冲突点定位正确',{c['point_index'] for c in r['conflict']['conflicts']}=={30,31})
 check('冲突报告含双方值',r['conflict']['conflicts'][0]['existing_value']==50.0 and r['conflict']['conflicts'][0]['incoming_value']==100.0)
 check('冲突报告含双方来源',len(r['conflict']['conflicts'][0]['existing_sources'])>=1)
 check('整次拒绝：已收数据不变',r['received_point_count']['C01']==64)
 check('整次拒绝：无新segment',r['segment_count']==3)  # B01、B02、B02重复；B03被整次拒绝
 # 同值重叠：点32-33已为100，再来100
 svc.receive_segment(db,bid,seg('B04','C01',32,[100.0,100.0]))
 r=svc.detail(db,bid)
 check('重叠同值不增加读数',r['received_point_count']['C01']==64)
 check('重叠同值保留来源',len(r['point_sources']['C01']['32'])==2)
 check('成功补传清除冲突标记',r['conflict'] is None)

# 6. 未登记曲线 / 越界片段拒绝
with Session() as db:
 expect_http(lambda:svc.receive_segment(db,bid,seg('B9','XX9',0,[1.0])),422)
 expect_http(lambda:svc.receive_segment(db,bid,seg('B9','C01',63,[1.0,2.0])),422)
 # start_index=64 在 schema 层即被拒绝（le=63）
 try:
  seg('B9','C01',64,[1.0]);raise AssertionError('start_index=64 应被schema拒绝')
 except Exception as ex:
  assert '64' in str(ex) or 'less_than_equal' in str(ex)
 print('PASS 起点越界在schema层拒绝')

# 7. 缺点时不可发布
with Session() as db:
 e=expect_http(lambda:svc.publish(db,bid),409)
 check('缺点发布被拒并指出缺点',any(m['curve_id']=='C02' for m in e.detail['missing']))

# 8. 补齐全部曲线后发布，生成完整曲线集
with Session() as db:
 for cid in ('C02','C03'):
  svc.receive_segment(db,bid,seg('B10',cid,0,[float(i) for i in range(64)]))
 ds=svc.publish(db,bid)
 check('发布生成曲线集',ds['curves'][0]['curve_id']=='C01' and len(ds['curves'])==3)
 check('发布曲线每点64值',all(len(c['values'])==64 for c in ds['curves']))
 check('发布取值与来源一致',ds['curves'][0]['values'][0]==50.0 and ds['curves'][0]['values'][63]==100.0)
 r=svc.detail(db,bid)
 check('批次状态published',r['status']=='published' and r['dataset_id']==ds['id'])

# 9. 发布后拒绝补传
with Session() as db:
 expect_http(lambda:svc.receive_segment(db,bid,seg('B11','C01',0,[9.0])),409)

# 10. 重复发布返回同一曲线集
with Session() as db:
 ds2=svc.publish(db,bid)
 check('重复发布返回同一曲线集',ds2['id']==ds['id'])

# 11. 从发布的曲线集继续归并
with Session() as db:
 cont=svc.create(db,batch_input('批次A·续',parent=bid,n=3))
 cid2=cont['id']
 check('续批记录parent',cont['parent_batch_id']==bid)
 # 时间轴不一致拒绝
 bad=BackfillBatchInput(name='续批坏轴',source='xx',times=[float(i*3) for i in range(64)],curves=curves(2),parent_batch_id=bid)
 expect_http(lambda:svc.create(db,bad),422)
 # 无交集拒绝
 far=BackfillBatchInput(name='续批无交集',source='xx',times=TIMES,
   curves=[{'curve_id':'Z01','label':'z'},{'curve_id':'Z02','label':'z'}],parent_batch_id=bid)
 expect_http(lambda:svc.create(db,far),422)
 # 未发布批次不能作为来源
 fresh=svc.create(db,batch_input('未发布批',n=2))
 expect_http(lambda:svc.create(db,batch_input('想接续',parent=fresh['id'],n=2)),409)

# 12. 续批独立收集、独立发布
with Session() as db:
 for c in curves(3):
  svc.receive_segment(db,cid2,seg('C01',c['curve_id'],0,[7.0]*64))
 ds3=svc.publish(db,cid2)
 check('续批发布为新曲线集',ds3['id']!=ds['id'] and all(v==7.0 for v in ds3['curves'][0]['values']))

# 13. 并发补传/发布串行化：多线程同时补同一批次，结果与顺序无关
with Session() as db:
 pb=svc.create(db,batch_input('并发批',n=2))
 pid=pb['id']
lock=threading.Lock()  # sqlite 写串行；服务内 with_for_update 在 PG 上提供行锁
def worker(args):
 cid,start,vals=args
 with Session() as db:
  with lock:
   svc.receive_segment(db,pid,seg('P',cid,start,vals))
 # 独立连接验证服务可重复调用
tasks=[]
for cid in ('C01','C02'):
 # 每曲线拆4个乱序片段，共8任务，打乱
 bounds=[(48,[float(48+i) for i in range(16)]),(0,[float(i) for i in range(16)]),
         (32,[float(32+i) for i in range(16)]),(16,[float(16+i) for i in range(16)])]
 for s,v in bounds:tasks.append((cid,s,v))
import random;random.Random(7).shuffle(tasks)
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
 list(ex.map(worker,tasks))
with Session() as db:
 r=svc.detail(db,pid)
 check('并发后全部齐点',all(c not in [m['curve_id'] for m in r['missing']] for c in ('C01','C02')))
 ds4=svc.publish(db,pid)
 check('并发结果与到达顺序无关',ds4['curves'][0]['values']==[float(i) for i in range(64)])

# 14. 并发异值冲突：整次拒绝，其余片段不受影响
with Session() as db:
 cb=svc.create(db,batch_input('冲突并发批',n=2))
 xid=cb['id']
 svc.receive_segment(db,xid,seg('X','C01',0,[1.0]*10))
def conflicker():
 with Session() as db:
  with lock:
   expect_http(lambda:svc.receive_segment(db,xid,seg('Y','C01',0,[2.0]*10)),409)
conflicker()
with Session() as db:
 r=svc.detail(db,xid)
 check('并发冲突后原值不变',all(s['value']==1.0 for s in r['point_sources']['C01']['0']))
 check('冲突片段未入库',all(seg_['batch_no']=='X' for seg_ in r['segments'].values()))

# 15. 名称唯一
with Session() as db:
 expect_http(lambda:svc.create(db,batch_input('批次A')),409)

print(f'\n{len(passed)} passed, {len(failed)} failed')
if failed:
 print('FAILED:',failed);sys.exit(1)
