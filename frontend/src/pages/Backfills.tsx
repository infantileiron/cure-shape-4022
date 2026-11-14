import {useState} from 'react';
import type {Workspace} from '../stores/workspace';
import type {BackfillBatch,BackfillMissing} from '../types/domain';
import * as api from '../api/backfills';
import {useAction} from '../hooks/useAction';
import {Heading} from '../components/common/Heading';
import {Notice} from '../components/common/Notice';
import {Empty} from '../components/common/Empty';
import {BACKFILL_STATUS} from '../constants/enums';
import {num} from '../utils/format';
import {ranges,backfillExample,continueExample} from '../utils/backfill';

const POINTS=64;

function missingMap(missing:BackfillMissing[]):Record<string,Set<number>>{
 const out:Record<string,Set<number>>={};
 for(const m of missing)out[m.curve_id]=new Set(m.missing_indexes);
 return out;
}
function conflictSet(b:BackfillBatch):Set<string>{
 const out=new Set<string>();
 for(const c of b.conflict?.conflicts??[])out.add(c.curve_id+'#'+c.point_index);
 return out;
}

// 64格缺点/收点网格：灰=已收，红虚框=缺点，深色=冲突点；点击查看该点全部来源
function PointGrid({b,curveId,onPick,picked}:{b:BackfillBatch;curveId:string;onPick:(i:number)=>void;picked:string}){
 const miss=missingMap(b.missing)[curveId]??new Set<number>();
 const conflicts=conflictSet(b);
 const sources=b.point_sources[curveId]??{};
 return <div className="point-grid" role="grid" aria-label={`${curveId} 64点收点情况`}>
  {Array.from({length:POINTS},(_,i)=>{
   const key=curveId+'#'+i;
   const state=miss.has(i)?'missing':conflicts.has(key)?'conflict':'filled';
   const multi=(sources[String(i)]?.length??0)>1;
   return <button key={i} type="button" role="gridcell" aria-label={`点${i} ${state==='missing'?'缺点':state==='conflict'?'冲突':'已收'}`}
    className={'pg-cell '+state+(picked===key?' picked':'')+(multi?' multi':'')}
    title={`#${i} · ${state==='missing'?'缺点':state==='conflict'?'异值冲突':(sources[String(i)]?.length??0)+'个来源'}`}
    onClick={()=>onPick(i)}><span>{i}</span>{multi&&<i>·</i>}</button>;
  })}
 </div>;
}

function SourcesPanel({b,curveId,index}:{b:BackfillBatch;curveId:string;index:number|null}){
 if(index===null)return <p className="muted">点击网格中任一点，查看该采样点的全部来源片段与读数。重叠同值会保留每一次补传来源。</p>;
 const sources=b.point_sources[curveId]?.[String(index)]??[];
 const conflict=b.conflict?.conflicts.find(c=>c.curve_id===curveId&&c.point_index===index);
 return <div className="sources-panel">
  <h3>{curveId} · 采样点 #{index}（{num(b.times[index],1)} 分钟）</h3>
  {sources.length===0
   ? <p className="muted">该点尚无任何读数，属于缺点；不补零、不插值。</p>
   : <table><thead><tr><th>来源片段</th><th>补传批次号</th><th>读数</th><th>片段ID（前8位）</th></tr></thead>
     <tbody>{sources.map((s,k)=><tr key={k}><td>第{k+1}次来源</td><td>{s.batch_no}</td><td>{num(s.value)}</td><td className="mono">{s.segment_id.slice(0,8)}</td></tr>)}</tbody></table>}
  {conflict&&<div role="alert" className="notice error">
   异值冲突：已收读数 <b>{num(conflict.existing_value)}</b>（来源 {conflict.existing_sources.map(x=>x.slice(0,8)).join('、')}），
   被拒片段 <b>{conflict.incoming_batch_no}</b> 送来 <b>{num(conflict.incoming_value)}</b>；整次补传已拒绝，已收数据不变。
  </div>}
 </div>;
}

