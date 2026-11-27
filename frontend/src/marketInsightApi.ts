import { apiFetch } from './apiFetch';

export type Data = Record<string, unknown>;
export interface MarketStudy {id:string;title:string;marketplace:string;author:string;owner_id:string;can_edit:boolean;notes:string;created_at:string;queries?:MarketQuery[]}
export interface MarketQuery {id:string;study_id:string;provider:'sellersprite'|'xiyou';section:string;tool:string;arguments:Data;status:'queued'|'running'|'succeeded'|'failed'|'unknown';result:Data;error:string;created_at:string;updated_at:string;billing:Data|null;reused_from?:string;cache_hit?:boolean}
export async function marketRequest<T>(path:string,method='GET',body?:unknown):Promise<T>{
  const response=await apiFetch('/api/market-insights'+path,{method,cache:'no-store',signal:AbortSignal.timeout(20000),headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
  const value=await response.json();
  if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'请求未完成，请检查输入或稍后刷新记录。');
  return value;
}
export function object(value:unknown):Data{return value!==null&&typeof value==='object'&&!Array.isArray(value)?value as Data:{}}
export function array(value:unknown):Data[]{return Array.isArray(value)?value.map(object):[]}
export function unwrap(value:Data):Data{return value.data&&typeof value.data==='object'&&!Array.isArray(value.data)?object(value.data):value}
export function numeric(value:unknown):number|null {if(value===null||value===undefined||value===''||typeof value==='boolean')return null;const n=Number(value);return Number.isFinite(n)?n:null;}
export function display(value:unknown,percent=false):string {const n=numeric(value);return n===null?'—':percent?(n*100).toFixed(1)+'%':n.toLocaleString('zh-CN',{maximumFractionDigits:2});}
export function label(value:unknown):string {if(typeof value==='string'||typeof value==='number')return String(value);const v=object(value);return String(v.translated||v.original||'未命名类目');}
