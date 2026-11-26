import { useState } from 'react';
import { materialUrl, type Project } from './creationProjectApi';

export default function ProductIdentity({project}:{project:Project}){
  const photo=project.materials.find(item=>item.media_type.startsWith('image/'));
  const [failed,setFailed]=useState(false);
  const confirmed=!!project.documents.analysis?.confirmed_at;
  const documents=project.materials.filter(item=>item.media_type==='application/pdf').length;
  const images=project.materials.filter(item=>item.media_type.startsWith('image/')).length;
  return <header className="studio-product-hero">
    <div className="product-identity-copy"><p className="identity-kicker"><span/>PRODUCT WORKSPACE <span className="identity-divider">/</span> 产品创作空间</p><h3>{project.title}</h3><p className="identity-description">从真实产品出发，展开每一种创意可能。</p><div className="identity-meta"><span>{confirmed?'卖点已确认':'待分析 / 确认'}</span>{project.settings.sku&&<span>SKU · {project.settings.sku}</span>}<span>{documents} 份文档</span><span>{images} 张图片</span></div><a className="identity-back" href="#/products">返回产品列表 <span aria-hidden="true">↗</span></a></div>
    <div className="product-identity-art" aria-hidden="true"><div className="identity-orbit"/><div className="identity-sheet identity-sheet-back"><i/><span>PRODUCT / STORY</span></div><div className="identity-sheet identity-sheet-front">{photo&&!failed?<img src={materialUrl(project.id,photo.id)+'?preview=true'} alt="" onError={()=>setFailed(true)}/>:<div className="identity-sculpture"><i/><b/></div>}<div><span>THE NEXT PERSPECTIVE</span><b>↗</b></div></div><span className="identity-art-label">MATERIALS INTO POSSIBILITIES</span></div>
  </header>;
}
