import { apiFetch } from './apiFetch';
import { useEffect, useRef, useState } from 'react';
import ExportDownload from './ExportDownload';
import { formatImageSize } from './ImageSizePicker';
import ImageRecordDialog from './ImageRecordDialog';
import SkillExecutionInfo from './SkillExecutionInfo';
import { startTaskPolling } from './taskPolling';
import { imageBatches, type ImageBatch } from './imageBatches.mjs';
import { formatTaskTime, readTaskResponse, taskCounts, taskLabels, taskPending, type ImageRecord, type ImageTaskDetail } from './imageTaskApi';

export default function TaskResultsPanel({ taskId, active = true, focusJobId, batches, onChanged }: { taskId: string; active?: boolean; focusJobId?: string; batches?: ImageBatch[]; onChanged?: () => void }) {
  const [rawTask, setTask] = useState<ImageTaskDetail>();
  const [batchId, setBatchId] = useState('latest');
  const [pendingDelete, setPendingDelete] = useState('');
  const [deletedId, setDeletedId] = useState('');
  const [removing, setRemoving] = useState(false);
  const batchList = batches || rawTask?.batches;
  const groups = batchList && rawTask ? imageBatches(rawTask.items, batchList) : [];
  const currentBatch = groups.find(group => group.id === batchId) || groups[0];
  const task = rawTask && currentBatch ? {...rawTask, items: currentBatch.items,
    model_name:currentBatch.items[0]?.model_name||rawTask.model_name, config_name:currentBatch.items[0]?.config_name||rawTask.config_name,
    created_at:currentBatch.created_at,
    counts: currentBatch.items.reduce<Record<string,number>>((counts,item)=>({...counts,[item.status]:(counts[item.status]||0)+1}), {total:currentBatch.items.length}),
    completed_job_ids: currentBatch.items.filter(item=>item.status==='succeeded').map(item=>item.id)} : rawTask;
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
    setTask(undefined); setSelected(undefined); setError(''); setHighlight(''); setBatchId('latest'); setPendingDelete(''); setDeletedId(''); located.current = '';
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
      if(currentBatch) {
        for(const item of currentBatch.items.filter(item=>item.status==='queued')) {
          await readTaskResponse(await apiFetch(`/api/image-jobs/${item.id}/cancel`, {method:'POST',body,signal:AbortSignal.timeout(12000)}));
        }
      } else {
        await readTaskResponse(await apiFetch(`/api/image-jobs/tasks/${taskId}/cancel`, { method: 'POST', body, signal: AbortSignal.timeout(12000) }));
      }
      await poller.current?.refresh();
    } catch (err) { setError(err instanceof Error ? err.message : '取消未完成。'); }
    finally { setCancelling(false); }
  }
  async function removeImage(item: ImageRecord) {
    setRemoving(true); setError('');
    try {
      await readTaskResponse(await apiFetch(`/api/image-jobs/${item.id}`, {method:'DELETE', signal:AbortSignal.timeout(12000)}));
      setDeletedId(item.id); setPendingDelete(''); setSelected(undefined);
      await poller.current?.refresh(); onChanged?.();
    } catch(err) {setError(err instanceof Error?err.message:'删除失败，请重试。');}
    finally {setRemoving(false);}
  }
  async function restoreImage() {
    setRemoving(true); setError('');
    try {
      const body = new FormData(); body.set('action', 'restore');
      await readTaskResponse(await apiFetch(`/api/image-jobs/${deletedId}/restore`, {method:'POST', body, signal:AbortSignal.timeout(12000)}));
      setDeletedId(''); await poller.current?.refresh(); onChanged?.();
    } catch(err) {setError(err instanceof Error?err.message:'恢复失败，请重试。');}
    finally {setRemoving(false);}
  }
  return <section className="task-results-panel" aria-label="任务运行结果">
    <div className="task-result-toolbar"><div><h3>运行结果{task && ` · ${task.counts.total} 张`}</h3>{task && <p>{taskCounts(task)}</p>}</div><div className="task-toolbar-actions">{(task?.counts.queued || 0) > 0 && task?.can_manage !== false && <button type="button" className="button-secondary" disabled={cancelling} onClick={cancel}>{cancelling ? '取消中…' : '取消排队'}</button>}<button type="button" className="button-secondary" disabled={loading} onClick={() => { void poller.current?.refresh(); }}>{loading ? '读取中…' : '刷新进度'}</button></div></div>
    {error && <p className="feedback feedback-error" role="alert">{error}</p>}
    {deletedId && <p className="feedback" role="status">图片已移入回收状态，原文件保留。<button type="button" className="button-secondary" disabled={removing} onClick={()=>void restoreImage()}>撤销删除</button></p>}
    {!!groups.length && <div className="image-batch-selector"><label>生成版本<select value={batchId==='latest'?'latest':currentBatch?.id} onChange={event=>{setBatchId(event.target.value);setPendingDelete('');}}><option value="latest">最新版本 · {groups[0].label}</option>{groups.map(group=><option key={group.id} value={group.id}>{group.label} · {formatTaskTime(group.created_at)} · {group.items.length} 张</option>)}</select></label><p>每次提交单独保存为一版，当前仅显示所选版本的图片、提示词和日志。</p></div>}
    {!task && !error && <p role="status">正在读取任务…</p>}
    {task && <>
      <div className="task-run-meta"><time dateTime={task.created_at}>提交于 {formatTaskTime(task.created_at)}</time><span>{task.config_name} · {task.model_name}</span></div>
      {currentBatch && <p className="image-batch-heading"><strong>{currentBatch.label}</strong> · {formatTaskTime(currentBatch.created_at)}</p>}
      {typeof task.items[0]?.execution_profile?.creation_project_id === 'string' && <div className="guided-actions"><a href={'#/planning?project='+task.items[0].execution_profile.creation_project_id}>查看来源策划方案</a><a href={'#/studio?project='+task.items[0].execution_profile.creation_project_id}>返回方案生图</a></div>}
      {task.agent_run_id && <div className="feedback feedback-warning"><strong>创作任务 · 共 {task.turn_count} 轮 · {taskLabels[task.status] || task.status}</strong>{task.agent_summary && <p>{task.agent_summary}</p>}{task.can_manage !== false && <a href={`#/studio?run=${task.agent_run_id}`}>打开制作对话与执行记录</a>}</div>}
      <details className="task-input-details"><summary>查看本次制作要求</summary>{task.items.map((item, index) => <div key={item.id}><strong>{index + 1}. {item.shot_name || '候选图片'} · {item.execution_profile?.backend ? formatImageSize(item.size) : item.size === "default" ? "自动（未指定尺寸）" : `${item.size.replace("x", " × ")} 像素`}</strong><p className="case-prompt">{item.prompt}</p>{item.reference_url && <a href={item.reference_url} target="_blank" rel="noreferrer">查看参考图</a>}</div>)}</details>
      <div className="task-image-grid">{task.items.map((item, index) => <article className={`task-image-card task-image-${item.status}`} key={item.id}>
        {item.image_url ? <button type="button" className="task-image-preview" onClick={() => setSelected(item)} aria-label={`查看第 ${index + 1} 张图片`}><img src={item.preview_url || item.image_url} alt={item.shot_name || `第 ${index + 1} 张生成图片`} loading="lazy" /></button> : <div className="task-image-placeholder"><strong>{taskLabels[item.status] || item.status}</strong>{['failed', 'unknown'].includes(item.status) && <button type="button" className="log-locate-button" title="定位错误日志" aria-label={`查看第 ${index + 1} 张图片的错误日志`} onClick={() => locateLog(item.id)}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M14 3H5v18h14V8zM14 3v5h5M8 12h8M8 16h5"/><circle cx="18" cy="17" r="3"/><path d="m20 19 3 3"/></svg><span>查看日志</span></button>}</div>}
        <div className="task-image-caption">{item.execution_result?.native_pixels && <small>原生尺寸 {item.execution_result.native_pixels.join(" × ")} · 图片反馈：{({pending:"待评价",passed:"满意",rework:"需要修改"} as Record<string,string>)[item.execution_result.review?.status || "pending"]}</small>}<strong>{index + 1}. {item.shot_name || '候选图片'}</strong><SkillExecutionInfo item={item} />
          {item.execution_result?.agent_review && <details><summary>{({passed:'自动质检通过',rework:'质检需要修改',uncertain:'待人工审核'})[item.execution_result.agent_review.status]}</summary><p>{item.execution_result.agent_review.summary}</p><ul>{item.execution_result.agent_review.checks.map(check => <li key={check.item}>{check.detail}</li>)}</ul></details>}
          {item.image_url && <span className={`job-status job-${item.status}`}>{taskLabels[item.status]}</span>}{item.image_url && <div className="result-actions"><button type="button" className="button-secondary" onClick={() => setSelected(item)}>图片详情</button><a href={`${item.image_url}?download=true`}>下载</a><a href={task.agent_run_id && task.can_manage !== false ? `#/studio?run=${task.agent_run_id}&source=${item.id}` : `#/edit?source=${item.id}`}>继续修改</a></div>}</div>
        {item.can_edit !== false && task.can_manage !== false && !['queued','running','unknown'].includes(item.status) && <div className="image-delete-actions">{pendingDelete===item.id?<><span>删除此图片？可撤销，原文件保留。</span><button type="button" className="button-secondary" disabled={removing} onClick={()=>void removeImage(item)}>确认删除</button><button type="button" className="button-secondary" disabled={removing} onClick={()=>setPendingDelete('')}>取消</button></>:<button type="button" className="image-delete-button" disabled={removing} onClick={()=>setPendingDelete(item.id)}>删除图片</button>}</div>}
      </article>)}</div>
      {!task.items.length&&<p>此版本暂无可显示图片，已删除的图片不会出现在记录中。</p>}
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
