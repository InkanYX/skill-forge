import TaskCancel from './TaskCancel';
import { useEffect, useState, type FormEvent } from 'react';
import { creativeRequest } from './creativeApi';
import { listModelOptions as listConfigs, type ModelOption as ModelConfig } from './modelConfigApi';
import RevisionTrail from './RevisionTrail';

interface RevisionJob {
  id: string; config_id: string; model_name: string; size: string; status: string; message: string; prompt: string;
  image_url: string | null; parent_job_id: string | null; product_snapshot: { sku?: string; name?: string };
}
const labels: Record<string, string> = { queued: '排队中', running: '生成中', succeeded: '已完成', failed: '未完成', unknown: '结果待确认', cancelled: '已取消' };
export default function ImageRevision() {
  const sourceId = new URLSearchParams(window.location.hash.split('?')[1] || '').get('source') || '';
  const [source, setSource] = useState<RevisionJob>(); const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [configId, setConfigId] = useState(''); const [prompt, setPrompt] = useState(''); const [count, setCount] = useState(1); const [size, setSize] = useState('default');
  const [loading, setLoading] = useState(true); const [attempt, setAttempt] = useState(0); const [sourceError, setSourceError] = useState(''); const [error, setError] = useState('');
  const [busy, setBusy] = useState(false); const [requestId, setRequestId] = useState(''); const [ambiguous, setAmbiguous] = useState(false);
  const [jobs, setJobs] = useState<RevisionJob[]>([]); const [ids, setIds] = useState<string[]>([]); const [pollError, setPollError] = useState('');
  const model = configs.find(item => item.id === configId);
  useEffect(() => {
    let active = true; setLoading(true); setSourceError('');
    if (!sourceId) { setSourceError('请先从作品库选择一张已完成图片，再点击“继续修改”。'); setLoading(false); return; }
    Promise.all([creativeRequest<RevisionJob>(`image-jobs/${encodeURIComponent(sourceId)}`), listConfigs()]).then(([item, connections]) => {
      if (!active) return;
      if (item.status !== 'succeeded' || !item.image_url) { setSourceError('这张作品尚未完成，请在完成后继续修改。'); return; }
      setSource(item); setConfigs(connections); setSize(['default','1024x1024','1536x1024','1024x1536'].includes(item.size) ? item.size : 'default');
      setConfigId(connections.find(c => c.config_id === item.config_id && c.model_name === item.model_name)?.id || connections.find(c => c.config_id === item.config_id)?.id || connections.find(c => c.model_name.trim())?.id || '');
    }).catch(err => { if (active) setSourceError(err instanceof Error ? err.message : '无法读取来源作品。'); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [sourceId, attempt]);
  useEffect(() => {
    if (!ids.length) return;
    let active = true; let timer: number;
    async function poll() {
      try {
        const items = await Promise.all(ids.map(id => creativeRequest<RevisionJob>(`image-jobs/${id}`)));
        if (!active) return;
        setJobs(items); setPollError('');
        if (items.some(item => ['queued','running'].includes(item.status))) timer = window.setTimeout(poll, 3000);
      } catch { if (active) { setPollError('进度暂时无法更新，正在重试。'); timer = window.setTimeout(poll, 5000); } }
    }
    void poll(); return () => { active = false; window.clearTimeout(timer); };
  }, [ids]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!source || !model || busy) return;
    const id = requestId || crypto.randomUUID(); setRequestId(id); setBusy(true); setError('');
    const body = new FormData();
    for (const [key, value] of Object.entries({ config_id: model.config_id, model_name: model.model_name, request_id: id, source_job_id: source.id, prompt, count: String(count), size })) body.set(key, value);
    try {
      const response = await fetch('/api/image-jobs/batch', { method: 'POST', body, signal: AbortSignal.timeout(30000) }); const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '修改任务提交失败。');
      const items = value as RevisionJob[]; setJobs(items); setIds(items.map(item => item.id)); setAmbiguous(false); setRequestId('');
    } catch (err) { setError(`${err instanceof Error ? err.message : '提交结果无法确认。'} 请先核对作品库。重发相同提交会复用原任务。`); setAmbiguous(true); }
    finally { setBusy(false); }
  }
  function unlock() { if (window.confirm('请先核对作品库。修改输入后再次提交会创建新任务，是否继续？')) { setAmbiguous(false); setRequestId(''); setError(''); } }
  return <section><div className="section-heading"><div><p className="eyebrow">REFINE YOUR IMAGE</p><h2>继续修改</h2></div><a className="button-secondary" href="#/library">返回作品库</a></div><p className="settings-intro">以选中的作品为参考，只填写这次想调整的内容。每次保存为新版本，原图始终保留。</p>
    {loading && <p role="status">正在读取来源作品…</p>}{sourceError && <p className="feedback feedback-error" role="alert">{sourceError} {sourceId && <button className="button-secondary" onClick={() => setAttempt(value => value + 1)}>重新读取</button>}</p>}
    {!loading && !sourceError && source && <><div className="revision-layout"><section className="revision-source"><h3>来源作品</h3><a href={source.image_url!} target="_blank" rel="noreferrer"><img src={source.image_url!} alt="本次修改的来源作品" /></a><p>{source.product_snapshot.sku ? `${source.product_snapshot.sku} · ${source.product_snapshot.name}` : '未关联产品资料'}</p><small>原模型：{source.model_name}。沿用来源作品保存的产品资料和模板记录。</small><details><summary>查看来源制作要求</summary><p className="case-prompt">{source.prompt}</p></details></section>
    <form className="revision-form" onSubmit={submit}><fieldset disabled={busy || ambiguous}><div className="form-field"><label htmlFor="revision-model">生图模型</label><select id="revision-model" required value={configId} onChange={e => setConfigId(e.target.value)}><option value="">请选择已配置模型</option>{configs.map(item => <option key={item.id} value={item.id} disabled={!item.model_name.trim()}>{item.name} · {item.model_name || '未指定模型'}</option>)}</select><small>使用当前保存的配置调用图片编辑接口。<a href="#/settings">管理模型配置</a></small></div>
    <div className="form-field"><label htmlFor="revision-prompt">本次修改要求</label><textarea id="revision-prompt" required maxLength={8000} rows={6} value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="例如：将背景换成现代庭院，调整为柔和的傍晚光线，保持产品结构、颜色和构图。" /><small>明确写出需要变化和需要保留的内容。</small></div>
    <div className="template-defaults"><div className="form-field"><label htmlFor="revision-count">生成新版本数量</label><select id="revision-count" value={count} onChange={e => setCount(Number(e.target.value))}>{[1,2,3,4,5,6,7,8].map(n => <option key={n} value={n}>{n} 张</option>)}</select></div><div className="form-field"><label htmlFor="revision-size">输出尺寸</label><select id="revision-size" value={size} onChange={e => setSize(e.target.value)}><option value="default">服务商默认</option><option value="1024x1024">1024 × 1024</option><option value="1536x1024">1536 × 1024</option><option value="1024x1536">1024 × 1536</option></select></div></div></fieldset>
    {error && <p className="feedback feedback-error" role="alert">{error}</p>}<div className="form-actions">{ambiguous && <button type="button" className="button-secondary" onClick={unlock}>核对后修改输入</button>}<button className="button-primary" disabled={busy || !model?.model_name.trim() || !prompt.trim()}>{busy ? '正在提交…' : ambiguous ? '重发相同提交' : `生成 ${count} 张新版本`}</button></div><p className="form-footnote">点击后会将来源图片和修改要求发送到所选服务商，每张独立消耗额度。不会覆盖原图，修改效果需人工检查。</p></form></div>
    {!!jobs.length && <section className="revision-results"><h3>本次修改结果</h3>{pollError && <p className="feedback feedback-warning">{pollError}</p>}<div className="case-grid">{jobs.map((item, index) => <article className="case-card" key={item.id}><h3>新版本 {index + 1} · {labels[item.status]}</h3>{item.image_url ? <a href={item.image_url} target="_blank" rel="noreferrer"><img src={item.image_url} alt={`修改后的第 ${index + 1} 张图片`} /></a> : <div className="result-placeholder"><p>{item.message}</p></div>}<p>{item.message}</p><TaskCancel key={item.id} jobId={item.id} status={item.status} onChanged={reply => { if (reply.status === "cancelled") setJobs(previous => previous.map(job => job.id === item.id ? { ...job, status: "cancelled", message: reply.message || "已取消排队。" } : job)); }} />{item.status === 'unknown' && <p>请核对服务商生成和计费记录，本任务不会自动重试。</p>}<div className="result-actions">{item.image_url && <a className="button-primary" href={`${item.image_url}?download=true`}>下载 PNG</a>}<a className="button-secondary" href={`#/library?job=${item.id}`}>查看记录与对比</a>{item.image_url && <a className="button-secondary" href={`#/edit?source=${item.id}`}>继续修改此版本</a>}</div></article>)}</div></section>}
    <RevisionTrail jobId={source.id} /></>}
  </section>;
}
