from sqlalchemy import String,JSON,ForeignKey
from sqlalchemy.orm import Mapped,mapped_column
from src.config.database import Base
class BackfillBatch(Base):
 __tablename__="backfill_batches"
 id:Mapped[str]=mapped_column(String,primary_key=True)
 name:Mapped[str]=mapped_column(String,unique=True)
 source:Mapped[str]=mapped_column(String)
 times:Mapped[list]=mapped_column(JSON)
 # 预登记曲线：[{curve_id,label}]，顺序即登记顺序
 curves:Mapped[list]=mapped_column(JSON)
 # 已收片段：{segment_id:{segment_id,batch_no,curve_id,start_index,values,received_at}}
 segments:Mapped[dict]=mapped_column(JSON)
 # 每个点的来源：{curve_id:{point_index:[{segment_id,batch_no,value}]}}
 point_sources:Mapped[dict]=mapped_column(JSON)
 # 冲突登记（最近一次被拒绝补传）：null 或 {rejected_at, conflicts:[{curve_id,point_index,existing_value,incoming_value,existing_sources:[...],incoming_segment_id,incoming_batch_no}]}
 conflict:Mapped[dict]=mapped_column(JSON)
 # collecting / published；发布后拒绝补传
 status:Mapped[str]=mapped_column(String)
 # 发布生成的曲线集ID（未发布为 None）
 dataset_id:Mapped[str]=mapped_column(ForeignKey("curve_datasets.id"),nullable=True)
 # 从哪个已发布批次继续归并（可为 None）
 parent_batch_id:Mapped[str]=mapped_column(ForeignKey("backfill_batches.id"),nullable=True)
 created_at:Mapped[str]=mapped_column(String)
 published_at:Mapped[str]=mapped_column(String,nullable=True)
