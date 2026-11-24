import { apiFetch } from './apiFetch';
import { useEffect, useRef, useState } from 'react';
import ExportDownload from './ExportDownload';
import { formatImageSize } from './ImageSizePicker';
import ImageRecordDialog from './ImageRecordDialog';
import { startTaskPolling } from './taskPolling';
import { formatTaskTime, readTaskResponse, taskCounts, taskLabels, taskPending, type ImageRecord, type ImageTaskDetail } from './imageTaskApi';

export default function TaskResultsPanel({ taskId, active = true, focusJobId }: { taskId: string; active?: boolean; focusJobId?: string }) {
  const [task, setTask] = useState<ImageTaskDetail>();
  const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const [pageVisible, setPageVisible] = useState(() => !document.hidden);
  const [selected, setSelected] = useState<ImageRecord>();
  const [highlight, setHighlight] = useState(''); const [cancelling, setCancelling] = useState(false);
  const poller = useRef<ReturnType<typeof startTaskPolling<ImageTaskDetail>> | null>(null);
  const logs = useRef(new Map<string, HTMLElement>());
  const located = useRef('');
  useEffect(() => {
    const visibility = () => setPageVisible(!document.hidden);
    document.addEventListener('visibilitychange', visibility);
    return () => document.removeEventListener('visibilitychange', visibility);
  }, []);
  useEffect(() => {
    setTask(undefined); setSelected(undefined); setError(''); setHighlight(''); located.current = '';
  }, [taskId]);
  useEffect(() => {
    if (!active || !pageVisible) return;
    const current = startTaskPolling<ImageTaskDetail>({
      load: async signal => readTaskResponse(await apiFetch(`/api/image-jobs/tasks/${encodeURIComponent(taskId)}`, { signal, cache: 'no-store' })),
      pending: taskPending, onData: value => { setTask(value); setError(''); },
      onError: err => setError(`${err instanceof Error ? err.message : '进度读取失败'}，请手动刷新。`), onLoading: setLoading,
    });
    poller.current = current;
    return () => { current.stop(); poller.current = null; };
  }, [taskId, active, pageVisible]);
  function locateLog(id: string) {
    setHighlight(id);
    const log = logs.current.get(id);
    log?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    log?.focus({ preventScroll: true });
  }
  useEffect(() => {
    if (!task || !focusJobId || located.current === focusJobId) return;
    const item = task.items.find(item => item.id === focusJobId);
    if (!item) return;
    located.current = focusJobId;
    if (item.image_url) setSelected(item); else locateLog(item.id);
  }, [task, focusJobId]);
  async function cancel() {
    if (cancelling) return;
    setCancelling(true); setError('');
    try {
      const body = new FormData(); body.set('action', 'cancel');
      await readTaskResponse(await apiFetch(`/api/image-jobs/tasks/${taskId}/cancel`, { method: 'POST', body, signal: AbortSignal.timeout(12000) }));
      await poller.current?.refresh();
    } catch (err) { setError(err instanceof Error ? err.message : '取消未完成。'); }
    finally { setCancelling(false); }
  }
  return <section className="task-results-panel" aria-label="任务运行结果">
    <div className="task-result-toolbar"><div><h3>运行结果{task && ` · ${task.counts.total} 张`}</h3>{task && <p>{taskCounts(task)}</p>}</div><div className="task-toolbar-actions">{(task?.counts.queued || 0) > 0 && task?.can_manage !== false && <button type="button" className="button-secondary" disabled={cancelling} onClick={cancel}>{cancelling ? '取消中…' : '取消排队'}</button>}<button type="button" className="button-secondary" disabled={loading} onClick={() => { void poller.current?.refresh(); }}>{loading ? '读取中…' : '刷新进度'}</button></div></div>
    {error && <p className="feedback feedback-error" role="alert">{error}</p>}
    {!task && !error && <p role="status">正在读取任务…</p>}
    {task && <>
      <div className="task-run-meta"><time dateTime={task.created_at}>提交于 {formatTaskTime(task.created_at)}</time><span>{task.config_name} · {task.model_name}</span></div>
      {task.agent_run_id && <div className="feedback feedback-warning"><strong>创作任务 · 共 {task.turn_count} 轮 · {taskLabels[task.status] || task.status}</strong>{task.agent_summary && <p>{task.agent_summary}</p>}{task.can_manage !== false && <a href={`#/studio?run=${task.agent_run_id}`}>打开制作对话与执行记录</a>}</div>}
      <details className="task-input-details"><summary>查看本次制作要求</summary>{task.items.map((item, index) => <div key={item.id}><strong>{index + 1}. {item.shot_name || '候选图片'} · {item.execution_profile?.backend ? formatImageSize(item.size) : item.size === "default" ? "自动（未指定尺寸）" : `${item.size.replace("x", " × ")} 像素`}</strong><p className="case-prompt">{item.prompt}</p>{item.reference_url && <a href={item.reference_url} target="_blank" rel="noreferrer">查看参考图</a>}</div>)}</details>
      <div className="task-image-grid">{task.items.map((item, index) => <article className={`task-image-card task-image-${item.status}`} key={item.id}>
        {item.image_url ? <button type="button" className="task-image-preview" onClick={() => setSelected(item)} aria-label={`查看第 ${index + 1} 张图片`}><img src={item.preview_url || item.image_url} alt={item.shot_name || `第 ${index + 1} 张生成图片`} loading="lazy" /></button> : <div className="task-image-placeholder"><strong>{taskLabels[item.status] || item.status}</strong>{['failed', 'unknown'].includes(item.status) && <button type="button" className="log-locate-button" title="定位错误日志" aria-label={`查看第 ${index + 1} 张图片的错误日志`} onClick={() => locateLog(item.id)}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M14 3H5v18h14V8zM14 3v5h5M8 12h8M8 16h5"/><circle cx="18" cy="17" r="3"/><path d="m20 19 3 3"/></svg><span>查看日志</span></button>}</div>}
        <div className="task-image-caption">{item.execution_result?.native_pixels && <small>原生尺寸 {item.execution_result.native_pixels.join(" × ")} · 人工检查：{({pending:"待检查",passed:"已通过",rework:"需要修改"} as Record<string,string>)[item.execution_result.review?.status || "pending"]}</small>}<strong>{index + 1}. {item.shot_name || '候选图片'}</strong>{item.execution_profile?.skill_workflow && <small>制作技能：{item.execution_profile.skill_workflow.primary.name} · {item.execution_profile.skill_workflow.primary.version}</small>}
          {item.execution_result?.agent_review && <details><summary>{({passed:'自动质检通过',rework:'质检需要修改',uncertain:'待人工审核'})[item.execution_result.agent_review.status]}</summary><p>{item.execution_result.agent_review.summary}</p><ul>{item.execution_result.agent_review.checks.map(check => <li key={check.item}>{check.detail}</li>)}</ul></details>}
          {item.image_url && <span className={`job-status job-${item.status}`}>{taskLabels[item.status]}</span>}{item.image_url && <div className="result-actions"><button type="button" className="button-secondary" onClick={() => setSelected(item)}>图片详情</button><a href={`${item.image_url}?download=true`}>下载</a><a href={task.agent_run_id && task.can_manage !== false ? `#/studio?run=${task.agent_run_id}&source=${item.id}` : `#/edit?source=${item.id}`}>继续修改</a></div>}</div>
      </article>)}</div>
      {task.completed_job_ids.length > 0 && <ExportDownload jobIds={task.completed_job_ids} count={task.completed_job_ids.length} />}
      <section className="task-logs" aria-label="任务运行日志"><h3>运行日志</h3><div className="task-log-list">{task.items.map((item, index) => {
        const diagnostic = item.diagnostic;
        const failed = ['failed', 'unknown'].includes(item.status);
        const time = diagnostic?.recorded_at || item.updated_at;
        return <article id={`task-log-${taskId}-${item.id}`} key={item.id} tabIndex={-1} ref={element => { if (element) logs.current.set(item.id, element); else logs.current.delete(item.id); }} className={`task-log-card${highlight === item.id ? ' task-log-highlight' : ''}${failed ? ' task-log-error' : ''}`} aria-label={`第 ${index + 1} 张图片运行日志`}>
          <header><strong>{index + 1}. {item.shot_name || '候选图片'} · {taskLabels[item.status]}</strong><time dateTime={time}>{formatTaskTime(time)}</time></header>
          {diagnostic ? <><div className="task-log-context">{diagnostic.http_status != null && <strong>HTTP {diagnostic.http_status}</strong>}<code>{diagnostic.method} {diagnostic.path}</code>{diagnostic.elapsed_ms != null && <span>{(diagnostic.elapsed_ms / 1000).toFixed(2)} 秒</span>}</div><pre>{diagnostic.response_body || diagnostic.provider_message || diagnostic.error_type || item.message}</pre>{diagnostic.request_id && <small className="task-request-id">Request ID: {diagnostic.request_id}</small>}</> : <p>{item.message || taskLabels[item.status]}{failed && <small className="task-legacy-log">此历史记录未保存服务商响应正文。</small>}</p>}
        </article>;
      })}</div></section>
      <ImageRecordDialog item={selected} onClose={() => setSelected(undefined)} onChanged={() => { void poller.current?.refresh(); }} />
    </>}
  </section>;
}
