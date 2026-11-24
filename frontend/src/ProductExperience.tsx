import { useEffect, useRef, useState } from 'react';
import { apiFetch } from './apiFetch';
import { useUnsavedChanges } from './useCreationProject';

export interface DrawingExperience {
  id: string; revision: number; guidance: string; market: string; purpose: string; style: string;
  status?: 'candidate' | 'active' | 'disabled'; updated_at?: string;
  sources: {id:string; revision:number; job_id:string; experience:string; issues:string; requested_change:string}[];
}
interface Feedback {id:string; revision:number; job_id:string; outcome:string; experience:string; issues:string; requested_change:string; shot_name:string; image_url:string; updated_at:string}
interface ExperienceData {feedback:Feedback[]; experiences:DrawingExperience[]}
async function request<T>(path:string,method='GET',body?:unknown):Promise<T>{
  const response=await apiFetch('/api/product-experience/'+path,{method,cache:'no-store',signal:AbortSignal.timeout(method==='POST'&&path.endsWith('/summarize')?150000:20000),headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
  const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'保存未完成，请检查内容并重试。');return value;
}
const statusNames={candidate:'待确认',active:'已生效',disabled:'已停用'};
const empty:DrawingExperience={id:'',revision:0,guidance:'',market:'',purpose:'',style:'',sources:[],status:'candidate'};
function ScopeFields({value,onChange}:{value:DrawingExperience;onChange:(value:DrawingExperience)=>void}){
  return <details className="experience-scope"><summary>适用范围 · {value.market||value.purpose||value.style?'有条件限制':'此产品通用'}</summary><p>留空表示通用。填写后，只有策划要求中包含对应条件才会参考；多项条件需同时匹配。</p><div className="guided-form-grid">{([{key:'market',label:'市场',limit:120},{key:'purpose',label:'图片用途',limit:120},{key:'style',label:'风格',limit:200}] as const).map(field=><label key={field.key}>{field.label}<input maxLength={field.limit} value={value[field.key]} onChange={e=>onChange({...value,[field.key]:e.target.value})}/></label>)}</div></details>;
}
function ExperienceCard({item,locked,onSave}:{item:DrawingExperience;locked:boolean;onSave:(value:DrawingExperience)=>Promise<boolean>}){
  const [draft,setDraft]=useState(item);const [dirty,setDirty]=useState(false);const [busy,setBusy]=useState(false);
  useUnsavedChanges(dirty);
  useEffect(()=>{setDraft(item);setDirty(false);},[item.id,item.revision]); // eslint-disable-line react-hooks/exhaustive-deps
  function change(value:DrawingExperience){setDraft(value);setDirty(true);}
  async function save(status:DrawingExperience['status']){setBusy(true);try{if(await onSave({...draft,status}))setDirty(false);}finally{setBusy(false);}}
  return <article className={'experience-rule experience-'+item.status}><header><strong>{statusNames[item.status||'candidate']}</strong><small>版本 {item.revision} · {item.updated_at&&new Date(item.updated_at).toLocaleString('zh-CN')}</small></header><fieldset disabled={locked||busy}><label>作图经验<textarea rows={3} maxLength={4000} value={draft.guidance} onChange={e=>change({...draft,guidance:e.target.value})}/></label><ScopeFields value={draft} onChange={change}/></fieldset>
    {!!item.sources.length&&<details><summary>依据 {item.sources.length} 条图片反馈</summary>{item.sources.map(source=><p key={source.id}><a href={'#/library?job='+source.job_id}>查看原图与反馈</a> · 反馈版本 {source.revision}<span className="experience-evidence">{[source.experience,source.issues,source.requested_change].filter(Boolean).join('；')}</span></p>)}</details>}
    {!locked&&<div className="guided-actions"><button type="button" className="button-primary" disabled={busy||!draft.guidance.trim()||(item.status==='active'&&!dirty)} onClick={()=>void save('active')}>{busy?'保存中…':item.status==='active'?'保存修改':'确认生效'}</button>{item.status==='candidate'&&<button type="button" className="button-secondary" disabled={busy||!dirty||!draft.guidance.trim()} onClick={()=>void save('candidate')}>保存草稿</button>}{item.status!=='disabled'&&<button type="button" className="button-secondary" disabled={busy} onClick={()=>void save('disabled')}>停用</button>}</div>}
  </article>;
}
export function DrawingExperienceUsed({value}:{value?:Record<string,DrawingExperience[]>}){
  const entries=[...new Map(Object.values(value||{}).flat().map(item=>[item.id+':'+item.revision,item])).values()];
  if(!entries.length)return null;
  return <details className="experience-used"><summary>策划参考的作图经验 · {entries.length} 条</summary><p>保留当时的经验版本；图片制作沿用已确认提示词。</p>{entries.map(item=><p key={item.id+':'+item.revision}><strong>版本 {item.revision}</strong> · {item.guidance}</p>)}</details>;
}
export default function ProductExperience({productId,readOnly=false}:{productId:string;readOnly?:boolean}){
  const [data,setData]=useState<ExperienceData>();const [picked,setPicked]=useState<string[]>([]);const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [notice,setNotice]=useState('');
  const [draft,setDraft]=useState(empty);const [adding,setAdding]=useState(false);const summaryId=useRef<string|undefined>(undefined);
  useUnsavedChanges(adding&&!!draft.guidance.trim()||busy);
  async function load(){try{setData(await request<ExperienceData>(productId));}catch(err){setError(err instanceof Error?err.message:'读取失败');}}
  useEffect(()=>{let active=true;setData(undefined);setPicked([]);setError('');request<ExperienceData>(productId).then(value=>{if(active)setData(value);}).catch(err=>{if(active)setError(err.message);});return()=>{active=false;};},[productId]);
  async function save(value:DrawingExperience){setError('');setNotice('');try{await request(productId+(value.id?'/'+value.id:''),value.id?'PUT':'POST',value);await load();setNotice(value.status==='active'?'作图经验已生效，后续策划会按适用范围参考。':'作图经验已保存。');return true;}catch(err){setError(err instanceof Error?err.message:'保存失败');return false;}}
  async function summarize(){if(!data)return;setBusy(true);setError('');setNotice('');summaryId.current ||= crypto.randomUUID();try{await request(productId+'/summarize','POST',{request_id:summaryId.current,feedback:Object.fromEntries(data.feedback.filter(item=>picked.includes(item.id)).map(item=>[item.id,item.revision]))});summaryId.current=undefined;await load();setNotice('经验建议已生成，请检查、修改并确认生效。');}catch(err){setError(err instanceof Error?err.message:'整理失败');}finally{setBusy(false);}}
  return <section className="guided-card product-experience" aria-label="产品作图经验"><header><div><h3>作图经验</h3><p>从图片反馈积累此产品的做法。仅已生效的经验用于后续策划或关联此产品的直接创作，不改动已有提示词。</p></div></header>
    {error&&<p className="feedback feedback-error" role="alert">{error} <button type="button" className="button-secondary" disabled={busy} onClick={()=>void load()}>刷新经验</button></p>}{notice&&<p className="feedback feedback-success" role="status">{notice}</p>}
    {!data&&!error&&<p role="status">正在读取作图经验…</p>}
    {data&&<><details className="product-feedback-list"><summary>图片反馈 · {data.feedback.length} 条</summary><p>在生成记录打开图片详情即可填写反馈。选择最多 30 条反馈整理建议，不会自动生效。</p>{!data.feedback.length&&<p className="empty-state">还没有关联此产品的图片反馈。</p>}{data.feedback.map(item=><article className="product-feedback-row" key={item.id}><a href={'#/library?job='+item.job_id}><img loading="lazy" src={item.image_url} alt={item.shot_name||'反馈图片'}/></a><div><header><label><input type="checkbox" disabled={readOnly||busy||(!picked.includes(item.id)&&picked.length>=30)} checked={picked.includes(item.id)} onChange={e=>{setPicked(previous=>e.target.checked?[...previous,item.id]:previous.filter(id=>id!==item.id));summaryId.current=undefined;}}/>{item.shot_name||'生成图片'} · {({pending:'待评价',satisfied:'满意',rework:'需要修改'} as Record<string,string>)[item.outcome]}</label><small>{new Date(item.updated_at).toLocaleString('zh-CN')}</small></header>{item.experience&&<p><strong>有效做法：</strong>{item.experience}</p>}{item.issues&&<p><strong>问题：</strong>{item.issues}</p>}{item.requested_change&&<p><strong>修改要求：</strong>{item.requested_change}</p>}<a href={'#/library?job='+item.job_id}>查看原图与反馈 →</a></div></article>)}{!readOnly&&<div className="guided-actions"><button type="button" className="button-primary" disabled={busy||!picked.length} onClick={()=>void summarize()}>{busy?'正在整理经验…':`AI 整理所选 ${picked.length} 条反馈`}</button></div>}</details>
      {data.experiences.map(item=><ExperienceCard key={item.id} item={item} locked={readOnly||busy} onSave={save}/>)}{!data.experiences.length&&<p className="empty-state">还没有作图经验，可整理反馈，也可手动记录。</p>}
      {!readOnly&&(adding?<form className="experience-rule" onSubmit={async e=>{e.preventDefault();setBusy(true);try{if(await save({...draft,status:'active'})){setAdding(false);setDraft(empty);}}finally{setBusy(false);}}}><fieldset disabled={busy}><label>新经验<textarea rows={3} maxLength={4000} required value={draft.guidance} onChange={e=>setDraft({...draft,guidance:e.target.value})}/></label><ScopeFields value={draft} onChange={setDraft}/></fieldset><div className="guided-actions"><button className="button-primary" disabled={busy||!draft.guidance.trim()}>保存并生效</button><button type="button" className="button-secondary" disabled={busy} onClick={()=>{if(!draft.guidance.trim()||window.confirm('放弃尚未保存的经验？')){setAdding(false);setDraft(empty);}}}>取消</button></div></form>:<button type="button" className="button-secondary" disabled={busy} onClick={()=>setAdding(true)}>手动添加经验</button>)}
    </>}
  </section>;
}
