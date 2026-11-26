import type { BriefPlanningMode, BriefPlanningReport } from './creationProjectApi';

export const briefModeLabels:Record<BriefPlanningMode,string>={optimize:'优化当前方案',replan:'重新策划一套',directed:'按指定方向策划'};
const descriptions:Record<BriefPlanningMode,string>={
  optimize:'保留逐图主题和顺序，优化表达、证据与画面。',
  replan:'保留产品事实，重新组织卖点组合、图序和展示方法。',
  directed:'围绕指定的内容重点，策划一条新的叙事主线。',
};
export function BriefPlanningControls({mode,onMode,direction,onDirection,hasDraft,disabled}:{
  mode:BriefPlanningMode;onMode:(mode:BriefPlanningMode)=>void;direction:string;onDirection:(value:string)=>void;hasDraft:boolean;disabled:boolean;
}){
  return <fieldset className="brief-planning-controls" disabled={disabled}><legend>本次策划方式</legend>
    <div className="brief-planning-options">{(['optimize','replan','directed'] as const).map(value=><label className={mode===value?'is-selected':''} key={value}>
      <input type="radio" name="brief-planning-mode" value={value} checked={mode===value} disabled={value==='optimize'&&!hasDraft} onChange={()=>onMode(value)}/>
      <span><strong>{briefModeLabels[value]}</strong><small>{descriptions[value]}{value==='optimize'&&!hasDraft?'（需先有当前图需）':''}</small></span>
    </label>)}</div>
    {mode==='directed'&&<div className="brief-planning-direction"><label>本次内容策划方向<textarea rows={3} maxLength={2000} value={direction} onChange={event=>onDirection(event.target.value)} placeholder="例如：面向家庭庭院生活，重点展示聚会、遮阳和使用便利。"/></label>
      <div className="brief-direction-presets">{['庭院生活','结构细节','使用便利'].map(value=><button key={value} type="button" onClick={()=>onDirection(value)}>{value}</button>)}</div></div>}
    <p>会对照本人同产品最近的图需。真实功能可以复用，主图与必要内容保留。结果另存为待确认图需版本，历史方案和图片保留。</p>
  </fieldset>;
}

export function BriefPlanningReview({report}:{report?:BriefPlanningReport|null}){
  if(!report)return null;
  return <section className="brief-planning-review" aria-label="本轮内容策划对照"><header><strong>{report.label}</strong><small>已对照 {report.history_count} 份历史图需</small></header>
    {report.direction&&<p>本轮方向：{report.direction}</p>}{report.summary&&<p className="workflow-preserve-lines">{report.summary}</p>}
    {!report.history_count&&<p>暂无同产品历史图需可供对照，本轮将作为后续策划的参考。</p>}
    {report.warnings.length>0&&<div className="feedback feedback-warning" role="status"><strong>部分内容仍可能重复</strong>{report.warnings.slice(0,3).map((warning,index)=><p key={index}>{warning}</p>)}<p>可补充受众、重点卖点或新的策划方向，再重新策划。</p></div>}
    {!!report.protected_slots.length&&<small>第 {report.protected_slots.join('、')} 张为商品主图，保留其展示职责，不计入重复提醒。</small>}
    {!!report.comparisons.length&&<details><summary>查看内容与图位对照</summary>{report.comparisons.map(item=><p key={item.document_id}>「{item.project_title}」图需第 {item.version} 版：{item.compared_slots} 个可对照图位，{item.same_slots.length} 个主题与位置较相似，{item.reused_theme_count} 个主题与历史相似。</p>)}<small>{report.method}</small></details>}
    <p className="brief-planning-confirmation">新图需仍需确认，再编写提示词和生图；历史图片保留。</p>
  </section>;
}
