import { useEffect, useState } from 'react';
import { projectRequest, type LearningSettings, type Project } from './creationProjectApi';
import type { DrawingExperience } from './ProductExperience';

export const defaultLearning:LearningSettings={enabled:true,category:'',image_type:'any',device:'any',excluded_ids:[]};
export default function LearningControls({value,onChange,project}:{value:LearningSettings;onChange:(value:LearningSettings)=>void;project?:Project}){
  const [matches,setMatches]=useState<DrawingExperience[]>([]);const [error,setError]=useState('');
  useEffect(()=>{let active=true;setError('');if(!project)return;projectRequest<{experiences:DrawingExperience[]}>('/'+project.id+'/experience-preview').then(data=>{if(active)setMatches(data.experiences);}).catch(err=>{if(active)setError(err.message);});return()=>{active=false;};},[project?.id,project?.revision]);
  return <details className="learning-controls"><summary>历史作图经验 · {value.enabled?'按范围自动参考':'本方案关闭'}</summary><p>读取已人工确认且证据仍有效的经验，最多 8 条。当前产品事实、Skill 与本轮明确要求优先。</p>
    <label><input type="checkbox" checked={value.enabled} onChange={e=>onChange({...value,enabled:e.target.checked})}/>后续策划参考适用经验</label>
    <div className="guided-form-grid"><label>经验匹配品类<input maxLength={120} value={value.category} onChange={e=>onChange({...value,category:e.target.value})} placeholder="例如：户外凉棚；留空不匹配同品类规则"/></label><label>本方案图型<select value={value.image_type} onChange={e=>onChange({...value,image_type:e.target.value as LearningSettings['image_type']})}><option value="any">未指定</option><option value="listing">Listing 套图</option><option value="a_plus">A+</option><option value="detail">结构 / 细节图</option></select></label><label>本方案终端<select value={value.device} onChange={e=>onChange({...value,device:e.target.value as LearningSettings['device']})}><option value="any">未指定</option><option value="desktop">桌面端</option><option value="mobile">手机端</option></select></label></div>
    {project&&<><p>以下按已保存的要求匹配。修改范围或排除经验后，保存并重新确认图需与提示词。</p>{error&&<p role="alert">经验预览暂不可用：{error}</p>}{matches.map(item=><article className="learning-match" key={item.id}><label><input type="checkbox" checked={!value.excluded_ids.includes(item.id)} onChange={e=>onChange({...value,excluded_ids:e.target.checked?value.excluded_ids.filter(id=>id!==item.id):[...value.excluded_ids,item.id]})}/>本次参考 · 版本 {item.revision}</label><p>{item.guidance}</p><small>{item.match_reason}</small><a href={'#/products?project='+item.product_id}>查看来源</a></article>)}{!matches.length&&!error&&<p>当前没有匹配经验。先评价图片并在产品页确认经验，或调整适用范围后保存。</p>}</>}
    <a href="#/learning">打开作图经验库 →</a>
  </details>;
}
