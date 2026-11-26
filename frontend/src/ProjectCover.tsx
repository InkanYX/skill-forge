import { useState } from 'react';
import { materialUrl, type Project } from './creationProjectApi';

export default function ProjectCover({project,product=false}:{project:Project;product?:boolean}){
  const photo=product?project.materials?.find(item=>item.media_type.startsWith('image/')):undefined;
  const latest=new Set(project.batches?.at(-1)?.job_ids||[]);
  const results=(project.images||[]).filter(item=>item.status==='succeeded'&&(item.preview_url||item.image_url));
  const image=results.find(item=>latest.has(item.id))||results.at(-1);
  const url=product?(photo?materialUrl(project.id,photo.id)+'?preview=true':undefined):image?.preview_url||image?.image_url;
  const [failed,setFailed]=useState('');
  return <div className={'project-cover'+(product?' is-product':' is-artwork')}>
    {url&&failed!==url?<img src={url} loading="lazy" alt={product?project.title+'产品资料封面':project.title+'实际成图'} onError={()=>setFailed(url)}/>:<div className="project-cover-empty"><svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" aria-hidden="true"><path d="M3 4h18v16H3zM3 16l6-6 5 5 3-3 4 4"/><circle cx="16" cy="8" r="1.5"/></svg><span>{url?'封面暂不可用':product?'添加实拍，建立产品档案':'等待第一张作品'}</span></div>}
    <span className="project-cover-tag">{product?'产品资料':image?'实际成图':'策划方向'}</span>
  </div>;
}
