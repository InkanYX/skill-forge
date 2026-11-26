import { createRequestId } from './requestId';
import { useEffect, useRef, useState } from 'react';
import { caseRequest, type WorkflowCase } from './workflowCaseApi';
import { projectRequest, stageNames, type Project } from './creationProjectApi';
import { formatTaskTime } from './imageTaskApi';

export default function WorkflowCases({route}:{route:string}) {
  const id=new URLSearchParams(route.split('?')[1]).get('case');
  const [items,setItems]=useState<WorkflowCase[]>([]);const [selected,setSelected]=useState<WorkflowCase>();
  const [products,setProducts]=useState<Project[]>([]);const [product,setProduct]=useState('');
  const [query,setQuery]=useState('');const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  const [preview,setPreview]=useState('');const requestId=useRef<string|undefined>(undefined);
  useEffect(()=>{let active=true;setError('');setSelected(undefined);requestId.current=undefined;
    Promise.all([caseRequest<WorkflowCase[]>(),id?caseRequest<WorkflowCase>('/'+id):Promise.resolve(undefined),projectRequest<Project[]>('?kind=product&ready=true')])
      .then(([list,detail,values])=>{if(active){setItems(list);setSelected(detail);setProducts(values);}}).catch(err=>{if(active)setError(err.message);});
    return()=>{active=false;};},[id]);
  async function reuse(){if(!selected||!product)return;setBusy(true);setError('');requestId.current??=createRequestId();
    try{const plan=await caseRequest<Project>('/'+selected.id+'/reuse','POST',{request_id:requestId.current,title:(selected.title+' · 参考方案').slice(0,120),product_id:product});window.location.hash='#/planning?project='+plan.id;}
    catch(err){setError(err instanceof Error?err.message:'复用失败');}finally{setBusy(false);}}
  return <section><div className="section-heading"><div><p className="eyebrow">WORKFLOW CASES</p><h2>完整案例</h2></div>{selected&&<a className="button-secondary" href="#/showcases">返回案例库</a>}</div><p className="settings-intro">团队共享案例库：所有成员可查看、下载完整流程，并为自己的产品创建参考方案。</p>
    {error&&<p className="feedback feedback-error" role="alert">{error}</p>}
    {selected?<>
      <section className="guided-card"><h3>{selected.title}</h3><p className="workflow-preserve-lines">{selected.summary||'完整制作流程快照'}</p><small>{formatTaskTime(selected.created_at)} · {selected.image_count} 张图片 · {selected.material_count} 份资料</small>
        <p>团队共享案例 · 作者：{selected.author?.name||'原作者'}</p><div className="guided-actions"><a className="button-primary" href={'/api/workflow-cases/'+selected.id+'/download'}>下载完整案例ZIP</a>{selected.can_edit&&<a href={'#/studio?project='+selected.project_id}>查看来源方案</a>}</div>
        <div className="delivery-option"><h4>参考此案例，为目标产品策划</h4><p>借鉴风格、版式和归档经验，带入最多3张案例成图作风格参考；产品事实取自你选择的已确认分析。确认图需后，选用的参考图会随生图发送给你配置的服务商。</p>
          <label>目标产品<select value={product} onChange={e=>{setProduct(e.target.value);requestId.current=undefined;}}><option value="">选择已确认分析的产品</option>{products.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select></label><button type="button" className="button-secondary" disabled={busy||!product} onClick={()=>void reuse()}>{busy?'正在创建…':'以此案例创建新方案'}</button>
        </div>
      </section>
      <section className="guided-card"><h3>成果展示</h3><div className="task-image-grid">{selected.snapshot?.images.filter(i=>i.status==='succeeded').map(i=><article className="task-image-card" key={i.id}><button type="button" className="task-image-preview" onClick={()=>setPreview(i.id)}><img loading="lazy" src={'/api/workflow-cases/'+selected.id+'/images/'+i.id} alt={i.shot_name||'案例图片'}/></button><div className="task-image-caption"><strong>{i.shot_name||'案例图片'}</strong><small>{i.size} · {i.model_name}</small><details><summary>提示词与质检</summary><p className="workflow-preserve-lines">{i.prompt}</p><pre>{JSON.stringify(i.execution_result?.agent_review||i.execution_result?.review||{},null,2)}</pre></details></div></article>)}</div></section>
      <section className="guided-card"><h3>原始资料与制作过程</h3><ul>{selected.snapshot?.materials.map(m=><li key={m.id}>{m.name} · {m.kind} · {m.pages} 页</li>)}</ul><p>原始文件、参考图、技能文件和完整清单包含在下载包中。</p>{selected.snapshot?.history.map(doc=><details key={doc.id}><summary>{stageNames[doc.stage]} · 第 {doc.version} 版 · {doc.confirmed_at?'已确认':'草稿'}</summary><pre className="workflow-preserve-lines">{JSON.stringify(doc.content,null,2)}</pre></details>)}{selected.snapshot?.related_projects?.map(p=><details key={p.id}><summary>关联方案：{p.title}</summary>{p.history.map(doc=><details key={doc.id}><summary>{stageNames[doc.stage]} · 第 {doc.version} 版</summary><pre className="workflow-preserve-lines">{JSON.stringify(doc.content,null,2)}</pre></details>)}</details>)}<details><summary>修正反馈与经验</summary><pre className="workflow-preserve-lines">{JSON.stringify(selected.snapshot?.feedback||[],null,2)}</pre></details></section>
      {preview&&<div className="case-preview-overlay" role="dialog" aria-modal="true" aria-label="案例图片预览"><button type="button" className="button-secondary" onClick={()=>setPreview('')}>关闭预览</button><img src={'/api/workflow-cases/'+selected.id+'/images/'+preview+'?preview=false'} alt="案例原图"/></div>}
    </>:<section className="guided-card"><p>从已完成的方案保存完整案例，在这里展示、下载，并作为后续策划参考。</p><label>搜索案例<input value={query} onChange={e=>setQuery(e.target.value)} placeholder="名称、经验或适用范围"/></label><div className="workflow-record-table">{items.filter(c=>(c.title+' '+c.summary).toLowerCase().includes(query.toLowerCase())).map(c=><a key={c.id} href={'#/showcases?case='+c.id}><div><strong>{c.title}</strong><small>{c.summary.slice(0,100)}</small></div><span>{c.image_count} 图 · {c.material_count} 份资料</span><time>{formatTaskTime(c.created_at)}</time></a>)}</div>{!items.length&&<p>还没有完整案例。完成生图后，点击“将整个流程打包为案例”。</p>}</section>}
  </section>;
}
