import { useEffect, useRef, useState } from 'react';
import ProductAnalysisEditor from './ProductAnalysisEditor';
import ImagePlanEditor from './ImagePlanEditor';
import PlanTemplateLibrary from './PlanTemplateLibrary';
import CreationProjectRecords from './CreationProjectRecords';
import { projectRequest, type Project } from './creationProjectApi';

export function ProductAnalysisPage({route}:{route:string}){
  const params=new URLSearchParams(route.split('?')[1]);const id=params.get('project');const legacy=params.get('legacy')||params.get('import');
  const editing=!!id||params.get('new')==='1'||!!legacy;
  return <section><div className="section-heading"><div><p className="eyebrow">PRODUCT ANALYSIS</p><h2>产品分析</h2></div>{!editing&&<a className="button-primary" href="#/products?new=1">新建产品</a>}</div>
    {!editing&&<p className="settings-intro">查看产品资料和已确认卖点。打开产品可维护资料、进行分析，并建立图片策划方案。</p>}
    {legacy?<LegacyProductBridge key={legacy} id={legacy}/>:editing?<ProductAnalysisEditor key={id||'new'} id={id||undefined}/>:<CreationProjectRecords kind="product"/>}
  </section>;
}
function LegacyProductBridge({id}:{id:string}){
  const pending=useRef<Promise<Project>|null>(null);const [error,setError]=useState('');
  useEffect(()=>{let active=true;pending.current??=projectRequest<Project>('/import-product','POST',{legacy_product_id:id});pending.current.then(value=>{if(active)window.location.replace('#/products?project='+value.id);}).catch(err=>{if(active)setError(err.message);});return()=>{active=false;};},[id]);
  return <section className="guided-card">{error?<p className="feedback feedback-error">{error}</p>:<p role="status">正在载入产品资料，不会调用模型。</p>}<a href="#/products">返回产品列表</a></section>;
}
export function PlanningPage({route}:{route:string}){
  const params=new URLSearchParams(route.split('?')[1]);const id=params.get('project');const templates=params.get('view')==='templates'||params.get('view')==='presets';
  const editing=!templates&&(!!id||params.get('new')==='1'||params.has('product')||params.has('template'));
  return <section><div className="section-heading"><div><p className="eyebrow">IMAGE PLANNING</p><h2>图片策划</h2></div>{!editing&&!templates&&<a className="button-primary" href="#/planning?new=1">新建策划方案</a>}</div>
    {!editing&&<nav className="workflow-subnav" aria-label="策划内容"><a href="#/planning" aria-current={!templates?'page':undefined}>策划方案</a><a href="#/planning?view=templates" aria-current={templates?'page':undefined}>方案模板</a></nav>}
    {templates?<PlanTemplateLibrary key={route} route={route}/>:editing?<ImagePlanEditor key={id||route} id={id||undefined} route={route}/>:<CreationProjectRecords kind="plan"/>}
  </section>;
}
