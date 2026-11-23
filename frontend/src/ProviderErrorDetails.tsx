import { useEffect, useState } from 'react';
import { creativeRequest } from './creativeApi';

interface Diagnostic {
  method: string; path: string; http_status: number | null;
  response_body?: string; provider_message: string; error_type: string; request_id: string;
}
interface LogResult { diagnostic: Diagnostic | null }
const logs = new Map<string, Promise<LogResult>>();
export const isJobError = (status: string) => status === 'failed' || status === 'unknown';
function readLog(id: string, retry = false) {
  if (retry) logs.delete(id);
  if (!logs.has(id)) {
    if (logs.size >= 100) logs.delete(logs.keys().next().value!);
    logs.set(id, creativeRequest<LogResult>(`image-jobs/${id}/diagnostics`).catch(error => { logs.delete(id); throw error; }));
  }
  return logs.get(id)!;
}

export default function ProviderErrorDetails({ jobId, status, compact = false }: { jobId: string; status: string; compact?: boolean }) {
  const [result, setResult] = useState<LogResult>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!isJobError(status)) return;
    let active = true; setResult(undefined); setLoading(true); setError('');
    readLog(jobId, attempt > 0).then(value => { if (active) setResult(value); })
      .catch(() => { if (active) setError('错误信息读取失败'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [jobId, status, attempt]);
  if (!isJobError(status)) return null;
  const log = result?.diagnostic;
  const body = log?.response_body || log?.provider_message || log?.error_type || '服务商未返回错误正文';
  return <div className={`provider-error-card${compact ? ' provider-error-compact' : ''}`} data-job-error={jobId}>
    <div className="provider-error-heading"><strong>{status === 'unknown' ? '结果待确认' : '生成失败'}</strong>{log?.http_status != null && <span>HTTP {log.http_status}</span>}</div>
    {loading ? <p>读取错误信息…</p> : error ? <p>{error}{!compact && <button type="button" className="button-secondary" onClick={() => setAttempt(value => value + 1)}>重新读取</button>}</p>
      : log ? <><pre>{body}</pre><small>{log.method} {log.path}</small>{log.request_id && <small>Request ID: {log.request_id}</small>}</>
      : <p>未保存服务商原始响应</p>}
  </div>;
}
