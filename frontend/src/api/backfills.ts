import {request} from './client';
import type {BackfillBatch,Dataset} from '../types/domain';
export const list=()=>request<BackfillBatch[]>('/backfills');
export const create=(data:unknown)=>request<BackfillBatch>('/backfills',data);
export const detail=(id:string)=>request<BackfillBatch>('/backfills/'+id);
export const sendSegment=(id:string,data:unknown)=>request<BackfillBatch>('/backfills/'+id+'/segments',data);
export const publish=(id:string)=>request<Dataset>('/backfills/'+id+'/publish');
