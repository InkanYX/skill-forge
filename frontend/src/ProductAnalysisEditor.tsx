import { useEffect, useRef, useState } from 'react';
import { CreationSkillPicker, useCreationSkill } from './CreationSkillContext';
import { imageConfigRequest, type ImageConfiguration } from './imageConfigApi';
import { projectRequest, type Project } from './creationProjectApi';
import { useCreationProject, uploadProjectMaterials, useUnsavedChanges } from './useCreationProject';
import { ProjectFeedback, ProjectMaterials, ProjectLog, ProjectHistory } from './ProjectParts';
import ProductExperience from './ProductExperience';

const sizeText = (bytes:number) => bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;

export default function ProductAnalysisEditor({id}:{id?:string}){
  const state=useCreationProject(id||'');const {project}=state;const skill=useCreationSkill();
  const [name,setName]=useState('');const [sku,setSku]=useState('');const [goal,setGoal]=useState('');
  const [planner,setPlanner]=useState('');const [config,setConfig]=useState<ImageConfiguration|null>(null);
  const plannerTouched=useRef(false);
  const [instruction,setInstruction]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');
  const [uploading,setUploading]=useState<{done:number;total:number}|null>(null);
  const [files,setFiles]=useState<{file:File;kind:string}[]>([]);const [pendingKind,setPendingKind]=useState('产品实拍');const [fileError,setFileError]=useState('');const created=useRef<Project|null>(null);
  const [analysis,setAnalysis]=useState({facts:'',selling_points:'',questions:''});const [analysisDirty,setAnalysisDirty]=useState(false);
  const doc=project?.documents.analysis;
  useEffect(()=>{let active=true;imageConfigRequest<ImageConfiguration|null>().then(value=>{if(active)setConfig(value);}).catch(err=>{if(active)setError(err.message);});return()=>{active=false;};},[]);
  useEffect(()=>{if(project){setName(project.title);setSku(project.settings.sku||'');setGoal(project.settings.goal);}},[project?.id,project?.revision]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>{
    if(!config)return;
    const names=config.model_names;
    const preferred=[project?.settings.planning_model,config.planning_model_name].find(name=>!!name&&names.includes(name))||'';
    setPlanner(previous=>plannerTouched.current?(previous&&names.includes(previous)?previous:preferred):preferred);
  },[config,project?.id,project?.settings.planning_model]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>{setAnalysis({facts:doc?.content.facts||'',selling_points:doc?.content.selling_points||'',questions:doc?.content.questions||''});setAnalysisDirty(false);},[doc?.id]);
  const infoDirty=!!project&&(name!==project.title||sku!==(project.settings.sku||'')||goal!==project.settings.goal);
  useUnsavedChanges(infoDirty||analysisDirty||(!id&&(!!name||!!goal||!!files.length)));
  const locked=busy||state.locked;
  const steps=[{label:'产品信息',target:'product-info',done:!infoDirty},{label:'资料准备',target:'product-materials',done:!!project?.materials.length||!!project?.settings.goal.trim()},{label:'产品分析与卖点',target:'product-analysis',done:!!doc?.confirmed_at&&!analysisDirty}];
  const currentStep=steps.findIndex(item=>!item.done);
  const hasRecords=!!project&&(project.executions.some(item=>item.stage==='analysis')||project.history.some(item=>item.stage==='analysis'));
  function goStep(target:string){document.getElementById(target)?.scrollIntoView({behavior:'smooth',block:'start'});}
  function addFiles(list:FileList|null){
    const incoming=Array.from(list||[]);if(!incoming.length)return;
    const rejected:string[]=[];const accepted:{file:File;kind:string}[]=[];
    for(const file of incoming){
      if(!/\.(pdf|png|jpe?g|webp)$/i.test(file.name)){rejected.push(`${file.name}（格式不支持）`);continue;}
      if(file.size>20*1024*1024){rejected.push(`${file.name}（超过 20 MB）`);continue;}
      accepted.push({file,kind:pendingKind});
    }
    if(accepted.length)setFiles(previous=>[...previous,...accepted]);
    setFileError(rejected.length?`有 ${rejected.length} 个文件未加入：${rejected.slice(0,3).join('、')}${rejected.length>3?' 等':''}`:'');
  }
  async function create(){
    setBusy(true);setError('');let value=created.current;
    const total=files.length;let done=0;
    try{
      value=value?await projectRequest<Project>('/'+value.id):await projectRequest<Project>('','POST',{kind:'product',title:name,sku,goal});
      created.current=value;
      const remaining=[...files];
      while(remaining.length){const entry=remaining[0];setUploading({done,total});value=await uploadProjectMaterials(value,[entry.file],entry.kind);created.current=value;remaining.shift();done+=1;setUploading({done,total});setFiles([...remaining]);}
      window.location.hash='#/products?project='+value.id;
    }catch(err){setError((err instanceof Error?err.message:'保存失败')+(value?' 产品已保存，可打开产品继续添加资料。':''));}
    finally{setBusy(false);setUploading(null);}
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
    {!id?<><div className="guided-toolbar guided-card-narrow"><div><h3>新建产品</h3><p>填写名称并上传现有资料。保存产品不调用模型，之后在同一详情页分析和确认卖点。</p></div><a className="button-secondary" href="#/products">返回产品列表</a></div><section className="guided-card guided-card-narrow"><fieldset disabled={busy}><div className="guided-form-grid"><label>产品名称<input required maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></label><label>SKU（选填）<input maxLength={100} value={sku} onChange={e=>setSku(e.target.value)}/></label></div><label>产品说明<textarea rows={4} maxLength={12000} value={goal} onChange={e=>setGoal(e.target.value)} placeholder="补充产品事实、已知参数或需要注意的结构特点。"/></label><div className="material-upload-block"><span className="material-upload-title">产品参考资料</span><div className="material-uploader"><select aria-label="资料类型" title="资料类型" value={pendingKind} onChange={e=>setPendingKind(e.target.value)}>{['说明书','规格书','产品实拍','产品图','结构细节','其他'].map(kind=><option key={kind}>{kind}</option>)}</select><span className="material-uploader-divider" aria-hidden="true"/><input aria-label="上传文件" type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" multiple onChange={e=>{addFiles(e.target.files);e.target.value='';}}/></div><p className="pending-hint">支持 PDF、PNG、JPG、JPEG、WebP，单个不超过 20 MB，可一次选择多个文件。</p>{fileError&&<p className="feedback feedback-warning" role="alert">{fileError}</p>}</div>{files.map((entry,index)=>{const current=!!uploading&&index===0;return <div className={`pending-material${current?' pending-material-uploading':''}`} key={index} aria-busy={current}><span className="pending-name">{entry.file.name}{current?<small className="pending-badge pending-badge-busy"><span className="upload-spinner" aria-hidden="true"/>上传中…</small>:<small className="pending-badge">{uploading?'等待上传':'待上传'}</small>}</span><span className="pending-kind">{entry.kind}</span><button type="button" onClick={()=>setFiles(previous=>previous.filter((_,i)=>i!==index))}>移除</button></div>;})}{uploading&&<p className="upload-progress" role="status" aria-live="polite"><span className="upload-spinner" aria-hidden="true"/>正在上传资料 {Math.min(uploading.done+1,uploading.total)} / {uploading.total}，请保持页面打开…</p>}<div className="guided-actions form-actions-sticky">{files.length>0&&!uploading&&<small className="form-actions-note">已选 {files.length} 个文件 · {sizeText(files.reduce((sum,item)=>sum+item.file.size,0))}</small>}{!busy&&<a className="button-secondary" href="#/products">取消</a>}<button type="button" className="button-primary" disabled={!name.trim()} onClick={()=>void create()}>{busy?(uploading?`上传中 ${Math.min(uploading.done+1,uploading.total)}/${uploading.total}…`:'保存中…'):'保存产品'}</button>{created.current&&<a href={'#/products?project='+created.current.id}>打开已保存产品</a>}</div></fieldset></section></>:project&&<>
      <div className="guided-toolbar"><div><h3>{project.title}</h3><p>产品资料与分析结果统一保存在这里。</p></div><a className="button-secondary" href="#/products">返回产品列表</a></div>
      {project.can_edit===false&&<p className="feedback">团队共享产品，可查看资料并建立策划方案，修改请联系创建者。</p>}
      <nav className="product-steps" aria-label="产品分析流程">{steps.map((step,index)=><button type="button" key={step.label} className={'product-step'+(step.done?' is-done':'')+(index===currentStep?' is-current':'')} aria-current={index===currentStep?'step':undefined} onClick={()=>goStep(step.target)}><b>{step.done?'✓':index+1}</b>{step.label}</button>)}</nav>
      <div className="product-inputs">
      <section className="guided-card" id="product-info"><header><h3>产品信息</h3></header><fieldset disabled={locked}><div className="guided-form-grid"><label>产品名称<input maxLength={120} value={name} onChange={e=>setName(e.target.value)}/></label><label>SKU<input maxLength={100} value={sku} onChange={e=>setSku(e.target.value)}/></label></div><label>产品说明<textarea rows={4} maxLength={12000} value={goal} onChange={e=>setGoal(e.target.value)}/></label><button type="button" className="button-secondary" disabled={!infoDirty} onClick={()=>void saveInfo()}>保存产品信息</button></fieldset></section>
      <ProjectMaterials id="product-materials" project={project} locked={locked||infoDirty||analysisDirty} onUpload={(items,kind)=>state.mutate(()=>uploadProjectMaterials(project,items,kind),'资料已保存，需重新确认分析结果。')} onRemove={materialId=>void state.mutate(()=>projectRequest<Project>(`/${project.id}/materials/${materialId}?revision=${project.revision}`,'DELETE'),'资料已移除。')}/>
      </div>
      <section className="guided-card" id="product-analysis"><header><h3>产品分析与卖点</h3>{doc&&<span>版本 {doc.version} · {doc.confirmed_at&&!analysisDirty?'已确认':'待确认'}</span>}</header>
        <div className="analysis-model">
          <span>分析模型</span>
          {config&&config.model_names.length>0?<select value={planner} disabled={locked} aria-label="分析模型" onChange={e=>{plannerTouched.current=true;setPlanner(e.target.value);}}><option value="">请选择模型</option>{config.model_names.map(model=><option key={model}>{model}</option>)}</select>:config?<a className="analysis-model-link is-empty" href="#/settings">未配置模型，去配置 →</a>:<strong>正在读取模型…</strong>}
          <small>用于读取全部资料并提炼事实与卖点，后续策划默认沿用。</small>
        </div>
        <details className="workflow-options"><summary>技能设置 · {skill.mode==='manual'?`已指定 ${skill.selectedIds.length} 个技能`:'自动匹配'}</summary><p>AI 按产品分析任务选择适用技能，不需要每次手动指定。</p><CreationSkillPicker/></details>
        <label>本轮分析要求<textarea rows={3} maxLength={12000} value={instruction} disabled={locked} onChange={e=>setInstruction(e.target.value)} placeholder="例如：核对说明书与实拍中的结构，区分已知事实、候选卖点和待确认参数。"/></label>
        {infoDirty&&<p className="feedback feedback-warning">产品信息尚未保存，先保存再分析。</p>}
        <div className="guided-actions"><button type="button" className="button-primary" disabled={locked||infoDirty||analysisDirty||!planner||!skill.ready||(!project.materials.length&&!goal.trim())} onClick={()=>void analyze()}>{project.busy?'正在分析…':doc?'按要求重新分析':'分析产品，提炼卖点'}</button></div>
        {(doc||analysisDirty)&&<fieldset disabled={locked}>{([{key:'facts',label:'产品事实与来源'},{key:'selling_points',label:'候选卖点与依据'},{key:'questions',label:'待确认问题'}] as const).map(field=><label key={field.key}>{field.label}<textarea rows={field.key==='questions'?3:7} value={analysis[field.key]} onChange={e=>{setAnalysis(previous=>({...previous,[field.key]:e.target.value}));setAnalysisDirty(true);}}/></label>)}<div className="guided-actions"><button type="button" className="button-secondary" disabled={!analysisDirty} onClick={()=>void saveAnalysis(false)}>保存修改</button><button type="button" className="button-primary" disabled={infoDirty||!analysis.facts.trim()||!analysis.selling_points.trim()} onClick={()=>void saveAnalysis(true)}>确认产品卖点</button></div></fieldset>}
        {doc?.confirmed_at&&!analysisDirty&&!infoDirty&&<a className="button-primary" href={'#/planning?new=1&product='+project.id}>为此产品新建策划方案 →</a>}
        {!doc&&!analysisDirty&&<details><summary>手动录入已确认的产品事实和卖点</summary><button type="button" disabled={locked} onClick={()=>setAnalysisDirty(true)}>开始填写</button></details>}
      </section>
      <p className="section-divider">后续参考 · 用于之后的策划与直接创作</p>
      <ProductExperience productId={project.id} readOnly={project.can_edit===false}/>
      {hasRecords&&<p className="section-divider">记录 · 仅供追溯</p>}
      <ProjectLog project={project} stages={['analysis']}/><ProjectHistory project={project} stages={['analysis']}/>
    </>}
  </div>;
}
