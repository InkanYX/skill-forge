import { useRef, useState } from 'react';
import { apiFetch } from './apiFetch';
import { readTaskResponse, type ImageRecord } from './imageTaskApi';

export default function ImageRetry({item,onSubmitted}:{item:ImageRecord;onSubmitted:()=>void}) {
  const requestId = useRef(crypto.randomUUID());
  const busy = useRef(false);
  const [submitting,setSubmitting] = useState(false);
  const [error,setError] = useState('');
  const [created,setCreated] = useState<ImageRecord>();
  if (!['failed','cancelled'].includes(item.status) || item.can_edit === false) return null;
  async function retry() {
    if (busy.current || created) return;
    busy.current=true; setSubmitting(true); setError('');
    const body = new FormData(); body.set('request_id',requestId.current);
    try {
      const result = await readTaskResponse<ImageRecord>(await apiFetch(`/api/image-jobs/${item.id}/retry`,{
        method:'POST',body,signal:AbortSignal.timeout(20000),
      }));
      setCreated(result); onSubmitted();
    } catch(err) { setError(err instanceof Error?err.message:'重试提交结果待核对，请刷新记录；再次点击会沿用同一提交标识。'); }
    finally { busy.current=false; setSubmitting(false); }
  }
  return <div className="image-retry-actions">
    {created?<p role="status">重试记录已保存。<a href={'#/library?job='+created.id}>查看重试进度 →</a></p>:<>
      <button type="button" className="button-secondary" disabled={submitting} onClick={()=>void retry()}>{submitting?'正在提交…':'重试生图（最多 3 次）'}</button>
      <small>沿用原模型、提示词和参考图，新建任务并保留原失败记录。</small>
    </>}
    {error&&<p className="feedback feedback-error" role="alert">{error}</p>}
  </div>;
}
