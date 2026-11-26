import { useEffect, useRef, useState } from 'react';
import { apiFetch } from './apiFetch';
import { formatTaskTime } from './imageTaskApi';
import { stageNames, type ProjectDocument, type Stage } from './creationProjectApi';

interface SharedImage {id:string;shot_name:string;status:string;size:string;model_name:string;prompt:string;parent_job_id:string|null;review:Record<string,unknown>;references:string[];reference_roles:unknown[]}
interface SharedProject {
  id:string;project_id:string;title:string;kind:string;author:{id:string;name:string};can_manage:boolean;
  visibility:'team'|'private';version:number;source_revision:number;updated_at:string;image_count:number;material_count:number;
  snapshot?:{publish_error?:string;settings:Record<string,unknown>;history:(ProjectDocument&{stage:Stage})[];
    materials:{id:string;name:string;kind:string;pages:number}[];images:SharedImage[];
    batches:{execution_id:string;job_ids:string[];created_at:string;version_number?:number}[];feedback:unknown[];experiences:{content:Record<string,unknown>;status:string}[]};
}
async function request<T>(path='',method='GET',body?:unknown):Promise<T>{
  const response=await apiFetch('/api/team-shares'+path,{method,cache:'no-store',headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined});
  const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'操作未完成，请刷新后重试。');return value;
}
const label=(kind:string)=>kind==='product'?'产品分析':kind==='plan'?'图片策划':'完整创作';
const sourceLink=(item:SharedProject)=>`#/${item.kind==='product'?'products':item.kind==='plan'?'planning':'studio'}?project=${item.project_id}`;
const file=(id:string,key:string)=>'/api/team-shares/'+id+'/files/'+key;

