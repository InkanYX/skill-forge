import { useEffect, useRef, useState } from 'react';

export interface CancelReply { id?: string; status?: string; message?: string; cancelled_count?: number }
export default function TaskCancel({ jobId, setId, status, queuedCount = 0, onChanged }: { jobId?: string; setId?: string; status?: string; queuedCount?: number; onChanged?: (reply: CancelReply) => void }) {
  const [busy, setBusy] = useState(false); const [message, setMessage] = useState(''); const [error, setError] = useState(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function cancel() {
    if (busy) return;
    if (setId && !window.confirm('取消本套中仍在排队的任务？已生成图片会保留，已开始的任务会继续执行。')) return;
    setBusy(true); setMessage(''); setError(false);
    const body = new FormData(); body.set('action', 'cancel');
    try {
      const path = setId ? `sets/${setId}/cancel` : `${jobId}/cancel`;
      const response = await fetch(`/api/image-jobs/${path}`, { method: 'POST', body, signal: AbortSignal.timeout(12000) });
      const value = await response.json();
      if (!mounted.current) return;
      if (!response.ok) { onChanged?.({}); throw new Error(typeof value.detail === 'string' ? value.detail : '取消未完成，请刷新任务状态。'); }
      setMessage(value.message || '排队任务已取消。'); onChanged?.(value);
    } catch (err) { if (mounted.current) { setError(true); setMessage(err instanceof Error && err.name !== 'TimeoutError' ? err.message : '取消结果暂未确认，请刷新任务状态后重试。'); } }
    finally { if (mounted.current) setBusy(false); }
  }
  if (!setId && status === 'running') return <p className="form-footnote">任务已开始，可能已调用服务商，当前不支持中止。</p>;
  if (setId ? queuedCount < 1 && !message : status !== 'queued' && !message) return null;
  return <div className="task-cancel">{(setId ? queuedCount > 0 : status === 'queued') && <button type="button" className="button-secondary cancel-button" aria-busy={busy} disabled={busy} onClick={cancel}>{busy ? '取消中…' : setId ? `取消本套排队任务（${queuedCount} 项）` : '取消排队'}</button>}{message && <p className={`feedback feedback-${error ? 'error' : 'success'}`} role={error ? 'alert' : 'status'}>{message}</p>}</div>;
}
