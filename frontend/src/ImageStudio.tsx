import { useEffect, useRef, useState, type FormEvent } from 'react';
import { listConfigs, type ModelConfig } from './modelConfigApi';

interface ImageJob {
  id: string; config_name: string; model_name: string; prompt: string; size: string;
  mode: string; status: string; message: string; created_at: string; updated_at: string;
  image_url: string | null; reference_url: string | null;
}

const labels: Record<string, string> = { queued: '排队中', running: '生成中', succeeded: '已完成', failed: '未完成', unknown: '结果未知' };
const errorMessage = (error: unknown) => error instanceof Error ? error.message : '请求失败，请检查服务状态。';

async function readResponse(response: Response): Promise<unknown> {
  const value = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = value?.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: {msg: string}) => item.msg).join('；') : `请求失败（HTTP ${response.status}）`);
  }
  return value;
}

export default function ImageStudio() {
  const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [configId, setConfigId] = useState('');
  const [count, setCount] = useState(4);
  const [batchIds, setBatchIds] = useState<string[]>([]);
  const [prompt, setPrompt] = useState('');
  const [size, setSize] = useState('default');
  const [reference, setReference] = useState<File>();
  const [referencePreview, setReferencePreview] = useState('');
  const [jobs, setJobs] = useState<ImageJob[]>([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState('');
  const [listError, setListError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loadingConfigs, setLoadingConfigs] = useState(false);
  const [requestId, setRequestId] = useState<string>();
  const [ambiguous, setAmbiguous] = useState(false);
  const alive = useRef(true);
  const referenceInput = useRef<HTMLInputElement>(null);
  const current = jobs.find((job) => job.id === selected) || jobs[0];
  const selectedConfig = configs.find((item) => item.id === configId);
  const batch = batchIds.map((id) => jobs.find((job) => job.id === id)).filter((job): job is ImageJob => !!job);

  useEffect(() => {
    if (!reference) { setReferencePreview(''); return; }
    const url = URL.createObjectURL(reference); setReferencePreview(url);
    return () => URL.revokeObjectURL(url);
  }, [reference]);

  async function refreshConfigs() {
    setLoadingConfigs(true);
    try {
      const items = await listConfigs();
      if (alive.current) {
        setConfigs(items); setError('');
        setConfigId((existing) => items.some((item) => item.id === existing && item.model_name.trim()) ? existing : items.find((item) => item.model_name.trim())?.id || '');
      }
    } catch (err) { if (alive.current) setError(errorMessage(err)); }
    finally { if (alive.current) setLoadingConfigs(false); }
  }

  useEffect(() => {
    alive.current = true;
    void refreshConfigs();
    let stopped = false;
    let timer: number;
    let controller: AbortController | undefined;
    async function poll() {
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller?.abort(), 8000);
      try {
        const response = await fetch('/api/image-jobs', { cache: 'no-store', signal: controller.signal });
        const value = await readResponse(response) as ImageJob[];
        if (!stopped) { setJobs(value); setListError(''); }
      } catch (err) { if (!stopped) setListError(errorMessage(err)); }
      finally { window.clearTimeout(timeout); if (!stopped) timer = window.setTimeout(poll, 3000); }
    }
    void poll();
    return () => { stopped = true; alive.current = false; window.clearTimeout(timer); controller?.abort(); };
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const id = requestId || crypto.randomUUID();
    setRequestId(id); setBusy(true); setError('');
    const form = new FormData();
    form.set('config_id', configId); form.set('request_id', id); form.set('count', String(count));
    form.set('prompt', prompt); form.set('size', size);
    if (reference) form.set('reference', reference);
    try {
      const response = await fetch('/api/image-jobs/batch', { method: 'POST', body: form, signal: AbortSignal.timeout(30000) });
      const created = await readResponse(response) as ImageJob[];
      if (!alive.current) return;
      setJobs((items) => [...created, ...items.filter((item) => !created.some((job) => job.id === item.id))].slice(0, 30));
      setBatchIds(created.map((job) => job.id));
      setSelected(created[0]?.id || ''); setRequestId(undefined); setAmbiguous(false);
    } catch (err) {
      if (!alive.current) return;
      setError(`${errorMessage(err)} 若请求已到达后端，任务仍可能已创建。请先核对下方列表；重发相同提交会复用同一标识。`);
      setAmbiguous(true);
    } finally { if (alive.current) setBusy(false); }
  }

  function unlockDraft() {
    if (!window.confirm('请先核对任务列表。修改输入将放弃原提交标识；再次提交可能产生新的模型调用，是否继续？')) return;
    setAmbiguous(false); setRequestId(undefined); setError('');
  }

  return <section className="image-studio" aria-labelledby="image-studio-heading">
    <div className="section-heading"><div><p className="eyebrow">CREATE YOUR NEXT IMAGES</p><h2 id="image-studio-heading">多图制作</h2></div><span>一次制作 1–8 张</span></div>
    <p className="settings-intro">选择已配置的模型、填写画面要求，一次生成多张候选图。添加产品参考图，可在原图基础上制作。</p>
    <div className="studio-layout">
      <form className="studio-form" onSubmit={submit}>
        <div className="form-field"><label htmlFor="generation-config">生图模型</label><div className="input-with-action"><select id="generation-config" required disabled={busy || ambiguous} value={configId} onChange={(event) => setConfigId(event.target.value)}><option value="">请选择已配置的模型</option>{configs.map((item) => <option key={item.id} value={item.id} disabled={!item.model_name.trim()}>{item.name} · {item.model_name || '未设置模型'}</option>)}</select><button type="button" className="button-secondary" disabled={loadingConfigs || busy || ambiguous} onClick={refreshConfigs}>{loadingConfigs ? '读取中' : '刷新'}</button></div>{!loadingConfigs && !configs.some((item) => item.model_name.trim()) && <small>请先到<a href="#/settings">个人模型配置</a>保存图片模型。</small>}</div>
        <fieldset disabled={busy || ambiguous}>
          <div className="form-field"><label htmlFor="generation-prompt">图片要求</label><textarea id="generation-prompt" required maxLength={8000} rows={6} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="例如：将参考图中的凉棚置于现代庭院，保持立柱、横梁、棚顶结构和颜色，匹配自然光与真实比例。" /><small>{prompt.length} / 8000 字符</small></div>
          <div className="form-field"><label htmlFor="generation-size">输出尺寸</label><select id="generation-size" value={size} onChange={(event) => setSize(event.target.value)}><option value="default">服务商默认</option><option value="1024x1024">方形 · 1024 × 1024</option><option value="1536x1024">横向 · 1536 × 1024</option><option value="1024x1536">纵向 · 1024 × 1536</option></select><small>具体尺寸需要所选服务商和模型支持。</small></div>
          <div className="form-field"><label htmlFor="generation-count">生成数量</label><select id="generation-count" value={count} onChange={(event) => setCount(Number(event.target.value))}>{Array.from({ length: 8 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>{value} 张</option>)}</select><small>使用同一制作要求，每张独立生成，便于比较和挑选。</small></div>
          <div className="form-field"><label htmlFor="reference-image">产品参考图 <span>可选</span></label><input ref={referenceInput} id="reference-image" type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file && file.size > 20 * 1024 * 1024) { setError('参考图不能超过 20 MB。'); event.target.value = ''; setReference(undefined); } else { setReference(file); setError(''); } }} /><small>单张 PNG、JPEG 或 WebP，最多 20 MB、2000 万像素。参考图将随任务发送到所选服务商。</small>{referencePreview && <div className="reference-preview"><img src={referencePreview} alt="本次产品参考图" /><button type="button" className="button-secondary" onClick={() => { setReference(undefined); if (referenceInput.current) referenceInput.current.value = ''; }}>移除参考图</button></div>}</div>
        </fieldset>
        {error && <div className="feedback feedback-error" role="alert">{error}</div>}
        <div className="form-actions">{ambiguous && <button type="button" className="button-secondary" onClick={unlockDraft}>核对后修改输入</button>}<button type="submit" className="button-primary" disabled={busy || !selectedConfig?.model_name.trim() || !prompt.trim()}>{busy ? '正在提交…' : ambiguous ? '重发相同提交' : `生成 ${count} 张图片`}</button></div>
        <p className="form-footnote">本次将提交 {count} 张图片，按张调用所选服务商并消耗其额度。刷新或切换页面不会取消已提交任务。</p>
      </form>
      <div className="studio-result" aria-live="polite">
        {batch.length > 0 && <section className="batch-results" aria-label="本次多图结果"><div className="result-heading"><h3>本次制作 · {batch.length} 张</h3><span>{batch.filter((job) => job.status === 'succeeded').length} 张已完成</span></div><div className="batch-grid">{batch.map((job, index) => <button key={job.id} type="button" aria-pressed={current?.id === job.id} className={`batch-item ${current?.id === job.id ? 'batch-selected' : ''}`} onClick={() => setSelected(job.id)}>{job.image_url ? <img src={job.image_url} alt={`第 ${index + 1} 张生成结果`} /> : <span className="batch-placeholder">{labels[job.status]}</span>}<span>第 {index + 1} 张 · {labels[job.status]}</span></button>)}</div></section>}
        {current ? <><div className="result-heading"><h3>制作结果</h3><span className={`job-status job-${current.status}`}>{labels[current.status] || current.status}</span></div>{current.image_url ? <a href={current.image_url} target="_blank" rel="noreferrer"><img className="generated-image" src={current.image_url} alt="当前任务生成的图片" /></a> : <div className="result-placeholder"><strong>{current.status === 'running' ? '正在制作画面' : current.status === 'queued' ? '任务已进入队列' : '本次暂未获得图片'}</strong><p>{current.message}</p></div>}<p className="result-message">{current.message}</p><dl className="job-details"><div><dt>模型</dt><dd>{current.model_name}</dd></div><div><dt>制作方式</dt><dd>{current.mode === 'edit' ? '参考图编辑' : '文字生图'}</dd></div><div><dt>创建时间</dt><dd>{new Date(current.created_at).toLocaleString('zh-CN')}</dd></div></dl><p className="job-prompt">{current.prompt}</p><div className="result-actions">{current.image_url && <a className="button-primary" href={`${current.image_url}?download=true`}>下载 PNG</a>}{current.reference_url && <a className="button-secondary" href={current.reference_url} target="_blank" rel="noreferrer">查看参考图</a>}</div>{current.status === 'unknown' && <div className="feedback feedback-warning">请先在服务商核对是否已生成／计费。此任务不会自动重试，再次点击生成将创建新任务。</div>}</> : <div className="result-placeholder empty-result"><span className="step-icon">作品</span><h3>第一张图片，从这里开始</h3><p>提交后会在这里展示状态和结果。<br />历史记录保存在数据库，图片保存在本机。</p></div>}
      </div>
    </div>
    <div className="section-heading history-heading"><h3>最近任务</h3><span>自动刷新 · 最近 30 项</span></div>
    {listError && <div className="feedback feedback-error" role="alert">{listError}</div>}
    <div className="job-history">{jobs.map((job) => <button type="button" key={job.id} className={`history-item ${current?.id === job.id ? 'history-selected' : ''}`} onClick={() => setSelected(job.id)}>{job.image_url ? <img src={job.image_url} alt="生成结果缩略预览" loading="lazy" /> : <span className="history-image-label">{labels[job.status] || job.status}</span>}<span><strong>{job.prompt}</strong><small>{job.model_name} · {labels[job.status]} · {new Date(job.created_at).toLocaleString('zh-CN')}</small></span></button>)}</div>
  </section>;
}
