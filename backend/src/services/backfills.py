import math,re,uuid
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified
from src.models import BackfillBatch,CurveDataset
from src.services.preprocessing import validate_dataset
from src.utils.serialization import serialize
from src.utils.time import now

POINT_COUNT=64
ID_PATTERN=re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,20}')

def _validate_times(times):
 if len(times)!=POINT_COUNT:raise ValueError("时间轴必须恰好64个时间点")
 if not all(isinstance(t,(int,float)) and not isinstance(t,bool) and math.isfinite(t) for t in times):
  raise ValueError("时间必须有限")
 delta=times[1]-times[0]
 if delta<=0 or any(times[i]<=times[i-1] or not math.isclose(times[i]-times[i-1],delta,rel_tol=1e-8,abs_tol=1e-9) for i in range(1,POINT_COUNT)):
  raise ValueError("时间必须严格递增、等距，无重复或缺点；不自动重采样")
 return delta

def _registered_ids(curves):
 ids=[]
 for c in curves:
  cid=c['curve_id']
  if not ID_PATTERN.fullmatch(cid):raise ValueError("曲线ID须为唯一英数短ID："+cid)
  if cid in ids:raise ValueError("曲线ID重复："+cid)
  ids.append(cid)
 return ids

def create(db,payload):
 data=payload.model_dump()
 try:
  _validate_times(data['times']);_registered_ids(data['curves'])
 except ValueError as e:raise HTTPException(422,str(e))
 if db.scalar(select(BackfillBatch).where(BackfillBatch.name==data['name'])):
  raise HTTPException(409,"补传批次名称已存在")
 parent=None
 if data['parent_batch_id']:
  parent=db.get(BackfillBatch,data['parent_batch_id'])
  if not parent:raise HTTPException(404,"来源补传批次不存在")
  if parent.status!='published':raise HTTPException(409,"只能从已发布的曲线集继续归并")
  if parent.times!=data['times']:raise HTTPException(422,"继续归并必须沿用同一64点时间轴")
  parent_ids={c['curve_id'] for c in parent.curves}
  new_ids={c['curve_id'] for c in data['curves']}
  if not (parent_ids & new_ids):raise HTTPException(422,"继续归并的预登记曲线须与来源曲线集有交集")
 # 预先登记曲线与64点时间轴：此时没有任何读数
 item=BackfillBatch(
  id=str(uuid.uuid4()),name=data['name'],source=data['source'],times=data['times'],
  curves=data['curves'],segments={},point_sources={},conflict=None,
  status='collecting',dataset_id=None,parent_batch_id=data['parent_batch_id'],
  created_at=now(),published_at=None)
 db.add(item)
 try:db.commit()
 except IntegrityError:db.rollback();raise HTTPException(409,"补传批次名称已存在")
 return _view(db,item)

def _get_locked(db,batch_id):
 # 行级锁：并发补传/发布串行化，全部规则在同一事务内判定
 item=db.scalar(select(BackfillBatch).where(BackfillBatch.id==batch_id).with_for_update())
 if not item:raise HTTPException(404,"补传批次不存在")
 return item

