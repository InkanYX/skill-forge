import type { ImageRecord } from './imageTaskApi';

export default function SkillExecutionInfo({ item }: { item: ImageRecord }) {
  const execution = item.execution_result?.skill_execution;
  if (!execution) return null;
  return <details className="skill-execution-info"><summary>{execution.used_skills.length
    ? '已加载技能：' + execution.used_skills.map(skill => skill.name).join('、')
    : execution.method === 'rules' ? '已附加技能规范，未执行自主文件读取' : '技能读取未完成'}</summary>
    <p>{execution.reused_preparation ? '复用了此前相同任务的技能读取与策划结果。' : '以下为本次实际提供给模型的技能与资料。读取记录不代表图片已经通过验收。'}</p>
    {execution.used_skills.map(skill => <p key={skill.skill_id}><strong>{skill.name}</strong> · {skill.version === '0.0.0' ? '版本未标注' : skill.version}</p>)}
    <ul>{execution.files.map((file, index) => <li key={index}><code>{file.path}</code><span>{file.error ? '读取失败：' + file.error : file.method === 'pinned' ? '指定加载' : '按需读取'}</span></li>)}</ul>
  </details>;
}