export default function TeamSharing({route}:{route:string}){
  const params=new URLSearchParams(route.split('?')[1]);const id=params.get('share');const mine=params.get('mine')==='1';
  const [items,setItems]=useState<SharedProject[]>([]);const [selected,setSelected]=useState<SharedProject>();
  const [query,setQuery]=useState('');const [author,setAuthor]=useState('');const [kind,setKind]=useState('');
  const [error,setError]=useState('');const [busy,setBusy]=useState(false);const [loading,setLoading]=useState(true);
  const [copyTitle,setCopyTitle]=useState('');const [copying,setCopying]=useState(false);const [preview,setPreview]=useState('');
  const requestId=useRef<string|undefined>(undefined);
  const [products,setProducts]=useState<{id:string;title:string}[]>([]);const [productId,setProductId]=useState('');
  const [adopted,setAdopted]=useState<number[]>([]);const [adopting,setAdopting]=useState<number|null>(null);
  const adoptionIds=useRef<Record<string,string>>({});
  useEffect(()=>{let alive=true;setAdopted([]);setProductId('');
    apiFetch('/api/creation-projects?kind=product').then(async response=>{if(!response.ok)throw new Error('无法加载个人产品列表');return response.json();})
      .then(value=>{if(alive)setProducts(value);}).catch(err=>{if(alive)setError(err.message);});return()=>{alive=false;};
  },[id]);
  async function adopt(index:number){
    if(!selected||!productId||adopting!==null)return;setAdopting(index);setError('');
    const key=`${selected.id}:${selected.version}:${productId}:${index}`;adoptionIds.current[key]??=crypto.randomUUID();
    try{await request('/'+selected.id+'/experiences','POST',{request_id:adoptionIds.current[key],version:selected.version,product_id:productId,index});setAdopted(values=>[...values,index]);}
    catch(err){setError(err instanceof Error?err.message:'采用经验失败');}finally{setAdopting(null);}
  }
  useEffect(()=>{let alive=true;setLoading(true);setError('');setSelected(undefined);setCopying(false);requestId.current=undefined;
    Promise.all([request<{items:SharedProject[]}>('?mine='+mine),id?request<SharedProject>('/'+id):Promise.resolve(undefined)])
      .then(([list,detail])=>{if(alive){setItems(list.items);setSelected(detail);setCopyTitle(detail?(detail.title+' · 副本').slice(0,120):'');}})
      .catch(err=>{if(alive)setError(err.message);}).finally(()=>{if(alive)setLoading(false);});return()=>{alive=false;};
  },[id,mine]);
  useEffect(()=>{if(busy)return;let alive=true;let reading=false;
    const reload=async()=>{if(document.hidden||reading)return;reading=true;
      try{const [list,detail]=await Promise.all([request<{items:SharedProject[]}>('?mine='+mine),id?request<SharedProject>('/'+id):Promise.resolve(undefined)]);
        if(alive){setItems(list.items);setSelected(detail);}}
      catch(err){if(alive)setError(err instanceof Error?err.message:'共享进度更新失败，请刷新。');}
      finally{reading=false;}
    };const timer=window.setInterval(()=>void reload(),8000);return()=>{alive=false;clearInterval(timer);};
  },[id,mine,busy]);
  async function manage(action:'visibility'|'publish'){
    if(!selected||busy)return;setBusy(true);setError('');
    try{setSelected(await request<SharedProject>('/'+selected.id+(action==='publish'?'/publish':''),action==='publish'?'POST':'PUT',{
      version:selected.version,visibility:action==='publish'?selected.visibility:selected.visibility==='team'?'private':'team'}));}
    catch(err){setError(err instanceof Error?err.message:'共享更新失败');}finally{setBusy(false);}
  }
  async function copy(){
    if(!selected||!copyTitle.trim()||busy)return;setBusy(true);setError('');requestId.current??=crypto.randomUUID();
    try{const value=await request<{id:string;kind:string}>('/'+selected.id+'/copy','POST',{request_id:requestId.current,title:copyTitle.trim(),version:selected.version});
      window.location.hash=`#/${value.kind==='product'?'products':value.kind==='plan'?'planning':'studio'}?project=${value.id}`;}
    catch(err){setError(err instanceof Error?err.message:'复制失败');}finally{setBusy(false);}
  }
  const visible=items.filter(item=>(!author||item.author.id===author)&&(!kind||item.kind===kind)&&(item.title+' '+item.author.name).toLowerCase().includes(query.toLowerCase()));
  const authors=[...new Map(items.map(item=>[item.author.id,item.author])).values()];
  const snapshot=selected?.snapshot;const published=!!selected?.version;
  const groups=snapshot?.batches?.length?snapshot.batches.map((batch,index)=>({name:`第 ${batch.version_number||index+1} 版`,ids:batch.job_ids})):snapshot?.images?.length?[{name:'项目图片',ids:snapshot.images.map(image=>image.id)}]:[];
  const grouped=new Set(groups.flatMap(group=>group.ids));const extras=snapshot?.images?.filter(image=>!grouped.has(image.id))||[];
  if(extras.length)groups.push({name:'后续修改',ids:extras.map(image=>image.id)});
  return <section className="team-sharing">
    <div className="section-heading"><div><p className="eyebrow">TEAM WORKSPACE</p><h2>团队共享</h2></div><div className="guided-actions"><a className="button-secondary" href="#/showcases">团队完整案例</a><a className="button-secondary" href="#/learning">团队作图经验</a>{selected&&<a className="button-secondary" href={mine?'#/team?mine=1':'#/team'}>返回共享列表</a>}</div></div>
    {error&&<p role="alert" className="feedback feedback-error">{error}</p>}
    {loading?<p role="status">正在载入共享项目…</p>:selected?<>
      <section className="guided-card team-project-intro"><div><span className="team-kind">{label(selected.kind)}</span><h3>{selected.title}</h3><p>作者：{selected.author.name} · {published?'共享第 '+selected.version+' 版':'制作中，尚未发布首版'} · {formatTaskTime(selected.updated_at)}</p>
        <small>{selected.image_count} 张成果 · {selected.material_count} 份资料 · 来源项目第 {selected.source_revision} 次修订</small></div>
        <div className="guided-actions">{published&&<><button className="button-primary" disabled={busy} onClick={()=>setCopying(!copying)}>复制到我的工作区</button><a className="button-secondary" href={'/api/team-shares/'+selected.id+'/download'}>下载完整项目</a></>}
          {selected.can_manage&&<><a className="button-secondary" href={sourceLink(selected)}>打开我的原项目</a><button className="button-secondary" disabled={busy} onClick={()=>void manage('publish')}>更新共享版本</button><button className="button-secondary" disabled={busy} onClick={()=>void manage('visibility')}>{selected.visibility==='team'?'取消共享':'设为团队共享'}</button></>}
        </div>
        {selected.visibility==='private'&&<p>当前仅自己可见，其他成员无法查看、下载或复制。</p>}
        {!published&&<p>{snapshot?.publish_error||'项目默认共享。产品分析确认或完整一套图片全部成功后自动发布；后续套图完成后自动更新，本页每8秒刷新进度。'}</p>}
        {copying&&<div className="team-copy-form"><label>我的副本名称<input value={copyTitle} maxLength={120} onChange={event=>{setCopyTitle(event.target.value);requestId.current=undefined;}}/></label><p>复制资料、方案、已有图片及反馈，保留作者和共享版本来源。图需与提示词需要重新确认；后续创作使用你自己的模型配置。复制本身不会调用模型，也不会上传资料到服务商。</p><button className="button-primary" disabled={busy||!copyTitle.trim()} onClick={()=>void copy()}>{busy?'正在复制…':'创建我的副本'}</button></div>}
      </section>
      {published&&snapshot&&<>
        <section className="guided-card"><h3>产品资料与制作流程</h3><div className="team-material-list">{snapshot.materials.map(material=><a key={material.id} href={file(selected.id,'materials/'+material.id)} target="_blank" rel="noreferrer"><strong>{material.name}</strong><small>{material.kind} · {material.pages} 页</small></a>)}</div>
          <details><summary>目标与风格要求</summary><pre className="workflow-preserve-lines">{JSON.stringify(snapshot.settings,null,2)}</pre></details>
          {snapshot.history.map(document=><details key={document.id}><summary>{stageNames[document.stage]} · 第 {document.version} 版 · {document.confirmed_at?'已确认':'草稿'}</summary><pre className="workflow-preserve-lines">{JSON.stringify(document.content,null,2)}</pre></details>)}
        </section>
        {groups.map(group=><section className="guided-card" key={group.name}><h3>{group.name}</h3><div className="task-image-grid">{group.ids.map(imageId=>snapshot.images.find(image=>image.id===imageId)).filter((image):image is SharedImage=>!!image).map(image=><article className="task-image-card" key={image.id}>
          {image.status==='succeeded'?<button className="task-image-preview" type="button" onClick={()=>setPreview(image.id)}><img loading="lazy" src={file(selected.id,'images/'+image.id+'/original.png')} alt={image.shot_name||'共享图片'}/></button>:<div className="team-image-status">{image.status==='failed'?'此图生成失败':image.status}</div>}
          <div className="task-image-caption"><strong>{image.shot_name||'项目图片'}</strong><small>{image.size} · {image.model_name}{image.parent_job_id?' · 修改版本':''}</small><details><summary>提示词与质检</summary><p className="workflow-preserve-lines">{image.prompt}</p><pre className="workflow-preserve-lines">{JSON.stringify(image.review,null,2)}</pre></details>
            {!!image.references.length&&<details><summary>参考输入与角色</summary><pre className="workflow-preserve-lines">{JSON.stringify(image.reference_roles,null,2)}</pre>{image.references.map((reference,index)=><a key={reference} href={file(selected.id,reference)} target="_blank" rel="noreferrer">参考输入 {index+1} </a>)}</details>}
          </div></article>)}</div></section>)}
        <section className="guided-card"><h3>反馈与作图经验</h3><details><summary>图片反馈</summary><pre className="workflow-preserve-lines">{JSON.stringify(snapshot.feedback,null,2)}</pre></details>
          {!!snapshot.experiences.length&&<><label>将经验用于我的产品<select value={productId} onChange={event=>{setProductId(event.target.value);setAdopted([]);}}><option value="">选择自己的产品</option>{products.map(product=><option key={product.id} value={product.id}>{product.title}</option>)}</select></label>
            {snapshot.experiences.map((experience,index)=><details key={index}><summary>参考经验 {index+1}</summary><pre className="workflow-preserve-lines">{JSON.stringify(experience.content,null,2)}</pre><button className="button-secondary" disabled={!productId||adopting!==null||adopted.includes(index)} onClick={()=>void adopt(index)}>{adopted.includes(index)?'已加入待确认经验':adopting===index?'正在采用…':'采用这条经验'}</button></details>)}
            {!products.length&&<p>先建立自己的产品分析，即可单独采用团队经验。</p>}</>}
          <p>采用或复制的经验先进入待确认列表，确认后才参与作图。<a href="#/learning">打开我的作图经验 →</a></p></section>
      </>}
      {preview&&<div className="case-preview-overlay" role="dialog" aria-modal="true" aria-label="共享图片预览"><button className="button-secondary" onClick={()=>setPreview('')}>关闭预览</button><img src={file(selected.id,'images/'+preview+'/original.png')+'?original=true'} alt="共享项目原图"/></div>}
    </>:<>
      <section className="team-sharing-banner"><span className="eyebrow">从个人创作，到团队积累</span><h3>把完整的制作过程，留给下一次创作。</h3><p>日常页面只展示自己的工作。在这里查看团队的产品资料、图片方案与修改经验，复制后独立继续制作。</p><a href="#/team?mine=1">管理我的共享 →</a></section>
      <nav className="workflow-subnav" aria-label="共享范围"><a href="#/team" aria-current={!mine?'page':undefined}>团队项目</a><a href="#/team?mine=1" aria-current={mine?'page':undefined}>我的共享</a></nav>
      <div className="team-sharing-filters"><label>搜索项目<input value={query} onChange={event=>setQuery(event.target.value)} placeholder="项目名称或作者"/></label><label>作者<select value={author} onChange={event=>setAuthor(event.target.value)}><option value="">全部作者</option>{authors.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>内容<select value={kind} onChange={event=>setKind(event.target.value)}><option value="">全部类型</option><option value="product">产品分析</option><option value="plan">图片策划</option><option value="legacy">完整创作</option></select></label></div>
      <div className="team-project-grid">{visible.map(item=><a className="team-project-card" key={item.id} href={'#/team?share='+item.id+(mine?'&mine=1':'')}><div className="team-project-card-top"><span className="team-kind">{label(item.kind)}</span><span>{item.visibility==='private'?'仅自己':item.version?'共享 v'+item.version:'制作中'}</span></div><h3>{item.title}</h3><p>{item.author.name} · {item.image_count} 张图片 · {item.material_count} 份资料</p><footer><time>{formatTaskTime(item.updated_at)}</time><span>查看流程 ↗</span></footer></a>)}</div>
      {!visible.length&&<section className="guided-card"><p>{items.length?'没有匹配的共享项目。':'还没有共享项目。新建项目默认共享，首次完成后会自动发布完整版本。'}</p></section>}
    </>}
  </section>;
}
