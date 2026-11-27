import { useEffect, useState } from 'react';
import { projectRequest, type VisualStyle, type VisualStyleSnapshot } from './creationProjectApi';

export const defaultVisualStyle:VisualStyle={preset:'auto',variation:'balanced',density:'medium',palette:'',campaign_treatment:'scene_editorial'};
interface Catalog {version:string;presets:{id:string;name:string;description:string;rules:string}[]}

export default function VisualStylePicker({value,onChange,snapshot,onUpgrade,upgrading=false}:{value:VisualStyle|null;onChange:(value:VisualStyle|null)=>void;snapshot?:VisualStyleSnapshot|null;onUpgrade?:()=>void;upgrading?:boolean}){
  const [catalog,setCatalog]=useState<Catalog|null>(null);const [error,setError]=useState('');const [retry,setRetry]=useState(0);
  useEffect(()=>{let active=true;setError('');projectRequest<Catalog>('/visual-styles').then(data=>{if(active)setCatalog(data);}).catch(err=>{if(active)setError(err.message);});return()=>{active=false;};},[retry]);
  const selected=catalog?.presets.find(item=>item.id===value?.preset);
  const pinned=snapshot&&JSON.stringify(snapshot.selection)===JSON.stringify(value)?snapshot:null;
  return <div className="visual-style-picker">
    <div className="visual-style-intro"><span className="visual-style-kicker">ART DIRECTION</span><h4>选择整套视觉语言</h4><p>控制构图、文字与信息层级。产品事实与 Skill 规范继续生效，每张图按用途独立设计。</p></div>
    {snapshot&&catalog&&snapshot.version!==catalog.version&&onUpgrade&&<div className="feedback feedback-warning"><p>本方案仍使用 {snapshot.version}。新版加入商品套图与 A+ 的画册策划、逐图设计和手机可读性规范，分别约束主图、附图与 A+。采用时同时更新已选内置技能；个人技能版本保留。保存后需重新策划、确认，历史图片保留。</p><button type="button" disabled={upgrading} onClick={onUpgrade}>{upgrading?'新版规范待保存':'采用新版设计规范'}</button></div>}
    {error&&<p role="alert">风格目录加载失败：{error} <button type="button" onClick={()=>setRetry(n=>n+1)}>重试加载</button></p>}
    {!catalog&&!error&&<p>正在加载风格目录…</p>}
    {!value&&<p>当前保留原方案的自由风格要求。选择下方风格后，将重新确认图需与提示词。</p>}
    <div className="visual-style-grid" role="group" aria-label="主视觉风格">{catalog?.presets.map(item=><label className={'visual-style-choice '+(value?.preset===item.id?'is-selected':'')} key={item.id}>
      <input type="radio" name="visual-style" value={item.id} checked={value?.preset===item.id} onChange={()=>onChange({...value||defaultVisualStyle,preset:item.id})}/>
      <span className={'style-sketch style-sketch-'+item.id} aria-hidden="true"><i/><b/><em/><span/></span>
      <strong>{item.name}</strong><small>{item.description}</small>
    </label>)}</div>
    {value&&<><div className="guided-form-grid">
      <label>排版变化程度<select value={value.variation} onChange={e=>onChange({...value,variation:e.target.value as VisualStyle['variation']})}><option value="steady">统一稳重</option><option value="balanced">适度变化</option><option value="rich">丰富变化</option></select></label>
      <label>文字密度<select value={value.density} onChange={e=>onChange({...value,density:e.target.value as VisualStyle['density']})}><option value="low">少 · 精简重点</option><option value="medium">中 · 层级清晰</option><option value="high">多 · 分组说明</option></select></label>
      <label>套图 / A+ 画册表达<select aria-label="套图 / A+ 画册表达" value={value.campaign_treatment||'adaptive'} onChange={e=>onChange({...value,campaign_treatment:e.target.value as VisualStyle['campaign_treatment']})}><option value="adaptive">自适应 · 按品牌与产品选择</option><option value="scene_editorial">沉浸画册 · 场景与证据编排</option><option value="light_gold">案例样式 · 浅色字与细金线</option></select></label>
      <label>图形配色要求（可选）<input value={value.palette} maxLength={1000} onChange={e=>onChange({...value,palette:e.target.value})} placeholder="例如品牌绿；留空由产品与场景决定"/></label>
    </div><p className="visual-style-note">沉浸画册用于商品套图附图和 A+，按购买问题组合场景、对照、细节与步骤。商品主图只展示产品，背景按确认要求，不添加文案与图形。浅色字与细金线为可选图形语言，不是黄色底图。明确配色与补充要求优先；修改后保存并重新策划、确认。</p>
    <details><summary>查看规范与验收依据</summary><p className="workflow-preserve-lines">{pinned?.rules||selected?.rules}</p><p>版本：{pinned?.version||catalog?.version||'待加载'}。{value.preset==='auto'?'AI 将在图需中给出推荐理由，确认后生效。':'图需将明确逐张构图，确认后再编写提示词。'}</p>{(pinned?.checks||['风格与构图一致','文字层级清楚、手机预览可读','场景或细节证据适合本图职责','整套品牌一致，逐张布局有变化']).map(check=><p key={check}>· {check}</p>)}</details></>}
  </div>;
}
