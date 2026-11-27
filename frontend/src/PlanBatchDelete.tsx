import { useEffect, useState } from 'react';
import { projectRequest, type Project } from './creationProjectApi';
import { createRequestId } from './requestId';

interface Deletion {request_id:string;project_ids:string[];count:number}
type Target=Pick<Project,'id'|'revision'|'title'>;

export function usePlanBatchDelete(plans:Project[], onChanged:()=>void){
  const [selected,setSelected]=useState<string[]>([]);
  const [review,setReview]=useState<Target[]|null>(null);
  const [pending,setPending]=useState<{request_id:string;plans:{id:string;revision:number}[]}|null>(null);
  const [undo,setUndo]=useState<Deletion|null>(null);
  const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [message,setMessage]=useState('');
  const eligible=plans.filter(item=>item.kind==='plan'&&item.can_edit!==false&&!item.busy);
  const key=eligible.map(item=>item.id+':'+item.revision).join('|');
  useEffect(()=>{setSelected(previous=>previous.filter(id=>eligible.some(item=>item.id===id)));setReview(null);setPending(null);},[key]);
  const chosen=eligible.filter(item=>selected.includes(item.id));
  function toggle(id:string){if(busy)return;setSelected(previous=>previous.includes(id)?previous.filter(item=>item!==id):[...previous,id]);setReview(null);setPending(null);setError('');}
  function selectAll(){if(busy)return;setSelected(chosen.length===eligible.length?[]:eligible.map(item=>item.id));setReview(null);setPending(null);}
  async function remove(){
    if(!review?.length||busy)return;
    const body=pending||{request_id:createRequestId(),plans:review.map(({id,revision})=>({id,revision}))};
    setPending(body);setBusy(true);setError('');
    try{const result=await projectRequest<Deletion>('/batch-delete','POST',body);setUndo(result);setMessage(`已删除 ${result.count} 套图片策划，可撤销本次删除。`);setSelected([]);setReview(null);setPending(null);onChanged();}
    catch(err){setError(err instanceof Error?err.message:'批量删除失败，请重试。');}
    finally{setBusy(false);}
  }
  async function restore(){
    if(!undo||busy)return;setBusy(true);setError('');
    try{const result=await projectRequest<Deletion>('/batch-delete/restore','POST',undo);setMessage(`已恢复 ${result.count} 套图片策划。`);setUndo(null);onChanged();}
    catch(err){setError(err instanceof Error?err.message:'恢复失败，请重试。');}
    finally{setBusy(false);}
  }
  return {selected,chosen,eligible,busy,error,message,undo,review,toggle,selectAll,remove,restore,
    begin:()=>{setReview(chosen.map(({id,revision,title})=>({id,revision,title})));setPending(null);setError('');},
    cancel:()=>{setReview(null);setPending(null);setError('');}};
}

export type PlanDeleteState=ReturnType<typeof usePlanBatchDelete>;
export function PlanBatchDeleteBar({state,loading=false}:{state:PlanDeleteState;loading?:boolean}){
  const disabled=state.busy||loading;
  return <div className="plan-batch-delete">
    <div className="plan-batch-toolbar" aria-label="图片策划批量操作">
      <label><input type="checkbox" aria-label="全选当前筛选的可删除策划" disabled={disabled||!state.eligible.length} checked={!!state.eligible.length&&state.chosen.length===state.eligible.length} onChange={state.selectAll}/>全选当前筛选</label>
      <span>已选 {state.chosen.length} 套</span>
      <button type="button" className="plan-delete-button" disabled={disabled||!state.chosen.length} onClick={state.begin}>批量删除策划</button>
      <small>执行中的策划不可删除</small>
    </div>
    {state.review&&<section className="plan-delete-review" aria-label="确认批量删除">
      <strong>确认删除这 {state.review.length} 套图片策划？</strong>
      <p>{state.review.slice(0,5).map(item=>item.title).join('、')}{state.review.length>5?' 等':''}</p>
      <p>策划、关联图片和团队共享入口将移除；产品资料、已打包案例、经验与他人的独立副本保留。原始文件保留，可撤销本次删除。</p>
      <div className="guided-actions"><button type="button" className="button-secondary" disabled={state.busy} onClick={state.cancel}>取消</button><button type="button" className="plan-delete-button" disabled={disabled} onClick={()=>void state.remove()}>{state.busy?'正在删除…':'确认删除所选策划'}</button></div>
    </section>}
    {state.error&&<p className="feedback feedback-error" role="alert">{state.error}</p>}
    {state.message&&<div className="feedback feedback-success" role="status">{state.message}{state.undo&&<button type="button" disabled={disabled} onClick={()=>void state.restore()}>{state.busy?'正在处理…':'撤销本次删除'}</button>}</div>}
  </div>;
}

export function PlanDeleteCheckbox({project,state}:{project:Project;state:PlanDeleteState}){
  const eligible=state.eligible.some(item=>item.id===project.id);
  return <label className="plan-delete-checkbox" title={eligible?'选择此策划':'执行中或无删除权限'}><input type="checkbox" aria-label={'选择策划：'+project.title} checked={state.selected.includes(project.id)} disabled={state.busy||!eligible} onChange={()=>state.toggle(project.id)}/><span>选择</span></label>;
}
