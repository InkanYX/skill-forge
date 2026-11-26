import { useRef, useState } from 'react';
import { projectRequest, type Project } from './creationProjectApi';
import { formatTaskTime } from './imageTaskApi';
import type { WorkflowCase } from './workflowCaseApi';

export default function ProjectDelivery({project,model}:{project:Project;model:string}) {
  const [batch,setBatch]=useState(''); const [busy,setBusy]=useState('');
  const [error,setError]=useState(''); const [mobile,setMobile]=useState<Project>();
  const [archived,setArchived]=useState<WorkflowCase>();
  const [title,setTitle]=useState(project.title+' · 完整案例'); const [summary,setSummary]=useState('');
  const [saving,setSaving]=useState(false); const [confirmMobile,setConfirmMobile]=useState(false);
  const ids=useRef<Record<string,string>>({});
  const desktop=project.batches.filter(b=>b.job_ids.length&&b.job_ids.every(id=>{
    const job=project.images.find(i=>i.id===id);return job?.status==='succeeded'&&job.size==='1464x600';
  }));
  const selected=desktop.find(b=>b.execution_id===batch)||desktop.at(-1);
  const isAPlus=desktop.length>0||project.settings.learning?.image_type==='a_plus'||project.documents.brief?.content.shots?.some(shot=>shot.size==='1464x600')||/a\s*\+|premium\s*a|ebc/i.test(project.settings.goal||'');
  const archiveReason=project.can_edit===false?'只有项目作者可以打包案例。':project.busy||project.images.some(i=>['queued','running'].includes(i.status))?'图片或流程仍在执行，完成后即可打包。':!project.images.some(i=>i.status==='succeeded')?'至少成功生成一张图片后可打包案例。':'';
  const canArchive=!archiveReason;
  const locked=!!busy||project.busy||project.can_edit===false;
  async function convert(){
    if(!selected)return;
    const key='mobile:'+selected.execution_id;ids.current[key]??=crypto.randomUUID();
    setBusy('mobile');setError('');
    try {
      setMobile(await projectRequest<Project>('/'+project.id+'/mobile','POST',{
        revision:project.revision,request_id:ids.current[key],batch_id:selected.execution_id,image_model:model,
      },AbortSignal.timeout(120000)));setConfirmMobile(false);
    }catch(err){setError(err instanceof Error?err.message:'手机版提交失败。');}
    finally{setBusy('');}
  }
  async function archive(){
    ids.current.case??=crypto.randomUUID();setBusy('case');setError('');
    try {
      setArchived(await projectRequest<WorkflowCase>('/'+project.id+'/cases','POST',{
        revision:project.revision,request_id:ids.current.case,title,summary,
      },AbortSignal.timeout(120000)));setSaving(false);
    }catch(err){setError(err instanceof Error?err.message:'案例归档失败。');}
    finally{setBusy('');}
  }
  return <section className="guided-card project-delivery" id="project-delivery" tabIndex={-1}><header><div><small>完成之后</small><h3>{isAPlus||project.mobile_source?'手机版与案例交付':'案例交付'}</h3></div><a href="#/showcases">浏览完整案例</a></header>
    {error&&<p className="feedback feedback-error" role="alert">{error}</p>}
    {project.mobile_source?<p>当前为独立手机版方案。<a href={'#/studio?project='+project.mobile_source.project_id}>查看桌面原版</a></p>:isAPlus&&<div className="delivery-option"><div><h4>整套转为手机版</h4><p>选定一版已完成的桌面A+，逐张以原图和实拍为参考重新排版，目标1200×900（4:3），保存为独立方案。会产生新的图片调用费用。</p></div>
      {!!desktop.length&&<label>桌面来源版本<select value={selected?.execution_id||''} disabled={locked} onChange={e=>{setBatch(e.target.value);setConfirmMobile(false);setMobile(undefined);}}>{[...desktop].reverse().map(b=><option key={b.execution_id} value={b.execution_id}>第 {b.version_number||project.batches.indexOf(b)+1} 版 · {b.job_ids.length} 张 · {formatTaskTime(b.created_at)}</option>)}</select></label>}
      {!desktop.length&&<small>桌面A+版本全部生成成功后可使用。</small>}
      {mobile?<p className="feedback feedback-success">手机版任务已提交。<a href={'#/studio?project='+mobile.id}>查看手机版进度</a></p>:confirmMobile?<div className="guided-actions"><span>使用当前配置的服务商和模型，批量编辑 {selected?.job_ids.length} 张参考图？</span><button type="button" className="button-primary" disabled={locked||!model} onClick={()=>void convert()}>{busy==='mobile'?'正在提交…':'确认制作手机版'}</button><button type="button" className="button-secondary" disabled={!!busy} onClick={()=>setConfirmMobile(false)}>取消</button></div>:<button type="button" className="button-secondary" disabled={locked||!selected||!model} onClick={()=>setConfirmMobile(true)}>一键制作整套手机版</button>}
    </div>}
    <div className="delivery-option"><div><h4>归档为完整案例</h4><p>保存原始PDF与图片资料、卖点分析、每版图需和提示词、生成结果、质检与反馈、技能版本和过程记录，包含已完成的关联桌面及手机版。后续选用案例方法，为新产品重新策划。</p></div>
      {archiveReason&&<p role="status">{archiveReason}</p>}
      {project.images.some(i=>i.status==='unknown')&&<p>历史记录中有结果待确认的调用，将按原状态归档；打包不会重试生图。</p>}
      {archived?<p className="feedback feedback-success">案例已保存。<a href={'#/showcases?case='+archived.id}>展示与复用</a> · <a href={'/api/workflow-cases/'+archived.id+'/download'}>下载完整案例ZIP</a></p>:saving?<div className="guided-form-grid"><label>案例名称<input value={title} maxLength={160} onChange={e=>setTitle(e.target.value)} disabled={!!busy}/></label><label>可复用经验与适用范围<textarea value={summary} maxLength={8000} rows={4} placeholder="哪些构图有效？哪些错误已纠正？适用于什么产品与场景？这些内容会作为后续选用案例的参考。" onChange={e=>setSummary(e.target.value)} disabled={!!busy}/></label><div className="guided-actions"><button type="button" className="button-primary" disabled={locked||!canArchive||!title.trim()} onClick={()=>void archive()}>{busy==='case'?'正在归档…':'保存完整案例'}</button><button type="button" className="button-secondary" disabled={!!busy} onClick={()=>setSaving(false)}>取消</button></div></div>:<button type="button" className="button-secondary" disabled={locked||!canArchive} onClick={()=>setSaving(true)}>将整个流程打包为案例</button>}
    </div>
  </section>;
}
