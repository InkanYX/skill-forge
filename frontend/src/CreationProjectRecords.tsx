import { useEffect, useState, type FormEvent } from 'react';
import { projectRequest, type Project } from './creationProjectApi';
import { creativeRequest } from './creativeApi';
import type { Product } from './productApi';
import { formatTaskTime } from './imageTaskApi';

export default function CreationProjectRecords({kind}:{kind:'product'|'plan'}){
  const [items,setItems]=useState<Project[]>([]);const [legacy,setLegacy]=useState<Product[]>([]);
  const [query,setQuery]=useState('');const [status,setStatus]=useState('all');const [applied,setApplied]=useState({query:'',status:'all'});
  const [error,setError]=useState('');const [loading,setLoading]=useState(true);const [attempt,setAttempt]=useState(0);
  useEffect(()=>{let active=true;setLoading(true);setError('');Promise.all([
    projectRequest<Project[]>(kind==='product'?'?kind=product':''),kind==='product'?creativeRequest<Product[]>('products'):Promise.resolve([]),
  ]).then(([values,old])=>{if(active){setItems(values.filter(item=>kind==='product'?item.kind==='product':item.kind!=='product'));setLegacy(old);}}).catch(err=>{if(active)setError(err.message);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[kind,attempt]);
  const imported=new Set(items.map(item=>item.legacy_product_id).filter(Boolean));
  const root=kind==='product'?'#/products':'#/planning';
  const rows=[...items.map(item=>({id:item.id,title:item.title,sku:item.settings.sku||'',source:item.source?.title||'',updated_at:item.updated_at,
    status:item.busy?'busy':kind==='product'?(item.analysis_confirmed?'ready':'draft'):(item.stage==='images'?'ready':'draft'),
    label:item.busy?'执行中':kind==='product'?(item.analysis_confirmed?'卖点已确认':'待分析 / 确认'):(item.stage==='images'?'提示词已确认':item.stage==='prompts'?'待确认提示词':'待编写 / 确认图需'),href:root+'?project='+item.id})),
    ...legacy.filter(item=>!imported.has(item.id)).map(item=>({id:'legacy-'+item.id,title:item.name,sku:item.sku,source:'',updated_at:item.updated_at,status:'draft',label:'待分析',href:'#/products?legacy='+item.id}))]
    .sort((a,b)=>b.updated_at.localeCompare(a.updated_at));
  const visible=rows.filter(row=>(applied.status==='all'||row.status===applied.status)&&`${row.title} ${row.sku} ${row.source}`.toLowerCase().includes(applied.query.toLowerCase()));
  function search(event:FormEvent){event.preventDefault();setApplied({query:query.trim(),status});}
  return <div className="workflow-record-list"><form className="record-filter-panel" onSubmit={search} aria-label={kind==='product'?'筛选产品':'筛选策划方案'}><div className="workflow-filter-fields"><label>关键词<input maxLength={200} value={query} onChange={e=>setQuery(e.target.value)} placeholder={kind==='product'?'产品名称或 SKU':'方案名称或产品名称'}/></label><label>状态<select value={status} onChange={e=>setStatus(e.target.value)}><option value="all">全部</option><option value="draft">{kind==='product'?'待分析 / 确认':'策划未完成'}</option><option value="ready">{kind==='product'?'卖点已确认':'提示词已确认'}</option><option value="busy">执行中</option></select></label><div className="guided-actions"><button type="button" className="button-secondary" onClick={()=>{setQuery('');setStatus('all');setApplied({query:'',status:'all'});}}>重置</button><button type="submit" className="button-primary">查询</button></div></div></form>
    {error&&<p className="feedback feedback-error" role="alert">{error}</p>}<section className="guided-card"><header><h3>{kind==='product'?'产品列表':'策划方案列表'} <small>共 {visible.length} 条</small></h3><button type="button" className="button-secondary" disabled={loading} onClick={()=>setAttempt(previous=>previous+1)}>刷新</button></header>
      {loading?<p role="status">正在读取记录…</p>:<div className="workflow-record-table">{visible.map(row=><a key={row.id} href={row.href}><div><strong>{row.title}</strong><small>{row.sku||row.source}</small></div><span className={'workflow-record-status status-'+row.status}>{row.label}</span><time>{formatTaskTime(row.updated_at)}</time><span>打开 →</span></a>)}</div>}
      {!loading&&!visible.length&&!error&&<p>{rows.length?'没有匹配的记录，请调整筛选条件。':'还没有记录，点击页面上方的新建按钮开始。'}</p>}
    </section>
  </div>;
}
