import { useEffect, useRef, useState } from 'react';
import { imageConfigRequest, type ImageConfiguration } from './imageConfigApi';
import { materialUrl, projectRequest, type Project } from './creationProjectApi';
import { useCreationProject } from './useCreationProject';
import { ProjectFeedback, ProjectLog } from './ProjectParts';
import TaskResultsPanel from './TaskResultsPanel';
import ProjectDelivery from './ProjectDelivery';

export default function ImageProduction({id}:{id:string}){
  const state=useCreationProject(id);const {project}=state;
  const [config,setConfig]=useState<ImageConfiguration|null>(null);const [model,setModel]=useState('');const modelTouched=useRef(false);
  const [picked,setPicked]=useState<string[]>([]);const submission=useRef<string|undefined>(undefined);
  useEffect(()=>{let active=true;imageConfigRequest<ImageConfiguration|null>().then(value=>{if(active)setConfig(value);}).catch(err=>{if(active)state.setError(err.message);});return()=>{active=false;};},[]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>{if(!config)return;const names=config.model_names;const preferred=[project?.settings.image_model,config.image_model_name].find(name=>!!name&&names.includes(name))||'';setModel(previous=>modelTouched.current?(previous&&names.includes(previous)?previous:preferred):preferred);},[project?.id,project?.settings.image_model,config]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>{setPicked(project?.documents.prompts?.content.prompts?.map(item=>item.shot_id)||[]);},[project?.documents.prompts?.id]);
  async function generate(){
    if(!project)return;const requestId=submission.current||crypto.randomUUID();submission.current=requestId;
    const value=await state.mutate(()=>projectRequest<Project>(`/${id}/generate`,'POST',{
      revision:project.revision,request_id:requestId,shot_ids:picked,image_model:model,
    }),'所选图片已提交，执行结果会显示在下方。');
    if(value)submission.current=undefined;
  }
  return <div className="guided-studio"><ProjectFeedback error={state.error} notice={state.notice} loading={state.loading} onRefresh={()=>void state.refresh()}/>{project&&<>
    <div className="production-source"><div><small>已载入策划内容</small><strong>{project.title}</strong>{project.source&&<span>产品：{project.source.title}</span>}</div><div className="guided-actions"><a href={'#/planning?project='+id}>返回修改策划</a><a href="#/studio">清除方案，直接填写</a></div></div>
    {!project.documents.prompts?.confirmed_at&&<p className="feedback feedback-warning">提示词尚未确认，请先在<a href={'#/planning?project='+id}>图片策划</a>完成确认。</p>}
    <section className="guided-card"><div className="guided-form-grid"><label>图片模型<select disabled={state.locked} value={model} onChange={e=>{modelTouched.current=true;setModel(e.target.value);}}><option value="">选择已配置的图片模型</option>{config?.model_names.map(name=><option key={name}>{name}</option>)}</select></label><div className="production-skill-note"><strong>技能规范随策划沿用</strong><p>使用策划阶段已确认的提示词和参考图，不重复选择技能或改写提示词。</p></div></div>
      {project.documents.prompts?.content.prompts?.map(item=>{const shot=project.documents.brief?.content.shots?.find(value=>value.id===item.shot_id);return <article className="production-shot" key={item.shot_id}><label className="guided-image-pick"><input type="checkbox" disabled={state.locked} checked={picked.includes(item.shot_id)} onChange={e=>setPicked(previous=>e.target.checked?[...previous,item.shot_id]:previous.filter(value=>value!==item.shot_id))}/><span><strong>{shot?.name||item.shot_id}</strong><small>{shot?.size==='default'?'采用模型默认尺寸':shot?.size} · {item.reference_ids.length} 张参考图</small></span></label><details><summary>提示词与实际参考图</summary><p className="workflow-preserve-lines">{item.prompt}</p><div className="production-reference-images">{item.reference_ids.map(ref=><a key={ref} href={materialUrl(id,ref)} target="_blank" rel="noreferrer"><img src={materialUrl(id,ref)+'?preview=true'} alt={project.materials.find(material=>material.id===ref)?.name||'参考图'}/><small>{project.materials.find(material=>material.id===ref)?.name}</small></a>)}</div></details></article>;})}
      <div className="guided-actions"><button type="button" className="button-primary" disabled={state.locked||!project.documents.prompts?.confirmed_at||!model||!picked.length} onClick={()=>void generate()}>{project.busy?'正在制作…':`生成所选 ${picked.length} 张图片`}</button><a href="#/settings">管理模型与参数</a></div>
    </section>
    {(!!project.images.length||!!project.batches.length)&&<TaskResultsPanel taskId={id} batches={project.batches} onChanged={()=>void state.refresh()}/>}
    <ProjectLog project={project} stages={['images']}/>
    <ProjectDelivery key={project.id} project={project} model={model}/>
  </>}</div>;
}
