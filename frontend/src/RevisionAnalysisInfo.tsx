import type { ImageRecord } from './imageTaskApi';

export default function RevisionAnalysisInfo({item}:{item:ImageRecord}) {
  const analysis=item.execution_result?.revision_analysis;
  if(!analysis)return null;
  const labels:Record<string,string>={understanding:'正在理解修改要求',inspecting:'正在分析来源图片',planning:'正在编写编辑提示词',ready:'修改分析与提示词已准备',failed:'修改分析未完成'};
  return <details className="skill-execution-info"><summary>{labels[analysis.stage]||'修改分析记录'}</summary>
    <p>你的要求：{analysis.user_instruction}</p>
    {analysis.intent&&<p>需求理解：{analysis.intent.user_issue}</p>}
    {analysis.visual_observations&&<details><summary>图片实际分析</summary><p className="case-prompt">{analysis.visual_observations}</p></details>}
    {analysis.edit_reference?.available&&<p>实际编辑底图已加载，可核对全图或局部；已再次查看 {analysis.edit_reference_reads?.length||0} 次。</p>}
    {!!analysis.edit_reference_reads?.length&&<details><summary>编辑底图核对记录</summary><ul>{analysis.edit_reference_reads.map((read,index)=><li key={index}>
      {read.crop?`局部：${read.crop.join(', ')}`:'全图'}{read.question&&` · ${read.question}`}
      <p className="case-prompt">{read.observation}</p>
    </li>)}</ul></details>}
    {!!analysis.materials?.length&&<p>已关联 {analysis.materials.length} 份原始产品资料，已查阅 {analysis.material_reads?.length||0} 项。</p>}
    {!!analysis.material_reads?.length&&<details><summary>实际查阅的产品资料</summary><ul>{analysis.material_reads.map((read,index)=><li key={index}>
      {read.name} · 第 {read.page} 页 · {read.method==='image'?'视觉核对':'文字读取'}
      {read.observation&&<p className="case-prompt">{read.observation}</p>}
    </li>)}</ul></details>}
    {analysis.plan&&<>
      <strong>发现的问题</strong><ul>{analysis.plan.observed_issues.map((value,index)=><li key={index}>{value}</li>)}</ul>
      <strong>修改步骤</strong><ol>{analysis.plan.correction_steps.map((value,index)=><li key={index}>{value}</li>)}</ol>
      <strong>保持不变</strong><ul>{analysis.plan.preserve.map((value,index)=><li key={index}>{value}</li>)}</ul>
      {!!analysis.plan.uncertainties.length&&<><strong>待核实信息</strong><ul>{analysis.plan.uncertainties.map((value,index)=><li key={index}>{value}</li>)}</ul></>}
      <details><summary>{analysis.stage==='failed'?'本次生成的提示词（未通过时不会提交）':'实际编辑提示词'}</summary><p className="case-prompt">{analysis.plan.prompt}</p></details>
    </>}
    {!!analysis.prompt_checks?.length&&<details open={analysis.stage==='failed'}><summary>提示词检查结果</summary><ul>{analysis.prompt_checks.map((check,index)=><li key={index}>
      {check.severity==='error'?'未通过':'提醒'}：{check.message}
    </li>)}</ul></details>}
    {analysis.error&&<p className="feedback feedback-error">{analysis.error}</p>}
    <small>文本模型：{analysis.text_model||'尚未调用'} · 视觉模型：{analysis.vision_model||'尚未调用'}</small>
  </details>;
}