function ConflictPanel({b}:{b:BackfillBatch}){
 if(!b.conflict)return null;
 return <details className="conflict-box" open>
  <summary>最近一次被拒绝的补传（{b.conflict.conflicts.length} 个冲突点 · {b.conflict.rejected_at}）</summary>
  <table><thead><tr><th>曲线</th><th>采样点</th><th>已收读数</th><th>被拒读数</th><th>被拒片段批次号</th></tr></thead>
   <tbody>{b.conflict.conflicts.map((c,k)=><tr key={k}><td>{c.curve_id}</td><td>#{c.point_index}</td><td>{num(c.existing_value)}</td><td>{num(c.incoming_value)}</td><td>{c.incoming_batch_no}</td></tr>)}</tbody></table>
 </details>;
}

function SegmentForm({b,refresh}:{b:BackfillBatch;refresh:()=>Promise<void>}){
 const a=useAction();
 const [batchNo,setBatchNo]=useState('REPLAY-001');
 const [curveId,setCurveId]=useState(b.curves[0]?.curve_id??'');
 const [start,setStart]=useState(0);
 const [text,setText]=useState('');
 const locked=b.status==='published';
 return <section className="form-section">
  <h2>按曲线与采样序号接收片段{locked&&'（批次已发布，拒绝补传）'}</h2>
  <p>片段按 curve_id 与 start_index 归位到64点时间轴；乱序可收、重复不增读数，重叠同值保留全部来源，异值则整次拒绝。</p>
  <form className="form-grid" onSubmit={e=>{e.preventDefault();void a.act(async()=>{
   const values=JSON.parse(text) as number[];
   await api.sendSegment(b.id,{batch_no:batchNo,curve_id:curveId,start_index:start,values});
   await refresh();setText('');
  },'片段已归并；如与已收读数异值会整次拒绝');}}>
   <label>补传批次号<input aria-label="补传批次号" value={batchNo} onChange={e=>setBatchNo(e.target.value)} required/></label>
   <label>曲线<select aria-label="片段曲线" value={curveId} onChange={e=>setCurveId(e.target.value)}>{b.curves.map(c=><option key={c.curve_id} value={c.curve_id}>{c.curve_id} · {c.label}</option>)}</select></label>
   <label>起始采样序号（0-63）<input aria-label="起始采样序号" type="number" min={0} max={63} step={1} value={start} onChange={e=>setStart(Number(e.target.value))}/></label>
   <label>读数 JSON 数组（按序号连续，不得越过63）<textarea aria-label="片段读数JSON" rows={3} placeholder='[12.4, 12.6, 12.9]' value={text} onChange={e=>setText(e.target.value)}/></label>
   <button className="primary" disabled={a.busy||locked}>接收片段</button>
  </form>
  <Notice error={a.error} notice={a.notice}/>
 </section>;
}

function BatchDetail({b,refresh}:{b:BackfillBatch;refresh:()=>Promise<void>}){
 const [pickedCurve,setPickedCurve]=useState(b.curves[0]?.curve_id??'');
 const [pickedIndex,setPickedIndex]=useState<number|null>(null);
 const a=useAction();
 const totalMissing=b.missing.reduce((n,m)=>n+m.missing_indexes.length,0);
 const totalPoints=b.curves.length*POINTS;
 const received=Object.values(b.received_point_count).reduce((n,v)=>n+v,0);
 return <article className="backfill-detail">
  <div className="section-rule"><h2>{b.name}</h2>
   <span className={'status '+(b.status==='published'?'completed':'queued')}>{BACKFILL_STATUS[b.status]}</span></div>
  <div className="policy-strip">
   <span>来源 <b>{b.source}</b></span>
   <span>预登记曲线 <b>{b.curves.length}</b></span>
   <span>已片段 <b>{b.segment_count}</b></span>
   <span>读数点 <b>{received}/{totalPoints}</b></span>
   <span>缺点 <b>{totalMissing}</b></span>
   {b.parent_batch_id&&<span>续自批次 <b className="mono">{b.parent_batch_id.slice(0,8)}</b></span>}
   {b.dataset_id&&<span>发布曲线集 <b className="mono">{b.dataset_id.slice(0,8)}</b></span>}
  </div>
  <ConflictPanel b={b}/>
  <label className="selector">选择曲线查看缺点与每点来源
   <select aria-label="选择曲线" value={pickedCurve} onChange={e=>{setPickedCurve(e.target.value);setPickedIndex(null)}}>
    {b.curves.map(c=><option key={c.curve_id} value={c.curve_id}>{c.curve_id} · {c.label}（已收 {b.received_point_count[c.curve_id]??0}/64）</option>)}
   </select></label>
  <PointGrid b={b} curveId={pickedCurve} picked={pickedCurve+'#'+pickedIndex} onPick={setPickedIndex}/>
  {b.missing.find(m=>m.curve_id===pickedCurve)&&<p className="muted">缺点序号：{ranges(b.missing.find(m=>m.curve_id===pickedCurve)!.missing_indexes)}</p>}
  <SourcesPanel b={b} curveId={pickedCurve} index={pickedIndex}/>
  {b.status==='collecting'
   ? <div className="inline-form">
      <button className="primary" disabled={a.busy} onClick={()=>void a.act(async()=>{await api.publish(b.id);await refresh()},totalMissing?'仍有缺点，不能发布':'已发布为完整曲线集')}>校验齐点并发布曲线集</button>
      <small className="muted">仅全部 {b.curves.length} 条曲线齐点（各64点）时可发布；发布后拒绝一切补传，重复发布返回同一曲线集。</small>
     </div>
   : <p className="notice">批次已发布，可在「曲线样本」页对发布的曲线集冻结归并任务；发布后的补传一律拒绝。</p>}
  <Notice error={a.error} notice={a.notice}/>
  <SegmentForm b={b} refresh={refresh}/>
 </article>;
}

export function Backfills({data,write,refresh}:{data:Workspace;write:boolean;refresh:()=>Promise<void>}){
 const [id,setId]=useState('');
 const [text,setText]=useState(JSON.stringify(backfillExample(),null,2));
 const [parent,setParent]=useState('');
 const a=useAction();
 const published=data.backfills.filter(b=>b.status==='published');
 const current=data.backfills.find(b=>b.id===id)??data.backfills[0];
 return <>
  <Heading index="03 / BACKFILL" title="分段补传，先登记曲线与时间轴。"
   detail="仪器可把同批养护曲线分段、乱序、重复补传：按曲线与采样序号接收片段，异值整次拒绝且已收数据不变，全部曲线齐点方可发布。"/>
  <label className="selector">选择补传批次
   <select aria-label="选择补传批次" value={current?.id||''} onChange={e=>setId(e.target.value)}>
    {data.backfills.map(b=><option key={b.id} value={b.id}>{b.name}（{BACKFILL_STATUS[b.status]}）</option>)}
   </select></label>
  {current?<BatchDetail key={current.id} b={current} refresh={refresh}/>:<Empty>先登记一个补传批次：预登记曲线ID与64点等距时间轴，读数随后按片段陆续到达。</Empty>}
  {write&&<section className="form-section">
   <h2>登记新补传批次</h2>
   <p>预登记 name、source、64个 times 与 curves（仅 curve_id/label，不含读数）。可从已发布批次继续归并，须沿用同一时间轴且曲线有交集。</p>
   <form onSubmit={e=>{e.preventDefault();void a.act(async()=>{
    const payload=JSON.parse(text);
    payload.parent_batch_id=parent||null;
    const created=await api.create(payload);await refresh();setId(created.id);
   },'补传批次已登记，可开始接收片段')}}>
    <label>从已发布曲线集继续归并（可选）
     <select aria-label="来源批次" value={parent} onChange={e=>{
      const pid=e.target.value;setParent(pid);
      const p=data.backfills.find(x=>x.id===pid);
      setText(JSON.stringify(p?continueExample(p,pid):backfillExample(),null,2));
     }}>
      <option value="">全新批次</option>
      {published.map(b=><option key={b.id} value={b.id}>{b.name}</option>)}
     </select></label>
    <label>批次登记 JSON<textarea aria-label="批次登记JSON" rows={8} value={text} onChange={e=>setText(e.target.value)}/></label>
    <button className="primary" disabled={a.busy}>登记补传批次</button>
    <button type="button" onClick={()=>{
     const p=data.backfills.find(x=>x.id===parent);
     setText(JSON.stringify(p?continueExample(p,parent):backfillExample(),null,2));
    }}>恢复示例</button>
   </form>
   <Notice error={a.error} notice={a.notice}/>
  </section>}
 </>;
}
