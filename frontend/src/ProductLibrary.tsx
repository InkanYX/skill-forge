import { useEffect, useRef, useState } from 'react';
import { projectRequest, type Project } from './creationProjectApi';
import { projectStatus } from './projectProgress.mjs';
import { formatTaskTime } from './imageTaskApi';
import ProjectCover from './ProjectCover';

function ProductCard({project,count}:{project:Project;count:number}){
  const [detail,setDetail]=useState<Project>(project);const [error,setError]=useState(false);const [attempt,setAttempt]=useState(0);const root=useRef<HTMLElement>(null);
  useEffect(()=>{let active=true;const controller=new AbortController();
    const observer=new IntersectionObserver(entries=>{if(!entries.some(item=>item.isIntersecting))return;observer.disconnect();
      if(project.materials)return;
      projectRequest<Project>('/'+project.id,'GET',undefined,controller.signal).then(value=>{if(active){setDetail(value);setError(false);}}).catch(()=>{if(active)setError(true);});
    },{rootMargin:'200px'});
    if(root.current)observer.observe(root.current);
    return()=>{active=false;controller.abort();observer.disconnect();};
  },[project,attempt]);
  const status=projectStatus(detail);
  return <article className="product-library-card" ref={root}><a href={'#/products?project='+project.id}><ProjectCover project={detail} product/><div className="product-library-copy"><div><span className={'workflow-record-status status-'+status.key}>{status.label}</span><small>{detail.settings.sku||'未设置 SKU'}</small></div><h4>{project.title}</h4><p>{detail.materials?`${detail.materials.length} 份资料`:'资料读取中'}<span>·</span>{count} 套策划</p><footer><time>{formatTaskTime(project.updated_at)}</time><strong>进入产品 ↗</strong></footer></div></a>{error&&<button type="button" className="cover-retry" onClick={()=>setAttempt(value=>value+1)}>资料读取失败，点击重试</button>}</article>;
}

export default function ProductLibrary({products,plans}:{products:Project[];plans:Project[]}){
  return <div className="product-library-grid">{products.map(project=><ProductCard key={project.id} project={project} count={plans.filter(plan=>(plan.source?.product_id||plan.source_product_id)===project.id).length}/>)}</div>;
}
