import { useEffect, useState } from 'react';
import { projectRequest, type Project } from './creationProjectApi';
import { projectDestination, projectStatus } from './projectProgress.mjs';
import { formatTaskTime } from './imageTaskApi';
import ProjectCover from './ProjectCover';
import { useWorkspaceView } from './useWorkspaceView';

function productId(project:Project){return project.source?.product_id||project.source_product_id||'';}
function useProductPlans(id:string,revision?:number){
  const [plans,setPlans]=useState<Project[]>([]);const [loading,setLoading]=useState(true);const [error,setError]=useState('');const [attempt,setAttempt]=useState(0);
  useEffect(()=>{let active=true;setLoading(true);setError('');
    if(!id){setPlans([]);setLoading(false);return;}
    projectRequest<Project[]>('?kind=plan').then(async values=>{
      const children=values.filter(item=>item.kind==='plan'&&productId(item)===id);
      // List responses omit documents and images. Read details to show the actual stage and latest result.
      const details=await Promise.all(children.map(item=>item.documents&&item.images?Promise.resolve(item):projectRequest<Project>('/'+item.id)));
      if(active)setPlans(details.sort((a,b)=>b.updated_at.localeCompare(a.updated_at)));
    }).catch(err=>{if(active)setError(err instanceof Error?err.message:'图片策划读取失败。');}).finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;};
  },[id,revision,attempt]);
  return {plans,loading,error,refresh:()=>setAttempt(value=>value+1)};
}

export function ProductPlanList({project,blocked=false}:{project:Project;blocked?:boolean}){
  const {plans,loading,error,refresh}=useProductPlans(project.id,project.revision);const [query,setQuery]=useWorkspaceView('product:'+project.id+':plans-query','');
  const visible=plans.filter(item=>`${item.title} ${item.settings.market||''} ${item.settings.goal||''}`.toLowerCase().includes(query.trim().toLowerCase()));
  const ready=!!project.documents.analysis?.confirmed_at&&!blocked;
  return <section className="guided-card product-plan-list" aria-label="该产品的图片策划">
    <header><div><small>属于 {project.title}</small><h3>图片策划 <span>{plans.length} 套</span></h3><p>同一份产品资料可以建立多套策划，每套分别保存图需、提示词、生图版本与案例。</p></div><div className="guided-actions"><button className="button-secondary" type="button" disabled={loading} onClick={refresh}>刷新方案</button>{ready&&<a className="button-primary" href={'#/planning?new=1&product='+project.id}>为此产品新建策划方案 →</a>}</div></header>
    {!ready&&<p className="action-prerequisite">{blocked?'产品资料或卖点有未保存修改，保存并确认后可新建策划。':'先在“产品资料与卖点”中确认卖点，再建立新的图片策划。已有方案可继续查看。'}</p>}
    <label className="product-plan-search">选择已有策划<input type="search" value={query} maxLength={200} onChange={e=>setQuery(e.target.value)} placeholder="按方案名称、渠道或制作目标查找"/></label>
    {error&&<p className="feedback feedback-error" role="alert">{error}</p>}
    {loading?<p role="status">正在读取该产品的策划方案…</p>:<div className="product-plan-grid">{visible.map(item=>{const status=projectStatus(item);return <a key={item.id} className="product-plan-card" href={projectDestination(item)}><ProjectCover project={item}/><div className="plan-card-meta"><span className={'workflow-record-status status-'+status.key}>{status.label}</span><small>{item.settings.market||'未设置渠道'}</small></div><h4>{item.title}</h4><p>{item.settings.goal||'未填写制作目标'}</p><footer><time>{formatTaskTime(item.updated_at)}</time><strong>{status.key==='complete'?'查看成果':'进入方案'} →</strong></footer></a>;})}</div>}
    {!loading&&!error&&!visible.length&&<p className="workspace-empty">{plans.length?'没有匹配的方案，请调整关键词。':'这个产品还没有图片策划。确认卖点后，创建第一套方案。'}</p>}
  </section>;
}

export function PlanContext({project,dirty=false,current}:{project:Project;dirty?:boolean;current?:string}){
  const sourceId=productId(project);const {plans,loading,error,refresh}=useProductPlans(sourceId);
  if(!sourceId)return null;
  const options=plans.some(item=>item.id===project.id)?plans:[project,...plans];
  return <section className="plan-context" aria-label="产品与策划归属"><div className="plan-breadcrumb"><a href="#/products">产品资料</a><span aria-hidden="true">/</span><a href={'#/products?project='+sourceId+'&tab=plans'}>{project.source?.title||'所属产品'}</a><span aria-hidden="true">/</span><strong>{project.title}</strong>{current&&<span className="context-stage">{current}</span>}</div><div className="plan-context-controls"><label>该产品的图片策划<select value={project.id} disabled={loading} onChange={event=>{
      const selected=options.find(item=>item.id===event.target.value);
      if(!selected||selected.id===project.id)return;
      if(dirty&&!window.confirm('当前修改尚未保存，确定切换到其他策划吗？'))return;
      window.location.hash=projectDestination(selected);
    }}>{options.map(item=><option key={item.id} value={item.id}>{item.title}{item.id===project.id?' · 当前方案':''}</option>)}</select></label><a className="button-secondary" href={'#/products?project='+sourceId+'&tab=plans'}>查看该产品全部策划</a></div>{error&&<p className="feedback feedback-error" role="alert">策划切换列表读取失败。<button type="button" onClick={refresh}>重新读取</button></p>}</section>;
}
