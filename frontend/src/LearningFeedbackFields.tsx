import type { CreativeCase, LearningFeedback } from './creativeApi';

export const ratingLabels={fidelity:'产品保真',composition:'构图',typography:'文字排版',scene:'场景表现',style:'风格符合度'} as const;
export default function LearningFeedbackFields({note,onChange}:{note:CreativeCase;onChange:(value:LearningFeedback)=>void}){
  const value=note.learning||{};
  return <div className="learning-feedback-fields"><h4>让这次评价成为下次的经验</h4><p>1 分表示问题明显，5 分表示满意；未评分的项目保持空白。</p><div className="guided-form-grid">{Object.entries(ratingLabels).map(([key,label])=><label key={key}>{label}评分<select value={value.ratings?.[key as keyof typeof ratingLabels]??''} onChange={e=>onChange({...value,ratings:{...value.ratings,[key]:e.target.value?Number(e.target.value):null}})}><option value="">未评分</option>{[1,2,3,4,5].map(n=><option value={n} key={n}>{n} 分</option>)}</select></label>)}</div>
    <label>对比历史图片<select value={value.reference_job_id||''} onChange={e=>onChange({...value,reference_job_id:e.target.value||null,preference:'unrated',comparison:undefined})}><option value="">暂不对比</option>{note.comparison_candidates?.map(item=><option key={item.id} value={item.id}>{item.name} · {new Date(item.created_at).toLocaleString('zh-CN')}</option>)}</select></label>
    {value.reference_job_id&&<><label>两个版本更喜欢哪个<select value={value.preference||'unrated'} onChange={e=>onChange({...value,preference:e.target.value as LearningFeedback['preference']})}><option value="unrated">尚未选择</option><option value="current">当前图片更好</option><option value="reference">历史图片更好</option><option value="tie">各有优点 / 接近</option></select></label><p><a href={'#/library?job='+value.reference_job_id} target="_blank" rel="noreferrer">打开历史图片查看</a> · 仅可选择同产品或修改链中的本人作品。</p></>}
    <label>选择原因 / 评价依据<textarea rows={3} maxLength={4000} value={value.reason||''} onChange={e=>onChange({...value,reason:e.target.value})} placeholder="例如：当前版本产品更突出、文案不遮挡连接件，但历史版本的场景更自然。"/></label>
    {value.comparison&&<details><summary>已保存的提示词差异与评分变化</summary><p>{Object.entries(value.comparison.rating_delta||{}).map(([key,n])=>`${ratingLabels[key as keyof typeof ratingLabels]} ${n>0?'+':''}${n}`).join(' · ')||'历史版本尚无可对比评分。'}（仅本次人工评分差异，不代表整体质量趋势）</p><pre className="workflow-preserve-lines">{value.comparison.prompt_diff||'两张图提示词相同；请用评价说明实际画面差异。'}</pre></details>}
  </div>;
}
