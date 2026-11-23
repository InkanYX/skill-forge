import { useEffect, useId, useRef, useState } from 'react';

export default function ExportDownload({ jobIds, setId, count }: { jobIds?: string[]; setId?: string; count: number }) {
  const [records, setRecords] = useState(true); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [download, setDownload] = useState<{ url: string; name: string; count: number }>();
  const mounted = useRef(true); const controller = useRef<AbortController | null>(null); const checkboxId = useId();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; controller.current?.abort(); }; }, []);
  useEffect(() => () => { if (download) URL.revokeObjectURL(download.url); }, [download]);
  async function exportZip() {
    if (busy || count < 1 || count > 50) return;
    const selectedCount = count;
    setBusy(true); setError(''); setDownload(undefined);
    const body = new FormData(); body.set('include_records', String(records));
    if (setId) body.set('set_id', setId); else body.set('job_ids', JSON.stringify(jobIds || []));
    const abort = new AbortController(); controller.current = abort;
    const timeout = window.setTimeout(() => abort.abort(), 120000);
    try {
      const response = await fetch('/api/image-jobs/exports', { method: 'POST', body, signal: abort.signal });
      if (!response.ok) { const value = await response.json().catch(() => null); throw new Error(typeof value?.detail === 'string' ? value.detail : `导出失败（HTTP ${response.status}）`); }
      if (!response.headers.get('content-type')?.includes('application/zip')) throw new Error('导出格式异常，请检查后端服务。');
      const blob = await response.blob();
      if (!mounted.current) return;
      const filename = response.headers.get('content-disposition')?.match(/filename="([^"]+)"/)?.[1] || 'skill-forge-images.zip';
      const actualCount = Number(response.headers.get('x-export-count')) || selectedCount;
      const url = URL.createObjectURL(blob); setDownload({ url, name: filename, count: actualCount });
      const link = document.createElement('a'); link.href = url; link.download = filename; document.body.appendChild(link); link.click(); link.remove();
    } catch (err) { if (mounted.current) setError(err instanceof Error && err.name !== 'AbortError' ? err.message : '导出超时或已中止，请减少图片数量后重试。'); }
    finally { window.clearTimeout(timeout); if (mounted.current) setBusy(false); }
  }
  return <div className="export-controls"><div className="export-actions"><label htmlFor={checkboxId}><input id={checkboxId} type="checkbox" checked={records} disabled={busy} onChange={e => setRecords(e.target.checked)} />附制作记录（含提示词与产品信息）</label><button type="button" className="button-primary export-download" aria-busy={busy} disabled={busy || count < 1 || count > 50} onClick={exportZip}>{busy ? '正在打包…' : setId ? `导出已完成图片（${count} 张）` : `导出选中图片（${count} 张）`}</button></div><small>每次最多 50 张、合计 200 MB。{setId ? '包含已完成的修改版。' : '可跨页选择。'}</small>{count > 50 && <p className="feedback feedback-warning">超过单次导出数量，请到生成记录分批勾选。</p>}{error && <p className="feedback feedback-error" role="alert">{error}</p>}{download && <p className="feedback feedback-success" role="status">已准备 {download.count} 张图片的 ZIP。若未自动下载，<a href={download.url} download={download.name}>点击下载</a>。</p>}</div>;
}
