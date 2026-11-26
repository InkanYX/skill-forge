import { useEffect, useState, type FormEvent } from 'react';
import { projectRequest, type Project } from './creationProjectApi';
import { creativeRequest } from './creativeApi';
import type { Product } from './productApi';
import { formatTaskTime } from './imageTaskApi';
import { projectDestination, projectStatus } from './projectProgress.mjs';
import ProductLibrary from './ProductLibrary';
import { useWorkspaceView } from './useWorkspaceView';

export default function CreationProjectRecords({kind}:{kind:'product'|'plan'}){
  const [items,setItems]=useState<Project[]>([]);const [legacy,setLegacy]=useState<Product[]>([]);
  const [query,setQuery]=useWorkspaceView('records:'+kind+':query','');const [status,setStatus]=useWorkspaceView('records:'+kind+':status','all');const [applied,setApplied]=useWorkspaceView('records:'+kind+':applied',{query:'',status:'all'});
  const [product,setProduct]=useWorkspaceView('records:'+kind+':product','');
  const [plans,setPlans]=useState<Project[]>([]);const [view,setView]=useWorkspaceView<'cards'|'list'>('records:'+kind+':view','cards');
  const [error,setError]=useState('');const [loading,setLoading]=useState(true);const [attempt,setAttempt]=useState(0);
  useEffect(()=>{let active=true;setLoading(true);setError('');Promise.all([
    projectRequest<Project[]>(kind==='product'?'?kind=product':''),kind==='product'?creativeRequest<Product[]>('products'):Promise.resolve([]),kind==='product'?projectRequest<Project[]>('?kind=plan'):Promise.resolve([]),
  ]).then(([values,old,children])=>{if(active){setPlans(children.filter(item=>item.kind==='plan'));setItems(values.filter(item=>kind==='product'?item.kind==='product':item.kind!=='product'));setLegacy(old);}}).catch(err=>{if(active)setError(err.message);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[kind,attempt]);
  const imported=new Set(items.map(item=>item.legacy_product_id).filter(Boolean));
  const rows=[...items.map(item=>({id:item.id,title:item.title,sku:item.settings.sku||'',source:item.source?.title||'',updated_at:item.updated_at,
    status:projectStatus(item).key,label:projectStatus(item).label,href:projectDestination(item)})),
    ...legacy.filter(item=>!imported.has(item.id)).map(item=>({id:'legacy-'+item.id,title:item.name,sku:item.sku,source:'',updated_at:item.updated_at,status:'draft',label:'待分析',href:'#/products?legacy='+item.id}))]
    .sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
  const sources=[...new Map(items.filter(item=>item.source?.product_id||item.source_product_id).map(item=>[item.source?.product_id||item.source_product_id,item.source?.title||'未命名产品'])).entries()];
  const visible=rows.filter(row=>(!product||items.find(item=>item.id===row.id&&(item.source?.product_id||item.source_product_id)===product))&&(applied.status==='all'||row.status===applied.status)&&`${row.title} ${row.sku} ${row.source}`.toLowerCase().includes(applied.query.toLowerCase()));
  function search(event:FormEvent){event.preventDefault();setApplied({query:query.trim(),status});}
  return <div className="workflow-record-list">
    {error&&<p className="feedback feedback-error" role="alert">{error}</p>}
    <section className="guided-card">
      <header><h3>{kind==='product'?'产品列表':'全部产品的策划方案'} <small>共 {visible.length} 条</small></h3><button type="button" className="button-secondary" disabled={loading} onClick={()=>setAttempt(previous=>previous+1)}>刷新</button></header>
      {kind==='plan'&&<label className="product-plan-search">按所属产品选择<select value={product} onChange={e=>setProduct(e.target.value)}><option value="">所有产品</option>{sources.map(([id,title])=><option key={id} value={id||''}>{title}</option>)}</select></label>}
      <form className="guided-record-filter" onSubmit={search} aria-label={kind==='product'?'筛选产品':'筛选策划方案'}>
        <div className="workflow-filter-fields">
          <label>关键词<input maxLength={200} value={query} onChange={e=>setQuery(e.target.value)} placeholder={kind==='product'?'产品名称或 SKU':'方案名称或产品名称'}/></label>
          <label>状态<select value={status} onChange={e=>setStatus(e.target.value)}><option value="all">全部</option><option value="draft">{kind==='product'?'待分析 / 确认':'策划未完成'}</option><option value="ready">{kind==='product'?'卖点已确认':'待生图'}</option><option value="busy">执行中</option>{kind==='plan'&&<><option value="attention">图片待处理</option><option value="complete">本轮已完成</option></>}</select></label>
          <div className="guided-actions"><button type="button" className="button-secondary" onClick={()=>{setQuery('');setStatus('all');setProduct('');setApplied({query:'',status:'all'});}}>重置</button><button type="submit" className="button-primary">查询</button></div>
        </div>
      </form>
      {kind==='product'&&<div className="library-view-switch" aria-label="产品展示方式"><button type="button" aria-pressed={view==='cards'} onClick={()=>setView('cards')}>封面卡片</button><button type="button" aria-pressed={view==='list'} onClick={()=>setView('list')}>紧凑列表</button></div>}
      {!loading&&kind==='product'&&view==='cards'&&<ProductLibrary products={visible.flatMap(row=>{const item=items.find(item=>item.id===row.id);return item?[item]:[];})} plans={plans}/>}
      {loading?<p role="status">正在读取记录…</p>:<div className="workflow-record-table">{visible.filter(row=>kind!=='product'||view==='list'||row.id.startsWith('legacy-')).map(row=><a key={row.id} href={row.href}><div><strong>{row.title}</strong><small>{row.sku||row.source}</small></div><span className={'workflow-record-status status-'+row.status}>{row.label}</span><span className="record-open"><time>{formatTaskTime(row.updated_at)}</time><b>{kind==='product'?'进入产品':row.status==='complete'?'查看成果':row.status==='busy'?'查看进度':'继续处理'} →</b></span></a>)}</div>}
      {!loading&&!visible.length&&!error&&<p>{rows.length?'没有匹配的记录，请调整筛选条件。':'还没有记录，点击页面上方的新建按钮开始。'}</p>}
    </section>
  </div>;
}
