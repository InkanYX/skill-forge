import { useEffect, useRef, useState } from 'react';
import { CreationSkillPicker, useCreationSkill } from './CreationSkillContext';
import { imageConfigRequest, type ImageConfiguration } from './imageConfigApi';
import { projectRequest, type Project } from './creationProjectApi';
import { useCreationProject, uploadProjectMaterials, useUnsavedChanges } from './useCreationProject';
import { ProjectFeedback, ProjectMaterials, ProjectLog, ProjectHistory } from './ProjectParts';
import ProductExperience from './ProductExperience';

export default function ProductAnalysisEditor({id}:{id?:string}){
  const state=useCreationProject(id||'');const {project}=state;const skill=useCreationSkill();
  const [name,setName]=useState('');const [sku,setSku]=useState('');const [goal,setGoal]=useState('');
  const [planner,setPlanner]=useState('');const [config,setConfig]=useState<ImageConfiguration|null>(null);
  const [instruction,setInstruction]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const [files,setFiles]=useState<{file:File;kind:string}[]>([]);const created=useRef<Project|null>(null);
  const [analysis,setAnalysis]=useState({facts:'',selling_points:'',questions:''});const [analysisDirty,setAnalysisDirty]=useState(false);
  const doc=project?.documents.analysis;
  useEffect(()=>{let active=true;imageConfigRequest<ImageConfiguration|null>().then(value=>{if(active){setConfig(value);setPlanner(previous=>previous||value?.planning_model_name||'');}}).catch(err=>{if(active)setError(err.message);});return()=>{active=false;};},[]);
  useEffect(()=>{if(project){setName(project.title);setSku(project.settings.sku||'');setGoal(project.settings.goal);setPlanner(project.settings.planning_model||config?.planning_model_name||'');}},[project?.id,project?.revision]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>{setAnalysis({facts:doc?.content.facts||'',selling_points:doc?.content.selling_points||'',questions:doc?.content.questions||''});setAnalysisDirty(false);},[doc?.id]);
  const infoDirty=!!project&&(name!==project.title||sku!==(project.settings.sku||'')||goal!==project.settings.goal);
  useUnsavedChanges(infoDirty||analysisDirty||(!id&&(!!name||!!goal||!!files.length)));
  const locked=busy||state.locked;
  async function create(){
    setBusy(true);setError('');let value=created.current;
    try{
      value=value?await projectRequest<Project>('/'+value.id):await projectRequest<Project>('','POST',{kind:'product',title:name,sku,goal});
      created.current=value;
      const remaining=[...files];
      while(remaining.length){const entry=remaining[0];value=await uploadProjectMaterials(value,[entry.file],entry.kind);created.current=value;remaining.shift();setFiles([...remaining]);}
      window.location.hash='#/products?project='+value.id;
    }catch(err){setError((err instanceof Error?err.message:'保存失败')+(value?' 产品已保存，可打开产品继续添加资料。':''));}
    finally{setBusy(false);}
  }
  async function saveInfo(){if(!project)return;await state.mutate(()=>projectRequest<Project>('/'+project.id,'PUT',{
    ...project.settings,kind:'product',title:name,sku,goal,skill:project.skill,revision:project.revision,
  }),'产品信息已保存。');}
  async function saveAnalysis(confirm:boolean){
    if(!project)return;let value=project;
    if(analysisDirty||!doc){const saved=await state.mutate(()=>projectRequest<Project>(`/${value.id}/documents/analysis`,'PUT',{revision:value.revision,content:analysis}),'分析结果已保存。');if(!saved)return;value=saved;setAnalysisDirty(false);}
    if(confirm)await state.mutate(()=>projectRequest<Project>(`/${value.id}/documents/analysis/confirm`,'POST',{revision:value.revision}),'产品卖点已确认，可以建立图片策划方案。');
  }
  async function analyze(){
    try{const body=new FormData();skill.append(body);const value=await state.run('analysis',instruction,{planning_model:planner,skill:JSON.parse(String(body.get('skill')))});if(value)setInstruction('');}
    catch(err){state.setError(err instanceof Error?err.message:'分析设置无效');}
  }
  return <div className="guided-studio"><ProjectFeedback error={error||state.error} notice={state.notice} loading={state.loading} onRefresh={()=>void state.refresh()}/>
    {!id?<section className="guided-card"><h3>新建产品</h3><p>填写名称并上传现有资料。保存产品不调用模型，之后在同一详情页分析和确认卖点。</p><fieldset disabled={busy}><div className="guided-form-grid"><label>产品名称<input required maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></label><label>SKU（选填）<input maxLength={100} value={sku} onChange={e=>setSku(e.target.value)}/></label></div><label>产品说明<textarea rows={4} maxLength={12000} value={goal} onChange={e=>setGoal(e.target.value)} placeholder="补充产品事实、已知参数或需要注意的结构特点。"/></label><label>说明书、规格书与产品图片<input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" multiple onChange={e=>{setFiles(previous=>[...previous,...Array.from(e.target.files||[]).map(file=>({file,kind:file.name.toLowerCase().endsWith('.pdf')?'说明书':'产品实拍'}))]);e.target.value='';}}/></label>{files.map((entry,index)=><div className="pending-material" key={index}><span>{entry.file.name}</span><select aria-label={entry.file.name+' 的资料用途'} value={entry.kind} onChange={e=>setFiles(previous=>previous.map((item,i)=>i===index?{...item,kind:e.target.value}:item))}>{['说明书','规格书','产品实拍','产品图','结构细节','其他'].map(kind=><option key={kind}>{kind}</option>)}</select><button type="button" onClick={()=>setFiles(previous=>previous.filter((_,i)=>i!==index))}>移除</button></div>)}<div className="guided-actions"><button type="button" className="button-primary" disabled={!name.trim()} onClick={()=>void create()}>{busy?'保存中…':'保存产品'}</button><a href="#/products">取消</a>{created.current&&<a href={'#/products?project='+created.current.id}>打开已保存产品</a>}</div></fieldset></section>:project&&<>
      <div className="guided-toolbar"><div><h3>{project.title}</h3><p>产品资料与分析结果统一保存在这里。</p></div><a className="button-secondary" href="#/products">返回产品列表</a></div>
      {project.can_edit===false&&<p className="feedback">团队共享产品，可查看资料并建立策划方案，修改请联系创建者。</p>}
      <details className="guided-card" open={!doc}><summary>产品信息</summary><fieldset disabled={locked}><div className="guided-form-grid"><label>产品名称<input maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></label><label>SKU<input maxLength={100} value={sku} onChange={e=>setSku(e.target.value)}/></label></div><label>产品说明<textarea rows={4} maxLength={12000} value={goal} onChange={e=>setGoal(e.target.value)}/></label><button type="button" className="button-secondary" disabled={!infoDirty} onClick={()=>void saveInfo()}>保存产品信息</button></fieldset></details>
      <ProjectMaterials project={project} locked={locked||infoDirty||analysisDirty} onUpload={(items,kind)=>state.mutate(()=>uploadProjectMaterials(project,items,kind),'资料已保存，需重新确认分析结果。')} onRemove={materialId=>void state.mutate(()=>projectRequest<Project>(`/${project.id}/materials/${materialId}?revision=${project.revision}`,'DELETE'),'资料已移除。')}/>
      <section className="guided-card"><header><h3>产品分析与卖点</h3>{doc&&<span>版本 {doc.version} · {doc.confirmed_at&&!analysisDirty?'已确认':'待确认'}</span>}</header>
        <details className="workflow-options"><summary>分析设置 · 技能默认自动选择</summary><p>AI 按产品分析任务选择适用技能，不需要每次手动指定。</p><label>分析模型<select value={planner} disabled={locked} onChange={e=>setPlanner(e.target.value)}><option value="">请选择模型</option>{config?.model_names.map(model=><option key={model}>{model}</option>)}</select></label><CreationSkillPicker/></details>
        <label>本轮分析要求<textarea rows={3} maxLength={12000} value={instruction} disabled={locked} onChange={e=>setInstruction(e.target.value)} placeholder="例如：核对说明书与实拍中的结构，区分已知事实、候选卖点和待确认参数。"/></label>
        {infoDirty&&<p className="feedback feedback-warning">产品信息尚未保存，先保存再分析。</p>}
        <div className="guided-actions"><button type="button" className="button-primary" disabled={locked||infoDirty||analysisDirty||!planner||!skill.ready||(!project.materials.length&&!goal.trim())} onClick={()=>void analyze()}>{project.busy?'正在分析…':doc?'按要求重新分析':'分析产品，提炼卖点'}</button>{!planner&&<a href="#/settings">先设置默认策划模型</a>}</div>
        {(doc||analysisDirty)&&<fieldset disabled={locked}>{([{key:'facts',label:'产品事实与来源'},{key:'selling_points',label:'候选卖点与依据'},{key:'questions',label:'待确认问题'}] as const).map(field=><label key={field.key}>{field.label}<textarea rows={field.key==='questions'?3:7} value={analysis[field.key]} onChange={e=>{setAnalysis(previous=>({...previous,[field.key]:e.target.value}));setAnalysisDirty(true);}}/></label>)}<div className="guided-actions"><button type="button" className="button-secondary" disabled={!analysisDirty} onClick={()=>void saveAnalysis(false)}>保存修改</button><button type="button" className="button-primary" disabled={infoDirty||!analysis.facts.trim()||!analysis.selling_points.trim()} onClick={()=>void saveAnalysis(true)}>确认产品卖点</button></div></fieldset>}
        {doc?.confirmed_at&&!analysisDirty&&!infoDirty&&<a className="button-primary" href={'#/planning?new=1&product='+project.id}>为此产品新建策划方案 →</a>}
        {!doc&&!analysisDirty&&<details><summary>手动录入已确认的产品事实和卖点</summary><button type="button" disabled={locked} onClick={()=>setAnalysisDirty(true)}>开始填写</button></details>}
      </section><ProductExperience productId={project.id} readOnly={project.can_edit===false}/><ProjectLog project={project} stages={['analysis']}/><ProjectHistory project={project} stages={['analysis']}/>
    </>}
  </div>;
}
