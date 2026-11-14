// 把连续序号压缩成区间，便于缺点展示：[0,1,2,5,7,8] -> "0-2、5、7-8"
export function ranges(indexes:number[]):string{
 if(!indexes.length)return '';
 const parts:string[]=[];let start=indexes[0],prev=indexes[0];
 for(let i=1;i<=indexes.length;i++){
  const cur=indexes[i];
  if(cur===prev+1){prev=cur;continue}
  parts.push(start===prev?String(start):`${start}-${prev}`);
  if(i<indexes.length){start=cur;prev=cur}
 }
 return parts.join('、');
}
// 生成补传批次示例：预登记两条曲线与64点时间轴，不含读数
export function backfillExample(parent?:string){
 const times=Array.from({length:64},(_,i)=>i*2);
 return {name:'新养护样·分段补传',source:'tanyuan_replay_cure.json',times,
  curves:[{curve_id:'NEW-1',label:'模拟新试件1'},{curve_id:'NEW-2',label:'模拟新试件2'}],
  parent_batch_id:parent||null};
}
// 从已发布批次继续归并的示例：沿用同一时间轴，保留一条来源曲线保证交集，另加一条新曲线
export function continueExample(parent:{times:number[];curves:{curve_id:string;label:string}[]},parentId:string){
 const kept=parent.curves[0];
 return {name:'新养护样·续批归并',source:'tanyuan_replay_cure_next.json',times:parent.times,
  curves:[{curve_id:kept.curve_id,label:kept.label},{curve_id:'NEW-9',label:'续批新增试件9'}],
  parent_batch_id:parentId};
}