def receive_segment(db,batch_id,payload):
 seg=payload.model_dump()
 item=_get_locked(db,batch_id)
 if item.status!='collecting':raise HTTPException(409,"批次已发布，发布后拒绝补传")
 registered={c['curve_id'] for c in item.curves}
 if seg['curve_id'] not in registered:raise HTTPException(422,"片段曲线未在批次中预登记："+seg['curve_id'])
 start=seg['start_index'];values=seg['values'];end=start+len(values)
 if end>POINT_COUNT:raise HTTPException(422,f"片段超出64点时间轴：起点{start}，长度{len(values)}")
 if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in values):
  raise HTTPException(422,"片段读数必须全部有限；不补点、不填0")
 segment_id=str(uuid.uuid4())
 # 直接在属性持有的字典上原地变更（不能用 `or {}`，那会得到脱离属性的新字典）
 if not item.point_sources:item.point_sources={}
 if not item.segments:item.segments={}
 point_sources=item.point_sources
 curve_sources=point_sources.setdefault(seg['curve_id'],{})
 # 先做整次校验：异值冲突则整次拒绝，已收数据不变
 conflicts=[]
 for offset,value in enumerate(values):
  idx=start+offset
  existing=curve_sources.get(str(idx))
  if existing:
   prior=existing[-1]['value']
   if not _same_value(prior,value):
    conflicts.append({
     'curve_id':seg['curve_id'],'point_index':idx,
     'existing_value':prior,'incoming_value':value,
     'existing_sources':[s['segment_id'] for s in existing],
     'incoming_segment_id':segment_id,'incoming_batch_no':seg['batch_no']})
 if conflicts:
  # 整次补传拒绝并指出冲突点；不落任何读数，只登记冲突供页面查看
  item.conflict={'rejected_at':now(),'incoming_batch_no':seg['batch_no'],'incoming_segment_id':segment_id,'conflicts':conflicts}
  db.commit()
  raise HTTPException(409,{'message':'补传片段与已收读数异值冲突，整次拒绝，已收数据不变','conflicts':conflicts})
 # 无冲突：乱序、重复、重叠同值都不产生额外读数，只追加来源
 for offset,value in enumerate(values):
  idx=start+offset
  entry={'segment_id':segment_id,'batch_no':seg['batch_no'],'value':value}
  # 首次到达建读数；重复或重叠同值仅追加来源，读数本身不增加
  curve_sources.setdefault(str(idx),[]).append(entry)
 item.segments[segment_id]={'segment_id':segment_id,'batch_no':seg['batch_no'],'curve_id':seg['curve_id'],
  'start_index':start,'values':values,'received_at':now()}
 item.conflict=None
 # JSON 列原地变更需显式标记，否则 SQLAlchemy 不会持久化
 flag_modified(item,'point_sources');flag_modified(item,'segments')
 db.commit()
 return _view(db,item)

def _same_value(a,b):
 # 与 preprocessing 相同的有限浮点比较口径
 return math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-12)

def publish(db,batch_id):
 item=_get_locked(db,batch_id)
 if item.status=='published':
  # 重复发布返回同一曲线集
  dataset=db.get(CurveDataset,item.dataset_id)
  return serialize(dataset)
 missing=_missing_points(item)
 if missing:
  raise HTTPException(409,{'message':'仅全部曲线齐点时可发布，仍有缺点','missing':missing})
 # 组装完整曲线集；每点取值与来源一致（重叠同值）
 curves=[]
 for c in item.curves:
  cid=c['curve_id'];sources=item.point_sources[cid]
  values=[sources[str(i)][-1]['value'] for i in range(POINT_COUNT)]
  curves.append({'curve_id':cid,'label':c['label'],'values':values})
 try:
  validate_dataset(item.times,curves)
 except ValueError as e:
  raise HTTPException(422,str(e))
 name=item.name+'·发布曲线集'
 if db.scalar(select(CurveDataset).where(CurveDataset.name==name)):
  name=name+'·'+item.id[:8]
 dataset=CurveDataset(id=str(uuid.uuid4()),name=name,source=item.source,
  times=list(item.times),curves=curves,created_at=now())
 db.add(dataset);db.flush()
 item.status='published';item.dataset_id=dataset.id;item.published_at=now()
 db.commit()
 return serialize(dataset)

def _missing_points(item):
 missing=[]
 for c in item.curves:
  cid=c['curve_id'];sources=item.point_sources.get(cid,{})
  gaps=[i for i in range(POINT_COUNT) if not sources.get(str(i))]
  if gaps:missing.append({'curve_id':cid,'missing_indexes':gaps})
 return missing

def _view(db,item):
 data=serialize(item)
 # 缺点、冲突及每点来源直接在详情中可见
 data['missing']=_missing_points(item)
 counts={}
 for c in item.curves:
  cid=c['curve_id'];points=(item.point_sources or {}).get(cid,{})
  counts[cid]=sum(1 for i in range(POINT_COUNT) if points.get(str(i)))
 data['received_point_count']=counts
 data['segment_count']=len(item.segments or {})
 return data

def listing(db):
 out=[]
 for item in db.scalars(select(BackfillBatch).order_by(BackfillBatch.created_at.desc())):
  out.append(_view(db,item))
 return out

def detail(db,batch_id):
 item=db.get(BackfillBatch,batch_id)
 if not item:raise HTTPException(404,"补传批次不存在")
 return _view(db,item)
