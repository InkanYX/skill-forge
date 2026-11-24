import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
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
  if (['failed', 'unknown', 'needs_changes'].includes(run.status)) return 'job-status job-failed';
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

export default function AgentStudio({ route = '', active = true, detailOnly = false }: { route?: string; active?: boolean; detailOnly?: boolean }) {
  const { user } = useAuth();
  const [packages, setPackages] = useState<SkillPackage[]>([]);
  const [config, setConfig] = useState<ImageConfiguration | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [runId, setRunId] = useState(() => new URLSearchParams(route.split('?')[1] || '').get('run') || '');
  const [detail, setDetail] = useState<AgentRun>();
  const [goal, setGoal] = useState('');
  const [skillId, setSkillId] = useState('');
  const [reference, setReference] = useState<File>();
  const [maxSteps, setMaxSteps] = useState(20);
  const [maxImages, setMaxImages] = useState(6);
  const [instruction, setInstruction] = useState('');
  const [sourceId, setSourceId] = useState('');
  const refreshEpoch = useRef(0);
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

  const refresh = useCallback(async (prefer?: string) => {
    const epoch = ++refreshEpoch.current;
    try {
      const next = prefer ?? runId;
      const [value, selected] = await Promise.all([listRuns(), next ? getRun(next) : Promise.resolve(undefined)]);
      if (epoch !== refreshEpoch.current) return;
      setRuns(value);
      setDetail(selected);
    } catch (err) { if (epoch === refreshEpoch.current) setError(err instanceof Error ? err.message : '制作任务读取失败'); }
  }, [runId]);

  function selectRun(id: string, source = '') {
    ++refreshEpoch.current;
    setRunId(id); setSourceId(source); setDetail(undefined); setInstruction(''); setError(''); setNotice('');
    const params = new URLSearchParams();
    if (id) params.set('run', id);
    if (source) params.set('source', source);
    window.history.replaceState(window.history.state, '', `#/studio?${params}`);
  }

  useEffect(() => { if (!detailOnly) void loadBasics(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => {
    if (!active) return;
    void refresh();
    const timer = pending ? window.setInterval(() => { void refresh(); }, 2500) : undefined;
    return () => { window.clearInterval(timer); ++refreshEpoch.current; };
  }, [active, pending, refresh]);
  useEffect(() => {
    if (!active) return;
    const params = new URLSearchParams(route.split('?')[1] || '');
    if (params.get('run')) setRunId(params.get('run')!);
    if (params.get('source')) setSourceId(params.get('source')!);
  }, [route, active]);
  useEffect(() => {
    if (!detail) return;
    const available = [...(detail?.previous_images || []), ...(detail?.images || [])].filter(item => item.status === 'succeeded');
    setSourceId(previous => available.some(item => item.id === previous) ? previous : available.at(-1)?.id || '');
  }, [detail]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!config) { setError('请先在「个人模型配置」中保存服务商连接和文字模型，视觉模型选填。'); return; }
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
      selectRun(value.id); setDetail(value); setGoal(''); setReference(undefined);
      setNotice('任务已排队。系统会分析参考图、按技能策划并制作；有视觉模型时对照参考图质检，否则待人工审核。');
      await refresh(value.id);
    } catch (err) { setError(err instanceof Error ? err.message : '任务创建失败'); }
    finally { setBusy(false); }
  }

  async function cancel() {
    if (!detail || !window.confirm('取消本轮制作？已开始的图片调用可能已完成，请核对生成记录。')) return;
    setBusy(true); setError('');
    try { setDetail(await cancelRun(detail.id)); await refresh(detail.id); setNotice('已请求取消任务。'); }
    catch (err) { setError(err instanceof Error ? err.message : '取消失败'); }
    finally { setBusy(false); }
  }

  async function rework() {
    if (!detail || !instruction.trim()) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const value = await reworkRun(detail.id, instruction.trim(), sourceId);
      selectRun(value.id); setDetail(value);
      setNotice('本轮修改已排队，将沿用原始目标、技能版本与参考图，并基于选定图片继续编辑。');
      await refresh(value.id);
    } catch (err) { setError(err instanceof Error ? err.message : '返工失败'); }
    finally { setBusy(false); }
  }

  const currentSkill = packages.find(item => item.id === skillId);
  const images = [...(detail?.previous_images || []), ...(detail?.images || [])];
  const available = images.filter(item => item.status === 'succeeded');
  const latest = runs.find(item => item.conversation_id === detail?.conversation_id);
  const isLatest = !latest || latest.id === detail?.id;

  return <section>
    {!detailOnly && <>
    <div className="section-heading"><h3>技能辅助制作</h3><button type="button" className="button-secondary" onClick={() => selectRun('')}>新建创作</button></div>
    <details className="skill-rules">
      <summary>查看制作规则</summary>
      <ul>
        <li>使用用户选择的模型与可选请求参数，技能建议不覆盖配置；失败不自动重试。</li>
        <li>技能包只读；本次任务锁定当前启用的版本，后续升级不影响已创建任务。</li>
        <li>不执行技能里的脚本，也不访问技能目录以外的文件；只使用系统提供的确定性工具。</li>
        <li>提供产品参考图后必须保留参考图进行制作；配置视觉模型时会先分析原图，再对照检查结果。</li>
        <li>未配置视觉模型或质检存在不确定项时标为「待人工审核」；达到执行上限不代表制作成功。</li>
      </ul>
    </details>
    </>}
    {error && <p className="feedback feedback-error" role="alert">{error}</p>}
    {notice && <p className="feedback feedback-success" role="status">{notice}</p>}
    {!detailOnly && config && !config.vision_model_name && <p className="feedback feedback-warning">当前未配置视觉模型。出图后只能标记为待人工审核。</p>}

    {!detailOnly && <div className="agent-layout">
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
            <div className="form-field"><label htmlFor="agent-images">最多出图</label><input id="agent-images" type="number" min={1} max={16} value={maxImages} onChange={e => setMaxImages(Number(e.target.value))} /></div>
          </div>
        </fieldset>
        <div className="form-actions"><button className="button-primary" disabled={busy || !config || !packages.length}>{busy ? '提交中…' : '开始制作'}</button></div>
        {!config && <p className="form-footnote">请先到「个人模型配置」保存服务商连接和文字模型；视觉模型选填。</p>}
        <p className="form-footnote">创建后任务在后台排队。步骤和结果会自动刷新；同一任务不会因超时自动重复提交图片。</p>
      </form>

      <aside className="agent-runs">
        <div className="section-heading"><h3>任务记录</h3><span>本人任务</span></div>
        {!runs.length && <p className="empty-config">还没有技能辅助制作任务。</p>}
        {runs.map(item => <button type="button" key={item.id} className={`config-item ${detail?.conversation_id === item.conversation_id ? 'config-item-active' : ''}`} onClick={() => selectRun(item.id)}>
          <strong>{item.goal.split('\n')[0].slice(0, 60)}</strong>
          <small>{agentStatusLabels[item.status] || item.status} · 第 {item.turn_index} 轮 · {formatTaskTime(item.updated_at)}</small>
        </button>)}
      </aside>
    </div>}

    {detail && <div className="connection-card agent-detail">
      <div className="section-heading"><div><h3>创作详情 · 第 {detail.turn_index} 轮</h3><p className="form-footnote">创建 {formatTaskTime(detail.created_at)}{detail.finished_at ? ` · 结束 ${formatTaskTime(detail.finished_at)}` : ''} · <a href={`#/library?task=${detail.conversation_id}`}>打开生成记录</a></p></div><span className={statusClass(detail)}>{agentStatusLabels[detail.status] || detail.status}</span></div>
      <p className="agent-goal">{detail.goal}</p>
      <p className="form-footnote">制作技能：{detail.skill_name} · {detail.skill_version}（本轮已锁定）</p>
      {detail.history.length > 0 && <section className="creation-dialogue" aria-label="制作对话"><h3 className="skill-subhead">制作对话</h3>{detail.history.map(turn => <article className="creation-turn" key={turn.id}>
        <div><strong>第 {turn.turn_index} 轮</strong><time dateTime={turn.created_at}>{formatTaskTime(turn.created_at)}</time></div>
        <p className="case-prompt">{turn.instruction}</p>
        {turn.summary && <p>{turn.summary}</p>}
        <small>{agentStatusLabels[turn.status] || turn.status}</small>
      </article>)}</section>}
      <p className="form-footnote">模型：{detail.model_name || '未记录'} · 视觉：{detail.vision_model_name || '未配置'} · 执行记录 {detail.steps_count} 条 · 工具调用上限 {detail.max_steps} 次 · 出图 {detail.image_calls}/{detail.max_images}</p>
      {(detail.summary || detail.error) && <p className={`feedback ${detail.status === 'succeeded' ? 'feedback-success' : 'feedback-warning'}`} role="status">{detail.summary || detail.error}</p>}
      {agentPending(detail) && <div className="form-actions"><button type="button" className="button-secondary cancel-button" disabled={busy} onClick={() => void cancel()}>取消任务</button></div>}

      {images.length > 0 && <><h3 className="skill-subhead">图片版本</h3><div className="agent-images">
        {images.map(item => <figure key={item.id} className="agent-image">
          {item.status === 'succeeded' && item.preview_url ? <a href={item.image_url || '#'} target="_blank" rel="noreferrer"><img src={item.preview_url} alt={item.shot_name || item.id} loading="lazy" /></a> : <div className="artwork-placeholder"><span>{agentStatusLabels[item.status] || item.status}</span></div>}
          <figcaption><strong>{item.shot_name || item.id.slice(0, 8)}</strong><small>{agentStatusLabels[item.status] || item.status} · {item.mode === 'edit' ? '编辑' : '生成'}</small>{item.message && <small>{item.message}</small>}
            {item.execution_result?.agent_review ? <details><summary>{item.execution_result.agent_review.status === 'passed' ? '自动质检通过' : item.execution_result.agent_review.status === 'rework' ? '质检需要修改' : '待人工审核'}</summary>
              <p>{item.execution_result.agent_review.summary}</p>
              <small>{item.execution_result.agent_review.compared_reference ? '已对照参考图' : '未进行参考图对照'} · {formatTaskTime(item.execution_result.agent_review.updated_at)}</small>
              <ul>{item.execution_result.agent_review.checks.map(check => <li key={check.item}>{check.detail}</li>)}</ul>
            </details> : item.status === 'succeeded' && <small>待质检</small>}
            {item.status === 'succeeded' && !agentPending(detail) && isLatest && <button type="button" className="button-secondary" aria-pressed={sourceId === item.id} onClick={() => { setSourceId(item.id); document.getElementById('agent-rework')?.focus(); }}>{sourceId === item.id ? '已选为修改来源' : '修改这张图'}</button>}
          </figcaption>
        </figure>)}
      </div></>}

      <h3 className="skill-subhead">第 {detail.turn_index} 轮执行记录</h3>
      {!detail.steps.length && <p className="empty-config">等待 Agent 开始执行…</p>}
      <ol className="agent-steps">{detail.steps.map(step => <li key={step.index} className="agent-step">
        <span className={`agent-step-kind agent-step-${step.kind}`}>{step.kind === 'tool' || step.kind === 'analysis' ? (toolLabels[step.tool] || step.tool) : step.kind === 'error' ? '已停止' : '模型回复'}</span>
        <div>
          <p className="agent-step-summary">{step.kind === 'tool' ? `${step.tool} · ${stepSummary(step)}` : step.result.slice(0, 240)}</p>
          <small>{formatTaskTime(step.created_at)}</small>
          {step.result && <details><summary>查看返回结果</summary><pre className="skill-content">{step.result}</pre></details>}
        </div>
      </li>)}</ol>

      {!isLatest && latest && <a href={`#/studio?mode=skill&run=${latest.id}`}>打开最新一轮继续修改</a>}
      {!agentPending(detail) && isLatest && <div className="agent-rework">
        <h3 className="skill-subhead">继续对话与修改</h3>
        {available.length > 0 && <div className="form-field"><label htmlFor="agent-source">本轮修改来源</label><select id="agent-source" value={sourceId} onChange={event => setSourceId(event.target.value)}>{available.map((item, index) => <option key={item.id} value={item.id}>{index + 1}. {item.shot_name || item.id.slice(0, 8)} · {formatTaskTime(item.created_at)}</option>)}</select></div>}
        <div className="form-field"><label htmlFor="agent-rework">本轮要求</label><textarea id="agent-rework" rows={4} maxLength={4000} value={instruction} onChange={e => setInstruction(e.target.value)} placeholder="例如：保持四根立柱和连接结构，只调整背景与主体颜色。" /><small>本轮要求完整保存到同一创作任务，原图与历次结果保留。</small></div>
        {detail.status === 'unknown' && <p className="feedback feedback-warning">本轮结果待确认，请先核对已有图片和服务商记录。</p>}
        <div className="form-actions"><button type="button" className="button-primary" disabled={busy || !instruction.trim() || detail.status === 'unknown' || (available.length > 0 && !sourceId)} onClick={() => void rework()}>提交本轮要求</button></div>
      </div>}
    </div>}
  </section>;
}
