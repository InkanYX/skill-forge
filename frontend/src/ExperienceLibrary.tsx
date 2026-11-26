import { useEffect, useRef, useState } from 'react';
import { apiFetch } from './apiFetch';
import type { DrawingExperience } from './ProductExperience';
import { projectRequest,type Project } from './creationProjectApi';

export default function ExperienceLibrary(){
  const [scope,setScope]=useState('team');const [products,setProducts]=useState<Project[]>([]);const [product,setProduct]=useState('');const [adopting,setAdopting]=useState('');const [notice,setNotice]=useState('');
  const adoptionIds=useRef<Record<string,string>>({});
  useEffect(()=>{let active=true;projectRequest<Project[]>('?kind=product').then(value=>{if(active)setProducts(value);}).catch(()=>{});return()=>{active=false;};},[]);
  async function adopt(item:DrawingExperience){
    if(!product)return;setAdopting(item.id);setError('');
    const key=`${item.id}:${item.revision}:${product}`;adoptionIds.current[key]??=crypto.randomUUID();
    try{const response=await apiFetch('/api/product-experience/library/'+item.id+'/adopt',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:adoptionIds.current[key],product_id:product,revision:item.revision})});
      const result=await response.json();if(!response.ok)throw new Error(result.detail||'采用失败');setNotice('已加入目标产品的待确认经验，确认后参与作图。');setRetry(n=>n+1);
    }catch(err){setError(err instanceof Error?err.message:'采用失败');}finally{setAdopting('');}
  }
  const [items,setItems]=useState<DrawingExperience[]>([]);const [query,setQuery]=useState('');const [status,setStatus]=useState('all');const [error,setError]=useState('');const [loading,setLoading]=useState(true);const [retry,setRetry]=useState(0);
  useEffect(()=>{let active=true;setLoading(true);apiFetch('/api/product-experience/library',{cache:'no-store'}).then(async r=>{const value=await r.json();if(!r.ok)throw new Error(value.detail||'读取失败');return value;}).then(data=>{if(active){setItems(data.experiences);setError('');}}).catch(err=>{if(active)setError(err.message);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[retry]);
  const shown=items.filter(item=>(scope==='team'||item.can_edit!==false)&&(status==='all'||item.status===status)&&(item.guidance+' '+item.product_name+' '+item.category+' '+item.style+' '+item.author?.name).toLowerCase().includes(query.toLowerCase()));
  return <section><div className="section-heading"><div><p className="eyebrow">DRAWING EXPERIENCE</p><h2>团队作图经验库</h2></div></div><p className="settings-intro">团队经验统一共享，保留作者与适用范围。其他成员的经验可加入自己的产品，确认后用于后续策划；待确认和停用经验仅供查阅，不会直接用于生图。</p>
    <nav className="workflow-subnav" aria-label="经验范围"><button className="button-secondary" aria-pressed={scope==='team'} onClick={()=>setScope('team')}>团队经验</button><button className="button-secondary" aria-pressed={scope==='mine'} onClick={()=>setScope('mine')}>我的经验</button></nav>
    <section className="guided-card"><label>采用经验的目标产品<select value={product} onChange={e=>setProduct(e.target.value)}><option value="">选择自己的产品</option>{products.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select></label></section>
    {notice&&<p role="status" className="feedback feedback-success">{notice}</p>}
    <section className="guided-card"><div className="guided-form-grid"><label>搜索经验<input value={query} onChange={e=>setQuery(e.target.value)} placeholder="经验、产品、品类或风格"/></label><label>经验状态<select value={status} onChange={e=>setStatus(e.target.value)}><option value="all">全部</option><option value="candidate">待确认</option><option value="active">已生效</option><option value="disabled">已停用</option></select></label></div><p>共 {items.length} 条 · 已生效 {items.filter(item=>item.status==='active').length} 条 · 待确认 {items.filter(item=>item.status==='candidate').length} 条</p>
    {loading&&<p role="status">正在读取…</p>}{error&&<p role="alert">{error} <button type="button" onClick={()=>setRetry(n=>n+1)}>重试</button></p>}
    {shown.map(item=><article className="experience-rule" key={item.id}><header><strong>{({candidate:'待确认',active:'已生效',disabled:'已停用'})[item.status||'candidate']}</strong><small>{item.author?.name||'原作者'} · {item.product_name} · 版本 {item.revision}</small></header><p>{item.guidance}</p>{item.evidence_current===false&&<p className="feedback feedback-warning">来源反馈已更新，暂不参与新任务检索，请重新整理确认。</p>}<p>范围：{item.reuse_scope==='global'?'通用视觉方法':item.reuse_scope==='category'?'同品类 · '+item.category:'仅原产品'} · {item.sources.length} 条来源反馈</p>{item.can_edit!==false?<><a href={'#/products?project='+item.product_id}>查看反馈、修改及确认经验 →</a> · <a href={'/api/product-experience/'+item.product_id+'/export'}>导出学习数据</a></>:<button className="button-secondary" disabled={!product||!!adopting||item.status==='disabled'||item.evidence_current===false} onClick={()=>void adopt(item)}>{adopting===item.id?'正在采用…':'加入我的产品经验'}</button>}</article>)}
    {!loading&&!shown.length&&<p>暂无匹配经验。到生成记录评价图片，再到对应产品页选择反馈并整理经验。</p>}</section></section>;
}
