import { createRequestId } from './requestId';
import { apiFetch } from './apiFetch';
import { useCallback, useEffect, useRef, useState } from 'react';
import ExportDownload from './ExportDownload';
import { formatImageSize } from './ImageSizePicker';
import ImageRecordDialog from './ImageRecordDialog';
import ImageRetry from './ImageRetry';
import SkillExecutionInfo from './SkillExecutionInfo';
import RevisionAnalysisInfo from './RevisionAnalysisInfo';
import InlineImageRevision from './InlineImageRevision';
import { startTaskPolling } from './taskPolling';
import { imageBatches, type ImageBatch } from './imageBatches.mjs';
import { formatTaskTime, readTaskResponse, taskCounts, taskLabels, taskPending, type ImageRecord, type ImageTaskDetail } from './imageTaskApi';

export default function TaskResultsPanel({ taskId, active = true, focusJobId, batches, onChanged }: { taskId: string; active?: boolean; focusJobId?: string; batches?: ImageBatch[]; onChanged?: () => void }) {
  const [rawTask, setTask] = useState<ImageTaskDetail>();
  const [batchId, setBatchId] = useState('latest');
  const [pendingDelete, setPendingDelete] = useState('');
  const [deletedId, setDeletedId] = useState('');
  const [removing, setRemoving] = useState(false);
  const [managing,setManaging]=useState(false);
  const [checkedBatches,setCheckedBatches]=useState<string[]>([]);
  const [confirmBatches,setConfirmBatches]=useState(false);
  const [batchUndo,setBatchUndo]=useState('');
  const changeCallback=useRef(onChanged);changeCallback.current=onChanged;
  const taskSignature=useRef('');
  const [editingId,setEditingId]=useState('');
  const [revisionItems,setRevisionItems]=useState<Record<string,ImageRecord>>({});
  const [revisionReload,setRevisionReload]=useState(0);
  const displayRevision=useCallback((rootId:string,item:ImageRecord)=>setRevisionItems(previous=>({...previous,[rootId]:item})),[]);
  const batchList = rawTask?.batches || batches;
  const groups = batchList && rawTask ? imageBatches(rawTask.items, batchList) : [];
  const currentBatch = groups.find(group => group.id === batchId) || groups[0];
  const oldGroups=groups.filter(group=>batchList?.some(b=>b.execution_id===group.id)&&group.id!==batchList?.at(-1)?.execution_id);
  const task = rawTask && currentBatch ? {...rawTask, items: currentBatch.items,
    model_name:currentBatch.items[0]?.model_name||rawTask.model_name, config_name:currentBatch.items[0]?.config_name||rawTask.config_name,
    created_at:currentBatch.created_at,
    counts: currentBatch.items.reduce<Record<string,number>>((counts,item)=>({...counts,[item.status]:(counts[item.status]||0)+1}), {total:currentBatch.items.length}),
    completed_job_ids: currentBatch.items.filter(item=>item.status==='succeeded').map(item=>item.id)} : rawTask;
  const [error, setError] = useState(''); const [loading, setLoading] = useState(true);
  const slotItems=task?.items.filter(item=>!task.items.some(parent=>parent.id===item.parent_job_id))||[];
  const visibleItems=slotItems.map(item=>revisionItems[item.id]||item);
  const exportIds=visibleItems.filter(item=>item.status==='succeeded').map(item=>item.id);
  const visibleCounts=visibleItems.reduce<Record<string,number>>((counts,item)=>({...counts,[item.status]:(counts[item.status]||0)+1}),{total:visibleItems.length});
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
    setRevisionItems({});setEditingId('');
  }, [taskId]);
  useEffect(() => {
    if (!active || !pageVisible) return;
    const current = startTaskPolling<ImageTaskDetail>({
      load: async signal => readTaskResponse(await apiFetch(`/api/image-jobs/tasks/${encodeURIComponent(taskId)}`, { signal, cache: 'no-store' })),
      pending: taskPending, onData: value => {
        const signature=JSON.stringify(value.items.map(item=>[item.id,item.status]));
        if(taskSignature.current!==signature){taskSignature.current=signature;changeCallback.current?.();}
        setTask(value); setError('');
      },
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
    if (!rawTask || !focusJobId || located.current === focusJobId) return;
    const group = groups.find(group => [...group.items, ...group.history].some(item => item.id === focusJobId));
    if (group) setBatchId(group.id);
  }, [rawTask, focusJobId]);
  useEffect(() => {
    if (!task || !focusJobId || located.current === focusJobId) return;
    const item = [...task.items, ...(currentBatch?.history || [])].find(item => item.id === focusJobId);
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
      await poller.current?.refresh(); setRevisionReload(value=>value+1); onChanged?.();
    } catch(err) {setError(err instanceof Error?err.message:'删除失败，请重试。');}
    finally {setRemoving(false);}
  }
  async function restoreImage() {
    setRemoving(true); setError('');
    try {
      const body = new FormData(); body.set('action', 'restore');
      await readTaskResponse(await apiFetch(`/api/image-jobs/${deletedId}/restore`, {method:'POST', body, signal:AbortSignal.timeout(12000)}));
      setDeletedId(''); await poller.current?.refresh(); setRevisionReload(value=>value+1); onChanged?.();
    } catch(err) {setError(err instanceof Error?err.message:'恢复失败，请重试。');}
    finally {setRemoving(false);}
  }
  async function changeVersions(restore=false){
    setRemoving(true);setError('');
    try{
      const token=restore?batchUndo:createRequestId();
      await readTaskResponse(await apiFetch(`/api/creation-projects/${taskId}/batches/${restore?'restore/'+token:'delete'}`,{
        method:'POST',headers:{'Content-Type':'application/json'},
        ...(restore?{}:{body:JSON.stringify({batch_ids:checkedBatches,request_id:token})}),signal:AbortSignal.timeout(20000),
      }));
      setBatchUndo(restore?'':token);setCheckedBatches([]);setConfirmBatches(false);setBatchId('latest');
      setRevisionItems({});setEditingId('');setSelected(undefined);
      await poller.current?.refresh();setRevisionReload(value=>value+1);onChanged?.();
    }catch(err){setError(err instanceof Error?err.message:'版本操作失败，请重试。');}
    finally{setRemoving(false);}
  }
  return <section className="task-results-panel" aria-label="任务运行结果">
    <div className="task-result-toolbar"><div><h3>运行结果{task && ` · ${slotItems.length} 张`}</h3>{task && <p>{taskCounts({...task,counts:visibleCounts})}</p>}</div><div className="task-toolbar-actions">{(task?.counts.queued || 0) > 0 && task?.can_manage !== false && <button type="button" className="button-secondary" disabled={cancelling} onClick={cancel}>{cancelling ? '取消中…' : '取消排队'}</button>}<button type="button" className="button-secondary" disabled={loading} onClick={() => { void poller.current?.refresh();setRevisionReload(value=>value+1); }}>{loading ? '读取中…' : '刷新进度'}</button></div></div>
    {error && <p className="feedback feedback-error" role="alert">{error}</p>}
    {deletedId && <p className="feedback" role="status">图片已移入回收状态，原文件保留。<button type="button" className="button-secondary" disabled={removing} onClick={()=>void restoreImage()}>撤销删除</button></p>}
    {batchUndo&&<p className="feedback" role="status">所选旧版本已删除，原始文件保留。<button type="button" className="button-secondary" disabled={removing} onClick={()=>void changeVersions(true)}>撤销版本删除</button></p>}
    {!!oldGroups.length&&rawTask?.can_manage!==false&&<div className="version-manager">
      <button type="button" className="button-secondary" aria-expanded={managing} onClick={()=>{setManaging(!managing);setConfirmBatches(false);}}>管理旧版本</button>
      {managing&&<fieldset disabled={removing}><legend>批量删除旧版本</legend><p>保留最新版本。删除包含该版的重试记录与后续修改，可撤销；正在生成或结果待确认的版本需先处理。</p>
        <div className="guided-actions"><button type="button" className="button-secondary" onClick={()=>{setCheckedBatches(oldGroups.filter(g=>![...g.items,...g.history].some(i=>['queued','running','unknown'].includes(i.status))).map(g=>g.id));setConfirmBatches(false);}}>全选可删除版本</button><button type="button" className="button-secondary" onClick={()=>{setCheckedBatches([]);setConfirmBatches(false);}}>清空选择</button></div>
        {oldGroups.map(group=>{const blocked=[...group.items,...group.history].some(i=>['queued','running','unknown'].includes(i.status));return <label className="version-choice" key={group.id}><input type="checkbox" checked={checkedBatches.includes(group.id)} disabled={blocked} onChange={e=>{setCheckedBatches(ids=>e.target.checked?[...ids,group.id]:ids.filter(id=>id!==group.id));setConfirmBatches(false);}}/><span>{group.label} · {group.items.length} 张 · {formatTaskTime(group.created_at)}{blocked?' · 请先确认任务结果':''}</span></label>;})}
        {confirmBatches?<div className="guided-actions"><span>确认删除选中的 {checkedBatches.length} 个旧版本？</span><button type="button" className="button-secondary" onClick={()=>void changeVersions()}>确认删除版本</button><button type="button" className="button-secondary" onClick={()=>setConfirmBatches(false)}>取消</button></div>:<button type="button" className="button-secondary" disabled={!checkedBatches.length} onClick={()=>setConfirmBatches(true)}>删除所选版本（{checkedBatches.length}）</button>}
      </fieldset>}
    </div>}
    {!!groups.length && <div className="image-batch-selector"><label>生成版本<select value={batchId==='latest'?'latest':currentBatch?.id} onChange={event=>{setBatchId(event.target.value);setPendingDelete('');}}><option value="latest">最新版本 · {groups[0].label}</option>{groups.map(group=><option key={group.id} value={group.id}>{group.label} · {formatTaskTime(group.created_at)} · {group.items.length} 张</option>)}</select></label><p>整批提交保存为一版；失败重试留在原版本的原位置，历史尝试保留在运行日志中。</p></div>}
    {!task && !error && <p role="status">正在读取任务…</p>}
    {task && <>
      <div className="task-run-meta"><time dateTime={task.created_at}>提交于 {formatTaskTime(task.created_at)}</time><span>{task.config_name} · {task.model_name}</span></div>
      {currentBatch && <p className="image-batch-heading"><strong>{currentBatch.label}</strong> · {formatTaskTime(currentBatch.created_at)}</p>}
      {typeof task.items[0]?.execution_profile?.creation_project_id === 'string' && <div className="guided-actions"><a href={'#/planning?project='+task.items[0].execution_profile.creation_project_id}>查看来源策划方案</a><a href={'#/studio?project='+task.items[0].execution_profile.creation_project_id}>返回方案生图</a></div>}
      {task.agent_run_id && <div className="feedback feedback-warning"><strong>创作任务 · 共 {task.turn_count} 轮 · {taskLabels[task.status] || task.status}</strong>{task.agent_summary && <p>{task.agent_summary}</p>}{task.can_manage !== false && <a href={`#/studio?run=${task.agent_run_id}`}>打开制作对话与执行记录</a>}</div>}
      <details className="task-input-details"><summary>查看本次制作要求</summary>{task.items.map((item, index) => <div key={item.id}><strong>{index + 1}. {item.shot_name || '候选图片'} · {item.execution_profile?.backend ? formatImageSize(item.size) : item.size === "default" ? "自动（未指定尺寸）" : `${item.size.replace("x", " × ")} 像素`}</strong><p className="case-prompt">{item.prompt}</p>{item.reference_url && <a href={item.reference_url} target="_blank" rel="noreferrer">查看参考图</a>}</div>)}</details>
      <div className="task-image-grid">{slotItems.map((root, index) => {const item=revisionItems[root.id]||root;return <article className={`task-image-card task-image-${item.status}${editingId===root.id?' task-image-editing':''}`} key={root.id}>
        {item.image_url ? <button type="button" className="task-image-preview" onClick={() => setSelected(item)} aria-label={`查看第 ${index + 1} 张图片`}><img src={item.preview_url || item.image_url} alt={item.shot_name || `第 ${index + 1} 张生成图片`} loading="lazy" /></button> : <div className="task-image-placeholder"><strong>{taskLabels[item.status] || item.status}</strong>{['failed', 'unknown'].includes(item.status) && <button type="button" className="log-locate-button" title="定位错误日志" aria-label={`查看第 ${index + 1} 张图片的错误日志`} onClick={() => locateLog(item.id)}><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><path d="M14 3H5v18h14V8zM14 3v5h5M8 12h8M8 16h5"/><circle cx="18" cy="17" r="3"/><path d="m20 19 3 3"/></svg><span>查看日志</span></button>}</div>}
        <div className="task-image-caption">{item.execution_result?.native_pixels && <small>原生尺寸 {item.execution_result.native_pixels.join(" × ")} · 图片反馈：{({pending:"待评价",passed:"满意",rework:"需要修改"} as Record<string,string>)[item.execution_result.review?.status || "pending"]}</small>}<strong>{index + 1}. {item.shot_name || '候选图片'}</strong><SkillExecutionInfo item={item} />
          {item.execution_result?.agent_review && <details><summary>{({passed:'自动质检通过',rework:'质检需要修改',uncertain:'待人工审核'})[item.execution_result.agent_review.status]}</summary><p>{item.execution_result.agent_review.summary}</p><ul>{item.execution_result.agent_review.checks.map(check => <li key={check.item}>{check.detail}</li>)}</ul></details>}
          {item.image_url && <span className={`job-status job-${item.status}`}>{taskLabels[item.status]}</span>}{item.image_url && <div className="result-actions"><button type="button" className="button-secondary" onClick={() => setSelected(item)}>图片详情</button><a href={`${item.image_url}?download=true`}>下载</a>{item.can_edit!==false&&task.can_manage!==false&&<button type="button" className="button-secondary" aria-expanded={editingId===root.id} onClick={()=>setEditingId(root.id)}>继续修改</button>}</div>}</div>
        {item.id!==root.id&&<p className="inline-revision-status" role="status">{taskLabels[item.status]||item.status} · {item.message}</p>}
        <RevisionAnalysisInfo item={item}/>
        {task.can_manage !== false && <ImageRetry key={item.id} item={item} onSubmitted={()=>{void poller.current?.refresh();setRevisionReload(value=>value+1);onChanged?.();}} />}
        <InlineImageRevision source={root} open={editingId===root.id} onClose={()=>setEditingId('')} onDisplay={displayRevision} reload={revisionReload} canEdit={item.can_edit!==false&&task.can_manage!==false}/>
        {item.can_edit !== false && task.can_manage !== false && !['queued','running','unknown'].includes(item.status) && <div className="image-delete-actions">{pendingDelete===item.id?<><span>删除此图片？可撤销，原文件保留。</span><button type="button" className="button-secondary" disabled={removing} onClick={()=>void removeImage(item)}>确认删除</button><button type="button" className="button-secondary" disabled={removing} onClick={()=>setPendingDelete('')}>取消</button></>:<button type="button" className="image-delete-button" disabled={removing} onClick={()=>setPendingDelete(item.id)}>删除图片</button>}</div>}
      </article>;})}</div>
      {!task.items.length&&<p>此版本暂无可显示图片，已删除的图片不会出现在记录中。</p>}
      {exportIds.length > 0 && <ExportDownload jobIds={exportIds} count={exportIds.length} />}
      <section className="task-logs" aria-label="任务运行日志"><h3>运行日志</h3>{!!currentBatch?.history.length && <p>含 {currentBatch.history.length} 条历史尝试；图片数量及导出仅统计当前结果。</p>}<div className="task-log-list">{[...visibleItems, ...(currentBatch?.history || [])].map((item, index) => {
        const diagnostic = item.diagnostic;
        const failed = ['failed', 'unknown'].includes(item.status);
        const time = diagnostic?.recorded_at || item.updated_at;
        return <article id={`task-log-${taskId}-${item.id}`} key={item.id} tabIndex={-1} ref={element => { if (element) logs.current.set(item.id, element); else logs.current.delete(item.id); }} className={`task-log-card${highlight === item.id ? ' task-log-highlight' : ''}${failed ? ' task-log-error' : ''}`} aria-label={`第 ${index + 1} 张图片运行日志`}>
          <header><strong>{index >= task.items.length ? '历史尝试' : `${index + 1}.`} {item.shot_name || '候选图片'} · {taskLabels[item.status]}</strong><time dateTime={time}>{formatTaskTime(time)}</time></header>
          {typeof item.execution_profile?.retry_source_job_id==='string'&&<p>本条为单张重试，<a href={'#/library?job='+item.execution_profile.retry_source_job_id}>查看原失败记录</a>。</p>}
          {!!item.execution_result?.attempts?.length&&<details><summary>调用记录 · {item.execution_result.attempts.length} 次{item.execution_result.attempts.length>1?'（含自动补试）':''}</summary>{item.execution_result.attempts.map(a=><p key={a.attempt}>第 {a.attempt} 次：{taskLabels[a.status]||a.status} {a.diagnostic?.http_status&&`HTTP ${a.diagnostic.http_status}`} · {formatTaskTime(a.at)}</p>)}</details>}
          {diagnostic ? <><div className="task-log-context">{diagnostic.http_status != null && <strong>HTTP {diagnostic.http_status}</strong>}<code>{diagnostic.method} {diagnostic.path}</code>{diagnostic.elapsed_ms != null && <span>{(diagnostic.elapsed_ms / 1000).toFixed(2)} 秒</span>}</div><pre>{diagnostic.response_body || diagnostic.provider_message || diagnostic.error_type || item.message}</pre>{diagnostic.request_id && <small className="task-request-id">Request ID: {diagnostic.request_id}</small>}</> : <p>{item.message || taskLabels[item.status]}{failed && <small className="task-legacy-log">此历史记录未保存服务商响应正文。</small>}</p>}
        </article>;
      })}</div></section>
      <ImageRecordDialog item={selected} onClose={() => setSelected(undefined)} onChanged={() => { void poller.current?.refresh();setRevisionReload(value=>value+1); }} onEdit={item=>{
        const root=slotItems.find(root=>(revisionItems[root.id]||root).id===item.id);
        if(root)setEditingId(root.id);
      }} />
    </>}
  </section>;
}
