import { useEffect, useState, type FormEvent } from 'react';
import { useAuth } from './AuthGate';
import {
  agentPending, agentStatusLabels, cancelRun, createRun, getRun, listRuns, reworkRun, toolLabels,
  type AgentRun,
} from './agentApi';
import { imageConfigRequest, type ImageConfiguration } from './imageConfigApi';
import { formatTaskTime } from './imageTaskApi';
import { listPackages, type SkillPackage } from './skillPackageApi';

function statusClass(run: AgentRun) {
  if (run.status === 'succeeded') return 'job-status job-succeeded';
  if (run.status === 'failed' || run.status === 'unknown') return 'job-status job-failed';
  if (run.status === 'cancelled') return 'job-status job-cancelled';
  return 'job-status';
}

function stepSummary(step: AgentRun['steps'][number]) {
  try {
    const value = JSON.parse(step.arguments || '{}') as Record<string, unknown>;
    const parts = Object.entries(value)
      .filter(([key]) => !['content'].includes(key))
      .map(([key, item]) => `${key}: ${typeof item === 'string' ? item.slice(0, 120) : JSON.stringify(item).slice(0, 120)}`);
    return parts.join(' · ');
  } catch { return step.arguments.slice(0, 160); }
}

export default function AgentStudio() {
  const { user } = useAuth();
  const [packages, setPackages] = useState<SkillPackage[]>([]);
  const [config, setConfig] = useState<ImageConfiguration | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [runId, setRunId] = useState('');
  const [detail, setDetail] = useState<AgentRun>();
  const [goal, setGoal] = useState('');
  const [skillId, setSkillId] = useState('');
  const [reference, setReference] = useState<File>();
  const [maxSteps, setMaxSteps] = useState(20);
  const [maxImages, setMaxImages] = useState(6);
  const [instruction, setInstruction] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const pending = runs.some(agentPending);

  async function loadBasics() {
    try {
      const [skillItems, configItem] = await Promise.all([
        listPackages(), imageConfigRequest<ImageConfiguration | null>('').catch(() => null),
      ]);
      // Only built-in packages and the caller's own personal packages can run.
      const usable = skillItems.filter(item => item.current_version
        && (item.source === 'builtin' || !item.owner_id || item.owner_id === user.id));
      setPackages(usable);
      setSkillId(previous => previous || usable[0]?.id || '');
      setConfig(configItem);
      setError('');
    } catch (err) { setError(err instanceof Error ? err.message : '基础信息读取失败'); }
  }

  async function refresh(prefer?: string) {
    try {
      const value = await listRuns();
      setRuns(value);
      const next = prefer || runId || value[0]?.id || '';
      if (next) setDetail(await getRun(next));
      else setDetail(undefined);
    } catch (err) { setError(err instanceof Error ? err.message : 'Agent 任务读取失败'); }
  }

  useEffect(() => { void loadBasics(); void refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => {
    const timer = window.setInterval(() => { void refresh(); }, pending ? 2500 : 15000);
    return () => window.clearInterval(timer);
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [pending, runId]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!config) { setError('请先在「个人模型配置」中保存图片服务、文字模型与视觉模型。'); return; }
    if (!skillId) { setError('请选择一个已启用的技能包。'); return; }
    if (!goal.trim()) { setError('请填写本次制作目标。'); return; }
    setBusy(true); setError(''); setNotice('');
    try {
      const form = new FormData();
      form.append('payload', JSON.stringify({
        goal: goal.trim(), skill_id: skillId, config_id: config.id,
        max_steps: maxSteps, max_images: maxImages,
      }));
      if (reference) form.append('reference', reference);
      const value = await createRun(form);
      setRunId(value.id); setDetail(value); setGoal(''); setReference(undefined);
      setNotice('任务已排队。Agent 会在后台读取技能规范、策划提示词、出图并质检。');
      await refresh(value.id);
    } catch (err) { setError(err instanceof Error ? err.message : '任务创建失败'); }
    finally { setBusy(false); }
  }

  async function cancel() {
    if (!detail || !window.confirm('取消这个 Agent 任务？已开始的图片调用可能已完成，请核对生成记录。')) return;
    setBusy(true); setError('');
    try { setDetail(await cancelRun(detail.id)); await refresh(detail.id); setNotice('已请求取消任务。'); }
    catch (err) { setError(err instanceof Error ? err.message : '取消失败'); }
    finally { setBusy(false); }
  }

  async function rework() {
    if (!detail || !instruction.trim()) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const value = await reworkRun(detail.id, instruction.trim());
      setInstruction(''); setRunId(value.id); setDetail(value);
      setNotice('已创建返工任务，将沿用原技能版本与参考图，并带上上一轮结论。');
      await refresh(value.id);
    } catch (err) { setError(err instanceof Error ? err.message : '返工失败'); }
    finally { setBusy(false); }
  }

  const currentSkill = packages.find(item => item.id === skillId);

  return <section>
    <div className="section-heading"><div><p className="eyebrow">SERVER-SIDE AGENT</p><h2>Agent 制作</h2></div><span>{runs.length} 个任务</span></div>
    <p className="settings-intro">Agent 在后端按技能规范自主策划、写提示词、出图并调用视觉模型质检。前端只展示步骤和结果；密钥不会进入模型上下文。</p>
    <div className="skill-rules">
      <strong>固定规则</strong>
      <ul>
        <li>图片固定 <code>gpt-image-2.5-sunburst</code> / high / auto / PNG / 不增强，调用失败不自动重试。</li>
        <li>技能包只读；本次任务锁定当前启用的版本，后续升级不影响已创建任务。</li>
        <li>不执行技能里的脚本，也不访问技能目录以外的文件；只使用系统提供的确定性工具。</li>
        <li>没有配置视觉模型时，Agent 只能以「待人工审核」结束，不能声称自动质检通过。</li>
      </ul>
    </div>
    {error && <p className="feedback feedback-error" role="alert">{error}</p>}
    {notice && <p className="feedback feedback-success" role="status">{notice}</p>}
    {config && !config.vision_model_name && <p className="feedback feedback-warning">当前未配置视觉模型。Agent 出图后只能标记为待人工审核。</p>}

    <div className="agent-layout">
      <form className="connection-card agent-form" onSubmit={submit}>
        <h3>新任务</h3>
        <fieldset disabled={busy} className="set-fieldset">
          <div className="form-field"><label htmlFor="agent-skill">技能包</label>
            <select id="agent-skill" required value={skillId} onChange={e => setSkillId(e.target.value)}>
              {!packages.length && <option value="">没有已启用的技能包</option>}
              {packages.map(item => <option key={item.id} value={item.id}>{item.name} · {item.current_version?.version_label}{item.source === 'builtin' ? ' · 内置' : ' · 个人'}</option>)}
            </select>
            <small>{currentSkill ? `当前版本 ${currentSkill.current_version?.version_label}，编译档位 ${currentSkill.current_version?.compile_level === 'full' ? '完整参考' : '核心'}。` : '请先在技能库中启用一个版本。'}</small>
          </div>
          <div className="form-field"><label htmlFor="agent-goal">制作目标</label><textarea id="agent-goal" required rows={7} maxLength={8000} value={goal} onChange={e => setGoal(e.target.value)} placeholder="例如：为这款凉棚做 1 张亚马逊主图，白底，保持结构、颜色和连接件不变；不要编造尺寸或认证。" /><small>{goal.length} / 8000 字符。写清平台、用途、必须保持与必须避免的事项。</small></div>
          <div className="form-field"><label htmlFor="agent-reference">参考图（选填，1 张）</label><input id="agent-reference" type="file" accept="image/png,image/jpeg,image/webp" onChange={e => setReference(e.target.files?.[0])} /><small>{reference ? `已选择 ${reference.name}` : '用于商品结构核对或作为编辑参考；不提供则 Agent 只能生成新图。'}</small></div>
          <div className="skill-import-row">
            <div className="form-field"><label htmlFor="agent-steps">最多步数</label><input id="agent-steps" type="number" min={5} max={40} value={maxSteps} onChange={e => setMaxSteps(Number(e.target.value))} /></div>
            <div className="form-field"><label htmlFor="agent-images">最多出图</label><input id="agent-images" type="number" min={1} max={8} value={maxImages} onChange={e => setMaxImages(Number(e.target.value))} /></div>
          </div>
        </fieldset>
        <div className="form-actions"><button className="button-primary" disabled={busy || !config || !packages.length}>{busy ? '提交中…' : '创建 Agent 任务'}</button></div>
        {!config && <p className="form-footnote">未找到图片服务配置。请先到「个人模型配置」保存服务商、文字模型和视觉模型。</p>}
        <p className="form-footnote">创建后任务在后台排队。步骤和结果会自动刷新；同一任务不会因超时自动重复提交图片。</p>
      </form>

      <aside className="agent-runs">
        <div className="section-heading"><h3>任务记录</h3><span>本人任务</span></div>
        {!runs.length && <p className="empty-config">还没有 Agent 任务。</p>}
        {runs.map(item => <button type="button" key={item.id} className={`config-item ${detail?.id === item.id ? 'config-item-active' : ''}`} onClick={() => { setRunId(item.id); setDetail(undefined); void refresh(item.id); }}>
          <strong>{item.goal.split('\n')[0].slice(0, 60)}</strong>
          <small>{agentStatusLabels[item.status] || item.status} · 出图 {item.image_calls}/{item.max_images} · {formatTaskTime(item.created_at)}</small>
        </button>)}
      </aside>
    </div>

    {detail && <div className="connection-card agent-detail">
      <div className="section-heading"><div><h3>任务详情</h3><p className="form-footnote">{detail.id} · 创建 {formatTaskTime(detail.created_at)}{detail.finished_at ? ` · 结束 ${formatTaskTime(detail.finished_at)}` : ''}</p></div><span className={statusClass(detail)}>{agentStatusLabels[detail.status] || detail.status}</span></div>
      <p className="agent-goal">{detail.goal}</p>
      <p className="form-footnote">模型：{detail.model_name || '未记录'} · 视觉：{detail.vision_model_name || '未配置'} · 步数 {detail.steps_count}/{detail.max_steps} · 出图 {detail.image_calls}/{detail.max_images}</p>
      {(detail.summary || detail.error) && <p className={`feedback ${detail.status === 'succeeded' ? 'feedback-success' : 'feedback-warning'}`} role="status">{detail.summary || detail.error}</p>}
      {agentPending(detail) && <div className="form-actions"><button type="button" className="button-secondary cancel-button" disabled={busy} onClick={() => void cancel()}>取消任务</button></div>}

      {detail.images.length > 0 && <><h3 className="skill-subhead">图片</h3><div className="agent-images">
        {detail.images.map(item => <figure key={item.id} className="agent-image">
          {item.status === 'succeeded' && item.preview_url ? <a href={item.image_url || '#'} target="_blank" rel="noreferrer"><img src={item.preview_url} alt={item.shot_name || item.id} loading="lazy" /></a> : <div className="artwork-placeholder"><span>{agentStatusLabels[item.status] || item.status}</span></div>}
          <figcaption><strong>{item.shot_name || item.id.slice(0, 8)}</strong><small>{agentStatusLabels[item.status] || item.status} · {item.mode === 'edit' ? '编辑' : '生成'}</small>{item.message && <small>{item.message}</small>}</figcaption>
        </figure>)}
      </div></>}

      <h3 className="skill-subhead">步骤</h3>
      {!detail.steps.length && <p className="empty-config">等待 Agent 开始执行…</p>}
      <ol className="agent-steps">{detail.steps.map(step => <li key={step.index} className="agent-step">
        <span className={`agent-step-kind agent-step-${step.kind}`}>{step.kind === 'tool' ? (toolLabels[step.tool] || step.tool) : step.kind === 'error' ? '已停止' : '模型回复'}</span>
        <div>
          <p className="agent-step-summary">{step.kind === 'tool' ? `${step.tool} · ${stepSummary(step)}` : step.result.slice(0, 240)}</p>
          <small>{formatTaskTime(step.created_at)}</small>
          {step.result && <details><summary>查看返回结果</summary><pre className="skill-content">{step.result}</pre></details>}
        </div>
      </li>)}</ol>

      {!agentPending(detail) && <div className="agent-rework">
        <h3 className="skill-subhead">返工</h3>
        <div className="form-field"><label htmlFor="agent-rework">补充要求</label><textarea id="agent-rework" rows={4} maxLength={4000} value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="例如：第二张图的立柱数量不对，请保持 4 根并保留原有连接关系。" /><small>返工会创建新任务，沿用原技能版本和参考图，并带上上一轮结论；历史任务保留。</small></div>
        <div className="form-actions"><button type="button" className="button-primary" disabled={busy || !instruction.trim()} onClick={() => void rework()}>创建返工任务</button></div>
      </div>}
    </div>}
  </section>;
}
