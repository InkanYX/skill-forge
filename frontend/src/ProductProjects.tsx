import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { imageConfigRequest, type ImageConfiguration } from './imageConfigApi';
import { listPackages, type SkillPackage } from './skillPackageApi';
import { listConfigs, type ModelConfig } from './modelConfigApi';
import { evidenceLabels, jsonRequest, projectBusy, projectRequest, projectStatus, roleLabels } from './productProjectApi';
import type { PlanArtifact, PointsArtifact, ProductProject, ProjectSummary } from './productProjectApi';
import './productProjects.css';

const actionLabels: Record<string, string> = {analyze:'理解资料与提炼卖点', discuss_points:'调整卖点', plan:'规划逐图图需', discuss_plan:'调整图需', generate:'编写提示词、制作与质检'};
type Apply = (task: () => Promise<ProductProject>) => Promise<void>;

function PointsEditor({project, disabled, onSave, onApprove}: {project: ProductProject; disabled: boolean;
  onSave: (value: PointsArtifact) => void; onApprove: (ids: string[]) => void}) {
  const [draft, setDraft] = useState<PointsArtifact>(structuredClone(project.points!));
  const [selected, setSelected] = useState(project.approved_point_ids.length ? project.approved_point_ids : draft.points.filter(p => p.status === 'supported' && p.priority !== 'excluded').map(p => p.id));
  const [dirty, setDirty] = useState(false);
  const change = (index: number, key: string, value: string) => {
    setDraft(d => ({...d, points:d.points.map((p,i) => i === index ? {...p,[key]:value} : p)})); setDirty(true);
  };
  return <section className="project-panel">
    <div className="section-heading"><div><span className="project-eyebrow">02 / SELLING POINTS · V{project.points_version}</span><h3>先选对购买理由</h3></div><span className="project-badge">{project.points_approval === project.points_version ? '本版已确认' : '等待你的确认'}</span></div>
    <p>{draft.summary}</p>
    <details className="project-source-detail"><summary>商品身份与证据账本 · {draft.claims.length} 项</summary><p className="project-preserve">{draft.identity}</p>{draft.claims.map(c => <div key={c.id} className="project-evidence"><strong>{c.id} · {evidenceLabels[c.status]}</strong><p>{c.text}</p><small>来源：{c.source_ids.join('、')} {c.boundary && ` / 边界：${c.boundary}`}</small></div>)}</details>
    <fieldset disabled={disabled} className="set-fieldset">
      <div className="project-point-grid">{draft.points.map((point, index) => <article key={point.id} className={`project-point ${point.status === 'supported' ? '' : 'project-point-unverified'}`}>
        <div className="project-point-meta"><label className="project-check"><input type="checkbox" disabled={point.status !== 'supported' || point.priority === 'excluded'} checked={selected.includes(point.id)} onChange={e => setSelected(s => e.target.checked ? [...s, point.id] : s.filter(id => id !== point.id))} />纳入图需</label><span>{evidenceLabels[point.status]}</span></div>
        <label className="form-field">卖点标题<input value={point.title} maxLength={200} onChange={e => change(index,'title',e.target.value)} /></label>
        <label className="form-field">商品特征<textarea rows={2} value={point.feature} maxLength={1500} onChange={e => change(index,'feature',e.target.value)} /></label>
        <label className="form-field">买家收益<textarea rows={2} value={point.benefit} maxLength={1500} onChange={e => change(index,'benefit',e.target.value)} /></label>
        <label className="form-field">画面怎么证明<textarea rows={2} value={point.visual} maxLength={1800} onChange={e => change(index,'visual',e.target.value)} /></label>
        <small>证据：{point.claim_ids.join('、')}{point.conditions && ` · 条件 / 待证：${point.conditions}`}</small>
      </article>)}</div>
      {draft.unknowns.length > 0 && <div className="project-unknowns"><strong>待补充 / 冲突</strong><ul>{draft.unknowns.map((u,i) => <li key={i}>{u}</li>)}</ul></div>}
      <div className="form-actions"><button type="button" className="button-secondary" disabled={!dirty} onClick={() => onSave(draft)}>保存卖点修改</button><button type="button" className="button-primary" disabled={dirty || !selected.length} onClick={() => onApprove(selected)}>确认所选卖点（{selected.length} 项）</button></div>
      {dirty && <p className="form-footnote">请先保存修改，再确认当前卖点版本。</p>}
    </fieldset>
  </section>;
}

