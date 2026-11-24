import { useEffect, useRef, useState } from 'react';
import { projectRequest, type Project } from './creationProjectApi';
import { formatTaskTime } from './imageTaskApi';

export default function PlanImportDialog({open,currentId,hasDraft,onClose,onImport}:{
  open:boolean;currentId?:string|null;hasDraft:boolean;onClose:()=>void;onImport:(id:string)=>void;
}){
  const dialog=useRef<HTMLDialogElement>(null);
  const [plans,setPlans]=useState<Project[]>([]);const [selected,setSelected]=useState('');
  const [query,setQuery]=useState('');const [applied,setApplied]=useState('');
  const [loading,setLoading]=useState(false);const [error,setError]=useState('');const [attempt,setAttempt]=useState(0);
  useEffect(()=>{
    if(!open){dialog.current?.close();return;}
    if(!dialog.current?.open)dialog.current?.showModal();
    setSelected('');setQuery('');setApplied('');
  },[open]);
  useEffect(()=>{
    if(!open)return;
    let active=true;const controller=new AbortController();setLoading(true);setError('');
    projectRequest<Project[]>('?kind=plan','GET',undefined,controller.signal).then(values=>{
      if(active)setPlans(values.filter(item=>item.stage==='images'&&item.can_edit!==false));
    }).catch(err=>{if(active)setError(err instanceof Error?err.message:'读取策划方案失败。');})
      .finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;controller.abort();};
  },[open,attempt]);
  const visible=plans.filter(item=>`${item.title} ${item.source?.title||''}`.toLowerCase().includes(applied.toLowerCase()));
  return <dialog ref={dialog} className="plan-import-dialog" aria-labelledby="plan-import-title" aria-describedby="plan-import-description" onCancel={onClose}>
    <header><div><h2 id="plan-import-title">导入策划内容</h2><p id="plan-import-description">只显示已确认提示词的方案。图片清单、提示词、参考图和尺寸要求将一起载入。</p></div><button type="button" className="button-secondary" aria-label="关闭导入策划内容" onClick={onClose}>关闭</button></header>
    <form className="plan-import-filter" onSubmit={event=>{event.preventDefault();setApplied(query.trim());}}><label>关键词<input value={query} maxLength={200} onChange={event=>setQuery(event.target.value)} placeholder="方案名称或产品名称"/></label><button type="submit" className="button-primary">查询</button></form>
    {error&&<p className="feedback feedback-error" role="alert">{error} <button type="button" disabled={loading} onClick={()=>setAttempt(value=>value+1)}>重新读取</button></p>}
    <fieldset className="plan-import-options" disabled={loading} aria-label="选择已确认的策划方案">
      {loading?<p role="status">正在读取已确认方案…</p>:visible.map(item=><label className={'plan-import-option'+(selected===item.id?' is-selected':'')} key={item.id}>
        <input type="radio" name="plan-import-choice" value={item.id} checked={selected===item.id} disabled={item.id===currentId} onChange={()=>setSelected(item.id)}/>
        <span><strong>{item.title}{item.id===currentId&&<small>当前已载入</small>}</strong><small>{item.source?.title||'未关联产品'}{item.settings.market&&' · '+item.settings.market}{item.settings.language&&' · '+item.settings.language}</small><time>{formatTaskTime(item.updated_at)}</time></span>
      </label>)}
      {!loading&&!error&&!visible.length&&<p>{plans.length?'没有匹配的方案，请调整关键词。':'还没有可导入的方案，请先在图片策划中确认提示词。'}</p>}
    </fieldset>
    {hasDraft&&<p className="feedback feedback-warning">导入会替换当前尚未提交的输入，请先确认需要保留的内容。</p>}
    <footer><a href="#/planning" onClick={onClose}>前往图片策划</a><div className="guided-actions"><button type="button" className="button-secondary" onClick={onClose}>取消</button><button type="button" className="button-primary" disabled={!selected||loading} onClick={()=>onImport(selected)}>{hasDraft?'替换输入并导入':'导入所选方案'}</button></div></footer>
  </dialog>;
}
