export const token=()=>localStorage.getItem('cure-token')||'';
function errorMessage(result:{detail?:unknown}):string{
 const d=result?.detail;
 if(typeof d==='string')return d;
 if(d&&typeof d==='object'){
  const o=d as Record<string,unknown>;
  if(typeof o.message==='string'){
   const conflicts=(o.conflicts as Array<Record<string,unknown>>|undefined);
   const missing=(o.missing as Array<Record<string,unknown>>|undefined);
   const extra=conflicts?.length
    ?'；冲突点 '+conflicts.map(c=>`${c.curve_id}#${c.point_index}（${c.existing_value}≠${c.incoming_value}）`).join('、')
    :missing?.length
     ?'；缺点 '+missing.map(m=>`${m.curve_id}: ${(m.missing_indexes as number[]).join(',')}`).join('；')
     :'';
   return o.message+extra;
  }
  return JSON.stringify(d);
 }
 return '请求失败，请重试';
}
export async function request<T>(path:string,data?:unknown):Promise<T>{const r=await fetch('/api'+path,{method:data===undefined?'GET':'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token()},body:data===undefined?undefined:JSON.stringify(data)});const text=await r.text();let result;try{result=JSON.parse(text)}catch{result={detail:text}}if(!r.ok){if(r.status===401&&path!='/auth/login'){localStorage.removeItem('cure-token');window.dispatchEvent(new Event('session-expired'))}throw new Error(errorMessage(result))}return result}
export async function download(id:string){const r=await fetch('/api/reports/'+id+'/csv',{headers:{Authorization:'Bearer '+token()}});if(!r.ok)throw new Error('导出失败，请重试');const u=URL.createObjectURL(await r.blob());const a=document.createElement('a');a.href=u;a.download='tanyuan-shape.csv';a.click();URL.revokeObjectURL(u)}