const shotFields = [ ['question','购买问题'], ['scene','场景与差异'], ['camera','商品状态与机位'], ['composition','构图、层级与安全区'], ['lighting','光影与材质外观'], ['props','道具 / 人物边界'], ['typography','字体与排版'], ['information_gain','本张信息增量'] ] as const;
function PlanEditor({project, disabled, onSave, onGenerate}: {project: ProductProject; disabled: boolean;
  onSave: (value: PlanArtifact) => void; onGenerate: () => void}) {
  const [draft, setDraft] = useState<PlanArtifact>(structuredClone(project.plan!));
  const [dirty, setDirty] = useState(false);
  const change = (index: number, key: string, value: unknown) => {
    setDraft(d => ({...d, shots:d.shots.map((s,i) => i === index ? {...s,[key]:value} : s)})); setDirty(true);
  };
  const alreadySubmitted = project.outputs.some(o => o.plan_version === project.plan_version);
  return <section className="project-panel">
    <div className="section-heading"><div><span className="project-eyebrow">03 / IMAGE BRIEF · V{project.plan_version}</span><h3>让每张图都有明确任务</h3></div><span className="project-badge">{draft.shots.length} 张制作卡</span></div>
    <p>{draft.summary}</p>
    <fieldset disabled={disabled} className="set-fieldset">
      <label className="form-field">整套视觉系统<textarea rows={5} value={draft.visual_system} maxLength={8000} onChange={e => {setDraft(d => ({...d,visual_system:e.target.value}));setDirty(true);}} /></label>
      <div className="project-shot-list">{draft.shots.map((shot,index) => <details key={shot.id} className="project-shot" open={draft.shots.length === 1 || undefined}>
        <summary><span className="project-shot-number">{String(index+1).padStart(2,'0')}</span><span><strong>{shot.name}</strong><small>{shot.question}</small></span><span className="project-shot-ratio">{shot.kind === 'main' ? '主图' : shot.kind === 'a-plus' ? 'A+' : '附图'} · {shot.aspect_ratio}</span></summary>
        <div className="project-shot-content">
          <div className="project-field-pair"><label className="form-field">图片名称<input value={shot.name} maxLength={100} onChange={e => change(index,'name',e.target.value)} /></label><label className="form-field">画幅比例<input value={shot.aspect_ratio} pattern="\d{1,4}:\d{1,4}" onChange={e => change(index,'aspect_ratio',e.target.value)} /></label></div>
          <label className="form-field">实际产品身份参考图<select value={shot.reference_asset_id} onChange={e => change(index,'reference_asset_id',e.target.value)}>{project.assets.filter(a => a.role === 'product_identity' && a.kind === 'image').map(a => <option key={a.id} value={a.id}>{a.name}</option>)}</select><small>该文件实际传入编辑接口；其余资料作为分析依据保存。</small></label>
          {shotFields.map(([key,label]) => <label className="form-field" key={key}>{label}<textarea rows={3} value={shot[key]} maxLength={key === 'scene' || key === 'composition' ? 2500 : key === 'question' ? 1200 : 1800} onChange={e => change(index,key,e.target.value)} /></label>)}
          <strong>成品逐字文案</strong>{shot.kind === 'main' ? <p className="form-footnote">白底主图不新增文字或道具。</p> : shot.copy.map((c,ci) => <label key={ci} className="form-field">文案 {ci+1}<textarea rows={2} maxLength={600} value={c.text} onChange={e => change(index,'copy',shot.copy.map((item,i) => i===ci ? {...item,text:e.target.value} : item))} /><small>证据：{c.claim_ids.join('、') || '氛围表达；不宣称产品性能'}</small></label>)}
          <label className="form-field">验收要求（每行一条）<textarea rows={4} value={shot.acceptance.join('\n')} onChange={e => change(index,'acceptance',e.target.value.split('\n'))} /></label>
          <small>卖点 {shot.point_ids.join('、')} / 证据 {shot.claim_ids.join('、')}</small>
        </div>
      </details>)}</div>
      <div className="project-confirm-box"><p><strong>确认后开始编写提示词并调用图片接口</strong><br />{project.image_model_name} · 共 {draft.shots.length} 张 · high / auto / PNG<br />接收方：{project.authorization?.receivers.image || '待确认'}。使用本项目已授权的参考图进行编辑。</p><div className="form-actions"><button type="button" className="button-secondary" disabled={!dirty} onClick={() => onSave(draft)}>保存图需修改</button><button type="button" className="button-primary" disabled={dirty || alreadySubmitted || project.points_approval !== project.points_version} onClick={onGenerate}>确认图需并开始生成，共 {draft.shots.length} 张</button></div>{alreadySubmitted && <small>本版已提交。查看下方记录；修改图需形成新版本后，仅变化的图片重新制作。</small>}</div>
    </fieldset>
  </section>;
}

