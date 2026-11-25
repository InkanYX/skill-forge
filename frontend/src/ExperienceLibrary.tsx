import { useEffect, useState } from 'react';
import { apiFetch } from './apiFetch';
import type { DrawingExperience } from './ProductExperience';

export default function ExperienceLibrary(){
  const [items,setItems]=useState<DrawingExperience[]>([]);const [query,setQuery]=useState('');const [status,setStatus]=useState('all');const [error,setError]=useState('');const [loading,setLoading]=useState(true);const [retry,setRetry]=useState(0);
  useEffect(()=>{let active=true;setLoading(true);apiFetch('/api/product-experience/library',{cache:'no-store'}).then(async r=>{const value=await r.json();if(!r.ok)throw new Error(value.detail||'读取失败');return value;}).then(data=>{if(active){setItems(data.experiences);setError('');}}).catch(err=>{if(active)setError(err.message);}).finally(()=>{if(active)setLoading(false);});return()=>{active=false;};},[retry]);
  const shown=items.filter(item=>(status==='all'||item.status===status)&&(item.guidance+' '+item.product_name+' '+item.category+' '+item.style).toLowerCase().includes(query.toLowerCase()));
  return <section><div className="section-heading"><div><p className="eyebrow">DRAWING EXPERIENCE</p><h2>作图经验库</h2></div></div><p className="settings-intro">图片评价 → AI 提出经验 → 人工确认 → 按条件检索 → 后续策划参考。这里只汇总你维护的经验；不会自动训练模型。</p>
    <section className="guided-card"><div className="guided-form-grid"><label>搜索经验<input value={query} onChange={e=>setQuery(e.target.value)} placeholder="经验、产品、品类或风格"/></label><label>经验状态<select value={status} onChange={e=>setStatus(e.target.value)}><option value="all">全部</option><option value="candidate">待确认</option><option value="active">已生效</option><option value="disabled">已停用</option></select></label></div><p>共 {items.length} 条 · 已生效 {items.filter(item=>item.status==='active').length} 条 · 待确认 {items.filter(item=>item.status==='candidate').length} 条</p>
    {loading&&<p role="status">正在读取…</p>}{error&&<p role="alert">{error} <button type="button" onClick={()=>setRetry(n=>n+1)}>重试</button></p>}
    {shown.map(item=><article className="experience-rule" key={item.id}><header><strong>{({candidate:'待确认',active:'已生效',disabled:'已停用'})[item.status||'candidate']}</strong><small>{item.product_name} · 版本 {item.revision}</small></header><p>{item.guidance}</p>{item.evidence_current===false&&<p className="feedback feedback-warning">来源反馈已更新，暂不参与新任务检索，请重新整理确认。</p>}<p>范围：{item.reuse_scope==='global'?'本人的通用视觉方法':item.reuse_scope==='category'?'本人同品类 · '+item.category:'仅原产品'} · {item.sources.length} 条来源反馈</p><a href={'#/products?project='+item.product_id}>查看反馈、修改及确认经验 →</a> · <a href={'/api/product-experience/'+item.product_id+'/export'}>导出学习数据</a></article>)}
    {!loading&&!shown.length&&<p>暂无匹配经验。到生成记录评价图片，再到对应产品页选择反馈并整理经验。</p>}</section></section>;
}
