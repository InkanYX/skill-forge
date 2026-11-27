import { createRequestId } from './requestId';
import { useRef, useState } from 'react';
import { apiFetch } from './apiFetch';
import { readTaskResponse, type ImageRecord } from './imageTaskApi';

export default function ImageRetry({item,onSubmitted}:{item:ImageRecord;onSubmitted:()=>void}) {
  const requestId = useRef(createRequestId());
  const busy = useRef(false);
  const [submitting,setSubmitting] = useState(false);
  const [error,setError] = useState('');
  const [created,setCreated] = useState<ImageRecord>();
  const [confirming,setConfirming] = useState(false);
  const [checked,setChecked] = useState(false);
  const uncertain = item.status === 'unknown';
  if (!['failed','cancelled','unknown'].includes(item.status) || item.can_edit === false) return null;
  async function retry() {
    if (busy.current || created || (uncertain && !checked)) return;
    busy.current=true; setSubmitting(true); setError('');
    const body = new FormData(); body.set('request_id',requestId.current);
    if (uncertain) body.set('provider_checked','true');
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
      {uncertain ? <>
        {!confirming ? <button type="button" className="button-secondary" onClick={()=>setConfirming(true)}>核对后重新生成</button> : <div className="image-retry-confirmation">
          <p>服务商报错、超时或连接中断，原请求可能已经生成或计费。请先查看服务商任务与账单；找到可用图片时请勿重复提交。</p>
          <label><input type="checkbox" checked={checked} disabled={submitting} onChange={event=>setChecked(event.target.checked)}/>我已核对服务商生成与计费记录，未找到可用图片，并确认重新生成可能产生新的费用。</label>
          <div className="guided-actions"><button type="button" className="button-secondary" disabled={!checked||submitting} onClick={()=>void retry()}>{submitting?'正在提交…':'确认重新生成'}</button><button type="button" className="button-secondary" disabled={submitting} onClick={()=>{setConfirming(false);setChecked(false);setError('');}}>取消</button></div>
        </div>}
      </> : <button type="button" className="button-secondary" disabled={submitting} onClick={()=>void retry()}>{submitting?'正在提交…':'重试生图（最多 3 次）'}</button>}
      <small>沿用原模型、提示词和参考图，重试图片保留在原版本的原位置，历史记录保留。明确失败最多尝试 3 次，超时仍会停止并等待核对。</small>
    </>}
    {error&&<p className="feedback feedback-error" role="alert">{error}</p>}
  </div>;
}