function Results({project, apply, disabled}: {project: ProductProject; apply: Apply; disabled: boolean}) {
  const [selected, setSelected] = useState('');
  const [notes, setNotes] = useState('');
  const output = project.outputs.find(o => o.id === selected) || project.outputs[project.outputs.length-1];
  if (!output) return null;
  return <section className="project-panel"><span className="project-eyebrow">04 / PRODUCTION & REVIEW</span><h3>制作记录与逐图验收</h3>
    <div className="project-output-tabs" role="group" aria-label="选择一张图片查看">{project.outputs.map(o => <button key={o.id} type="button" aria-pressed={o.id === output.id} onClick={() => {setSelected(o.id);setNotes(o.human_notes || '');}}>{o.name} · V{o.plan_version}</button>)}</div>
    <div className="project-result-grid"><div>{output.job?.preview_url ? <img className="project-result-image" src={output.job.preview_url} alt={`${output.name} JPEG 质检预览`} /> : <div className="project-result-placeholder">{output.job?.status || '正在编写提示词'}</div>}<p className="form-footnote">一次展示一张 JPEG 预览。{output.native_pixels ? `实际原生尺寸：${output.native_pixels.join(' × ')} px。` : '原生尺寸待接口返回。'}</p></div>
      <div><h4>{output.name} · 图需 V{output.plan_version}</h4><p>生成：{output.job?.status || '准备中'} · 人工验收：{output.human_review === 'passed' ? '通过' : output.human_review === 'rework' ? '需要返工' : '待审核'}</p>{output.inherited_from && <p className="form-footnote">图需未变化，复用已完成结果，没有重新调用图片接口。</p>}
      {output.job?.message && <p>{output.job.message}</p>}<p className="project-preserve">{output.qc.report || '自动质检尚未完成。'}</p><p className="form-footnote">自动质检建议与人工验收分别记录。存在 P0/P1 时请标记返工。</p>
      <div className="form-actions">{output.job?.image_url && <a className="button-secondary" href={output.job.image_url} target="_blank" rel="noreferrer">查看原生 PNG</a>}{output.prompt && <a className="button-secondary" href={`/api/product-projects/${project.id}/outputs/${output.id}/prompt`} target="_blank" rel="noreferrer">完整提示词</a>}{output.job_id && <a className="button-secondary" href={`#/edit?source=${output.job_id}`}>局部修改此图</a>}</div>
      <label className="form-field">验收记录<textarea rows={3} value={notes} maxLength={4000} onChange={e => setNotes(e.target.value)} placeholder="记录结构、文字、比例及 P0/P1 缺陷，或通过依据。" /></label>
      <div className="form-actions">{(['passed','rework'] as const).map(status => <button key={status} type="button" className="button-secondary" disabled={disabled || output.job?.status !== 'succeeded'} onClick={() => void apply(() => projectRequest(`/${project.id}/outputs/${output.id}/review`,jsonRequest({revision:project.revision,status,notes})))}>{status === 'passed' ? '人工验收通过' : '标记需要返工'}</button>)}</div></div>
    </div>
  </section>;
}

