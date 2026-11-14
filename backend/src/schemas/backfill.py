from pydantic import BaseModel,Field,ConfigDict
class BackfillCurveInput(BaseModel):
 model_config=ConfigDict(extra='forbid')
 curve_id:str=Field(min_length=1,max_length=21)
 label:str=Field(min_length=1,max_length=80)
class BackfillBatchInput(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 name:str=Field(min_length=2,max_length=120)
 source:str=Field(min_length=2,max_length=120)
 times:list[float]=Field(min_length=64,max_length=64)
 curves:list[BackfillCurveInput]=Field(min_length=2,max_length=64)
 # 从已发布批次继续归并时传入；为 None 表示全新批次
 parent_batch_id:str|None=None
class SegmentInput(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 # 补传批次号，仪器侧分段补传的同批标识；用于来源追溯
 batch_no:str=Field(min_length=1,max_length=80)
 curve_id:str=Field(min_length=1,max_length=21)
 # 该片段第一个采样点在64点时间轴上的序号（0..63）
 start_index:int=Field(ge=0,le=63)
 values:list[float]=Field(min_length=1,max_length=64)
