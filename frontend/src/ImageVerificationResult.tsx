import { useEffect, useRef, useState } from 'react';
import { startTaskPolling } from './taskPolling';
import { formatTaskTime, readTaskResponse, type ImageTaskDetail } from './imageTaskApi';

export default function ImageVerificationResult({taskId,onFinished}:{taskId:string;onFinished:()=>void}) {
  const [task,setTask]=useState<ImageTaskDetail>();
  const [error,setError]=useState(''); const [loading,setLoading]=useState(true);
  const poller=useRef<ReturnType<typeof startTaskPolling<ImageTaskDetail>>|null>(null);
  const finished=useRef(''); const onFinishedRef=useRef(onFinished); onFinishedRef.current=onFinished;
  useEffect(()=>{
    setTask(undefined);setError('');finished.current='';
    const current=startTaskPolling<ImageTaskDetail>({
      load:async signal=>readTaskResponse(await fetch(`/api/image-jobs/tasks/${encodeURIComponent(taskId)}`,{signal,cache:'no-store'})),
      pending:value=>['queued','running'].includes(value.status),
      onData:value=>{setTask(value);setError('');if(!['queued','running'].includes(value.status)&&finished.current!==value.id){finished.current=value.id;onFinishedRef.current();}},
      onError:err=>setError(err instanceof Error?err.message:'结果读取失败，请重新读取。'),onLoading:setLoading,
    });poller.current=current;return()=>{current.stop();poller.current=null;};
  },[taskId]);
  const item=task?.items[0]; const diagnostic=item?.diagnostic;
  const state=item?.status;
  const title=state==='succeeded'?'验证通过':state==='failed'?'验证失败':state==='unknown'?'结果待确认':state==='cancelled'?'验证已取消':state==='queued'?'验证任务已排队':'正在生成测试图片';
  const tone=state==='succeeded'?'success':state==='failed'?'error':state==='unknown'?'warning':'neutral';
  return <div className="verification-result" aria-live="polite">
    {error&&<div className="settings-feedback settings-feedback-error" role="alert"><strong>结果读取失败</strong><p>{error}</p><button type="button" className="button-secondary" disabled={loading} onClick={()=>{void poller.current?.refresh();}}>重新读取结果</button></div>}
    {!item&&!error&&<p className="verification-loading" role="status">正在读取验证结果…</p>}
    {item&&<><div className={`verification-outcome verification-outcome-${tone}`}><span className="verification-outcome-icon" aria-hidden="true">{state==='succeeded'?'✓':state==='failed'?'!':state==='unknown'?'?':'·'}</span><div><strong>{title}</strong><p>{state==='succeeded'?'已收到图片并保存，本次接口能力验证通过。':state==='unknown'?'请求可能已被服务商接受。请先核对服务商记录，再决定是否重新验证。':item.message}</p></div>{diagnostic?.http_status!=null&&<span className="verification-http">HTTP {diagnostic.http_status}</span>}</div>
      <div className="verification-result-meta"><time dateTime={item.updated_at}>{formatTaskTime(item.updated_at)}</time>{diagnostic?.elapsed_ms!=null&&<span>{(diagnostic.elapsed_ms/1000).toFixed(2)} 秒</span>}<a href={`#/library?task=${taskId}`}>打开任务记录 ↗</a></div>
      {item.image_url&&<figure className="verification-image"><a href={item.image_url} target="_blank" rel="noreferrer"><img src={item.preview_url||item.image_url} alt="接口验证返回的测试图片" /></a><figcaption>服务商返回图片{item.execution_result?.native_pixels&&` · ${item.execution_result.native_pixels.join(' × ')} px`}</figcaption></figure>}
      {diagnostic&&<div className="verification-response"><div><strong>服务商返回</strong><code>{diagnostic.method} {diagnostic.path}</code></div><pre>{diagnostic.response_body||diagnostic.provider_message||diagnostic.error_type||item.message}</pre>{diagnostic.request_id&&<small>Request ID: {diagnostic.request_id}</small>}</div>}
      {state==='failed'&&!diagnostic&&<p className="verification-no-response">{item.message} 当前记录没有保存服务商响应正文。</p>}
    </>}
  </div>;
}
