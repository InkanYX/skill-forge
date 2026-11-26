import { useEffect, useState } from 'react';
import { projectRequest, type Project } from './creationProjectApi';
import { projectDestination, projectStatus } from './projectProgress.mjs';

export default function WorkflowOverview() {
  const [items,setItems]=useState<Project[]>([]);const [error,setError]=useState('');
  useEffect(()=>{let active=true;projectRequest<Project[]>().then(values=>{if(active)setItems(values);}).catch(err=>{if(active)setError(err.message);});return()=>{active=false;};},[]);
  return <section className="workflow-overview"><div className="workflow-entry-grid">{[
    {href:'#/products',step:'01',title:'产品资料',description:'先进入产品，管理资料、卖点和该产品下的所有策划。'},
    {href:'#/planning',step:'02',title:'全部图片策划',description:'跨产品查找已有方案；每套方案归属于一个产品。'},
    {href:'#/studio',step:'03',title:'图片创作',description:'从已确认方案生图，也可直接填写要求生成。'},
    {href:'#/library',step:'04',title:'生成记录',description:'查看实际结果、图片版本和服务商调用日志。'},
  ].map(item=><a href={item.href} key={item.href}><small>{item.step}</small><strong>{item.title}</strong><p>{item.description}</p></a>)}</div>
    {error&&<p className="feedback feedback-error">流程草稿读取失败：{error}</p>}
    {items.length>0&&<div className="workflow-drafts"><h3>最近的创作项目</h3>{[...items].sort((a,b)=>b.updated_at.localeCompare(a.updated_at)).slice(0,5).map(item=><a key={item.id} href={projectDestination(item)}><strong>{item.title}</strong><span>{projectStatus(item).label} <b aria-hidden="true">↗</b></span></a>)}</div>}
  </section>;
}
