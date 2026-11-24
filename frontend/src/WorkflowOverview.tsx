import { useEffect, useState } from 'react';
import { projectRequest, stageNames, type Project } from './creationProjectApi';

export default function WorkflowOverview() {
  const [items,setItems]=useState<Project[]>([]);const [error,setError]=useState('');
  useEffect(()=>{let active=true;projectRequest<Project[]>().then(values=>{if(active)setItems(values);}).catch(err=>{if(active)setError(err.message);});return()=>{active=false;};},[]);
  return <section className="workflow-overview"><div className="workflow-entry-grid">{[
    {href:'#/products',step:'01',title:'产品分析',description:'上传说明书与实拍，确认产品事实和候选卖点。'},
    {href:'#/planning',step:'02',title:'图片策划',description:'选用产品，确认图需、风格和完整提示词。'},
    {href:'#/studio',step:'03',title:'图片创作',description:'从已确认方案生图，也可直接填写要求生成。'},
    {href:'#/library',step:'04',title:'生成记录',description:'查看实际结果、图片版本和服务商调用日志。'},
  ].map(item=><a href={item.href} key={item.href}><small>{item.step}</small><strong>{item.title}</strong><p>{item.description}</p></a>)}</div>
    {error&&<p className="feedback feedback-error">流程草稿读取失败：{error}</p>}
    {items.length>0&&<div className="workflow-drafts"><h3>继续分析与策划</h3>{items.slice(0,5).map(item=><a key={item.id} href={(item.kind==='product'?'#/products':'#/planning')+'?project='+item.id}><strong>{item.title}</strong><span>{item.kind==='product'?(item.analysis_confirmed?'卖点已确认':'产品分析待确认'):stageNames[item.stage]}</span></a>)}</div>}
  </section>;
}