export default function ProductProjects({route}: {route: string}) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<ProductProject>();
  const [config, setConfig] = useState<ImageConfiguration | null>(null);
  const [connections, setConnections] = useState<ModelConfig[]>([]);
  const [skills, setSkills] = useState<SkillPackage[]>([]);
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);
  const [authorized, setAuthorized] = useState(false);
  const [role, setRole] = useState('product_identity');
  const [discussion, setDiscussion] = useState('');
  const [target, setTarget] = useState('points');
  const [selectedId, setSelectedId] = useState(new URLSearchParams(route.split('?')[1]).get('project') || '');
  const [create, setCreate] = useState({title:'',sku:'',brief:'',skill_id:'',image_model_name:'',image_count:6});
  const fileInput = useRef<HTMLInputElement>(null);
  const active = useRef(selectedId); active.current = selectedId;
  useEffect(() => {
    const identifier = new URLSearchParams(route.split('?')[1]).get('project') || '';
    if (identifier !== active.current) {
      setSelectedId(identifier);setProject(undefined);setAuthorized(false);setError('');setDiscussion('');
    }
  }, [route]);
  const loadList = async () => setProjects(await projectRequest<ProjectSummary[]>());
  useEffect(() => {
    void Promise.all([projectRequest<ProjectSummary[]>(), imageConfigRequest<ImageConfiguration | null>(), listPackages(), listConfigs()]).then(([p,c,s,con]) => {
      setProjects(p);setConfig(c);setConnections(con);
      const enabled=s.filter(item => item.current_version?.status === 'ready');setSkills(enabled);
      setCreate(d => ({...d,skill_id:enabled.find(item => item.name === 'premium-product-image-workflow')?.id || enabled[0]?.id || '',image_model_name:c?.model_name || ''}));
    }).catch(e => setError(String(e.message || e)));
  },[]);
  useEffect(() => {
    if (!selectedId) {setProject(undefined);return;}
    let stopped=false;
    const load=async () => {try {const p=await projectRequest<ProductProject>(`/${selectedId}`);if(!stopped) setProject(p);}catch(e){if(!stopped)setError(e instanceof Error ? e.message : '项目读取失败');}};
    void load();
    return () => {stopped=true;};
  },[selectedId]);
  const busy=!!project && projectBusy(project);
  useEffect(() => {
    if(!selectedId || !busy) return;
    let pending=false,stopped=false;
    const timer=window.setInterval(async () => {
      if(pending) return; pending=true;
      try {const p=await projectRequest<ProductProject>(`/${selectedId}`);if(!stopped)setProject(p);}catch(e){if(!stopped)setError(e instanceof Error?e.message:'刷新失败');}finally{pending=false;}
    },2500);
    return () => {stopped=true;window.clearInterval(timer);};
  },[selectedId,busy]);
  const select=(id:string) => {setSelectedId(id);setProject(undefined);setAuthorized(false);setError('');setDiscussion('');window.location.hash=`#/projects${id ? `?project=${id}` : ''}`;};
  const apply: Apply=async task => {setWorking(true);setError('');try{const p=await task();if(active.current===p.id)setProject(p);await loadList();}catch(e){setError(e instanceof Error?e.message:'操作失败');if(active.current){try{const latest=await projectRequest<ProductProject>(`/${active.current}`);if(active.current===latest.id)setProject(latest);}catch{/* Preserve the visible project if the refresh also fails. */}}}finally{setWorking(false);}};
  const command=(action:string,extra:Record<string,unknown>={}) => project && apply(() => projectRequest(`/${project.id}/commands`,jsonRequest({revision:project.revision,action,...extra})));
  const submit=async(e:FormEvent) => {e.preventDefault();if(!config)return;setWorking(true);setError('');try{const p=await projectRequest<ProductProject>('',jsonRequest({...create,config_id:config.id}));select(p.id);setProject(p);await loadList();}catch(e){setError(e instanceof Error?e.message:'创建失败');}finally{setWorking(false);}};
  const upload=async(files:FileList|null) => {
    if(!files?.length || !project)return;
    setWorking(true);setError('');let current=project;
    try{for(const file of Array.from(files)){const form=new FormData();form.set('revision',String(current.revision));form.set('asset_id',crypto.randomUUID());form.set('role',role);form.set('file',file);current=await projectRequest(`/${current.id}/assets`,{method:'POST',body:form});setProject(current);}setAuthorized(false);await loadList();}
    catch(e){setError(e instanceof Error?e.message:'资料上传失败');}finally{setWorking(false);if(fileInput.current)fileInput.current.value='';}
  };
  const textConnection=connections.find(c=>c.id===config?.text_config_id)?.base_url || config?.base_url;
  const stage=!project ? 0 : ['review','completed'].includes(project.status) ? 4 : project.plan_approval===project.plan_version && project.plan_version>0 ? 3 : project.points_approval===project.points_version && project.points_version>0 ? 2 : project.points ? 1 : 0;
  return <section className="settings-section project-workspace" aria-labelledby="project-heading">
    <div className="section-heading"><div><span className="project-eyebrow">PRODUCT IMAGE WORKFLOW</span><h2 id="project-heading">商品图项目</h2><p className="settings-intro">先理解产品，再确认卖点和图需。把每次讨论沉淀为可追溯的制作依据。</p></div>{project && <button type="button" className="button-secondary" disabled={working} onClick={()=>select('')}>新建项目</button>}</div>
    {error && <p className="feedback feedback-error" role="alert">{error}</p>}
    {config && !config.has_api_key && <p className="feedback feedback-warning" role="status">运行时 API Key 尚未就绪。可先整理项目资料，开始 AI 分析前请到<a href="#/settings">个人模型配置</a>重新填入密钥。</p>}
    <div className="project-layout"><aside className="project-index"><span className="project-eyebrow">PROJECTS</span>{!projects.length && <p className="form-footnote">你的商品图项目会保存在这里。</p>}{projects.map(p=><button key={p.id} type="button" disabled={working} className={`config-item ${p.id===selectedId?'config-item-active':''}`} onClick={()=>select(p.id)}><strong>{p.title}</strong><small>{projectStatus[p.status] || p.status}</small></button>)}</aside>
    <div className="project-main">{!project ? <form className="project-panel" onSubmit={e=>void submit(e)}><h3>建立一个商品图项目</h3><fieldset disabled={working} className="set-fieldset"><div className="project-field-pair"><label className="form-field">项目名称<input required maxLength={120} value={create.title} onChange={e=>setCreate(d=>({...d,title:e.target.value}))} placeholder="例如：庭院凉棚 · 美国站套图" /></label><label className="form-field">SKU<input required maxLength={100} value={create.sku} onChange={e=>setCreate(d=>({...d,sku:e.target.value}))} /></label></div><label className="form-field">产品信息与初步想法<textarea rows={5} maxLength={8000} value={create.brief} onChange={e=>setCreate(d=>({...d,brief:e.target.value}))} placeholder="产品名称、目标平台、文案语言、不可变结构，以及目前想要的风格或场景。也可以后续与 AI 讨论。" /></label><label className="form-field">策划技能<select required value={create.skill_id} onChange={e=>setCreate(d=>({...d,skill_id:e.target.value}))}>{!skills.length && <option value="">请先在技能库启用技能</option>}{skills.map(s=><option key={s.id} value={s.id}>{s.name} · {s.current_version?.version_label}</option>)}</select></label><div className="project-field-pair"><label className="form-field">生图模型<select required value={create.image_model_name} onChange={e=>setCreate(d=>({...d,image_model_name:e.target.value}))}>{!config && <option value="">请先配置模型</option>}{config?.model_names.map(m=><option key={m} value={m}>{m}</option>)}</select></label><label className="form-field">规划图片数量<input type="number" min={1} max={8} value={create.image_count} onChange={e=>setCreate(d=>({...d,image_count:Number(e.target.value)}))} /></label></div><button className="button-primary" disabled={!config || !skills.length}>建立项目，开始整理资料</button></fieldset><p className="form-footnote">建立项目不调用 AI。上传资料后，由你授权开始分析。<a href="#/settings">管理文字 / 视觉 / 生图模型</a></p></form> : <>
      <header className="project-title"><div><h3>{project.title}</h3><span>{project.sku} · {project.skill.name} / {project.skill.version_label}</span></div><span className="project-badge">{projectStatus[project.status]}</span></header>
      <ol className="project-progress">{['产品资料','确认卖点','规划图需','制作质检','人工验收'].map((name,i)=><li key={name} aria-current={i===stage?'step':undefined} className={i<=stage?'project-step-active':''}><span>{i+1}</span>{name}</li>)}</ol>
      {project.error && <p className="feedback feedback-warning" role="status">{project.error}</p>}
      {busy && <div className="project-processing" role="status"><span className="project-pulse" />{actionLabels[project.action] || '处理中'} · 已完成的资料与步骤会自动保存。<button type="button" disabled={working} onClick={()=>void command('cancel')}>停止后续步骤</button></div>}
      {project.status==='blocked' && project.interrupted_action==='generate' && <button className="button-secondary" type="button" disabled={working} onClick={()=>void command('resume')}>核对并恢复制作（复用现有图片任务）</button>}
      <section className="project-panel"><div className="section-heading"><div><span className="project-eyebrow">01 / SOURCE MATERIALS</span><h3>让 AI 先读懂你的产品</h3></div><span className="project-badge">{project.assets.length} 份资料</span></div>{project.brief && <p className="project-preserve">{project.brief}</p>}
        <fieldset disabled={working || busy} className="set-fieldset"><div className="project-upload"><label className="form-field">资料角色<select value={role} onChange={e=>setRole(e.target.value)}>{Object.entries(roleLabels).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label><label className="form-field">选择多份同角色资料<input ref={fileInput} type="file" multiple accept={role==='manual'||role==='specification'?'.pdf':'image/png,image/jpeg,image/webp'} onChange={e=>void upload(e.target.files)} /></label></div><small>PDF 每份最多 40 页，单文件 20 MB。原始文件保留，逐页提取文本并视觉识读图解或扫描页。产品实拍图与用于锁定 SKU 的商品图请选择「产品身份图」。</small></fieldset>
        <div className="project-source-list">{project.assets.map(a=><details key={a.id} className="project-source-detail"><summary><span>{a.kind==='pdf'?'PDF':'IMG'}</span><strong>{a.name}</strong><small>{roleLabels[a.role]} {a.pages?`· ${a.pages.length} 页`:''} · {a.analysis || a.pages?.every(p=>p.analysis)?'已分析':'待分析'}</small></summary><p className="form-footnote">来源 ID：{a.id} · SHA-256 {a.sha256}</p><p className="project-preserve">{a.analysis}</p>{a.pages?.map(p=><details key={p.page}><summary>第 {p.page} 页 · {p.analysis?'已识读':'待识读'}</summary><pre className="project-preserve">{p.text || '扫描 / 图形页，等待视觉识读'}</pre><p className="project-preserve">{p.analysis}</p></details>)}<div className="form-actions"><a href={`/api/product-projects/${project.id}/assets/${a.id}/original`} className="button-secondary">下载原始资料</a><button type="button" className="button-secondary" disabled={working||busy} onClick={()=>void apply(()=>projectRequest(`/${project.id}/assets/${a.id}?revision=${project.revision}`,{method:'DELETE'}))}>从当前资料移除</button></div></details>)}</div>
        <div className="project-authorization"><p>图片接收方：{config?.base_url || '请配置'}<br />文字 / 视觉接收方：{textConnection || '请配置'}。分析将逐张读取图片、逐页读取 PDF（当前共 {project.assets.reduce((n,a)=>n+(a.pages?.length || 1),0)} 次视觉读取），并调用文字模型提炼卖点。</p><label className="project-check"><input type="checkbox" checked={authorized} disabled={working||busy} onChange={e=>setAuthorized(e.target.checked)} />我拥有这些资料的使用权，授权向上述服务商提交本项目资料，用于分析、制图和质检。</label><button type="button" className="button-primary" disabled={working||busy||!authorized||!project.assets.some(a=>a.role==='product_identity')} onClick={()=>void command('analyze',{authorized:true})}>{project.points?'重新分析当前资料':'开始分析资料并提炼卖点'}</button></div>
      </section>
      {project.points && <PointsEditor key={`${project.id}-points-${project.points_version}`} project={project} disabled={working||busy} onSave={points=>void apply(()=>projectRequest(`/${project.id}/artifacts`,jsonRequest({revision:project.revision,points},'PUT')))} onApprove={ids=>void command('approve_points',{point_ids:ids})} />}
      {project.points_approval===project.points_version && project.points_version>0 && (!project.plan || project.plan_points_version!==project.points_version) && <section className="project-panel"><h3>卖点已确认，开始讨论图需</h3><p>在下方写出希望的风格、排版、场景和图序，再点击规划。你可以在看到制作卡后继续修改。旧图需若基于更早卖点版本，需要重新规划或逐项复核后保存。</p><label className="form-field">风格与图片要求<textarea rows={5} maxLength={8000} value={discussion} onChange={e=>setDiscussion(e.target.value)} placeholder="例如：温暖户外杂志风，米白与深灰色板；场景不要重复，每张附图有清晰的标题和细节证据。" /></label><button type="button" className="button-primary" disabled={working||busy} onClick={()=>void command('plan',{message:discussion})}>根据确认卖点规划 {project.image_count} 张图</button></section>}
      {project.plan && <PlanEditor key={`${project.id}-plan-${project.plan_version}`} project={project} disabled={working||busy} onSave={plan=>void apply(()=>projectRequest(`/${project.id}/artifacts`,jsonRequest({revision:project.revision,plan},'PUT')))} onGenerate={()=>void command('generate')} />}
      {project.points && <section className="project-panel project-discussion"><span className="project-eyebrow">DISCUSS & REFINE</span><h3>和 AI 一起细化</h3><div className="project-messages">{project.messages.map(m=><div key={m.id} className={`project-message project-message-${m.role}`}><small>{m.role==='user'?'你':'AI'}</small><p>{m.content}</p></div>)}</div><fieldset disabled={working||busy} className="set-fieldset"><label className="form-field">本次讨论<select value={target} onChange={e=>setTarget(e.target.value)}><option value="points">卖点与资料依据</option><option value="plan" disabled={!project.plan || project.points_approval!==project.points_version}>图片风格、排版、场景与图需</option></select></label><label className="form-field">补充或修改要求<textarea rows={4} maxLength={8000} value={discussion} onChange={e=>setDiscussion(e.target.value)} placeholder="例如：删除没有规格书证明的抗风卖点；或把第二张改成傍晚庭院，标题放左上，保留完整产品。" /></label><button type="button" className="button-secondary" disabled={!discussion.trim()} onClick={()=>void command(target==='plan'?'discuss_plan':'discuss_points',{message:discussion})}>发送并更新{target==='plan'?'图需':'卖点'}草稿</button></fieldset><p className="form-footnote">讨论不会直接生图。更新后需重新确认受影响的卖点或图需版本。</p></section>}
      <Results project={project} apply={apply} disabled={working||busy} />
      <details className="project-panel"><summary>确认与版本记录 · {project.history.length} 条</summary>{project.history.slice().reverse().map((h,i)=><p className="form-footnote" key={i}>{new Date(h.at).toLocaleString()} · {h.kind}{h.version?` · V${String(h.version)}`:''}</p>)}</details>
    </>}</div></div>
  </section>;
}
