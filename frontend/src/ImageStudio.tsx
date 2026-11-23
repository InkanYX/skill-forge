import ImageSizePicker from './ImageSizePicker';
import TaskResultsPanel from './TaskResultsPanel';
import { formatTaskTime, kindLabels, taskLabels as labels, taskCounts, taskPending, type ImageTaskPage } from './imageTaskApi';
import { startTaskPolling } from './taskPolling';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { listModelOptions as listConfigs, type ModelOption as ModelConfig } from './modelConfigApi';
import { creativeRequest, type CreativeTemplate } from './creativeApi';
import { productValues, type Product, type ProductAsset } from './productApi';

interface CreatedImage { id: string; task_id: string }
const errorMessage = (error: unknown) => error instanceof Error ? error.message : '请求失败，请检查服务状态。';

async function readResponse(response: Response): Promise<unknown> {
  const value = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = value?.detail;
    throw new Error(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: {msg: string}) => item.msg).join('；') : `请求失败（HTTP ${response.status}）`);
  }
  return value;
}

export default function ImageStudio({ active = true }: { active?: boolean }) {
  const [products, setProducts] = useState<Product[]>([]);
  const [productId, setProductId] = useState('');
  const [assets, setAssets] = useState<ProductAsset[]>([]);
  const [assetId, setAssetId] = useState('');
  const [assetsLoading, setAssetsLoading] = useState(false);
  const product = products.find(item => item.id === productId);
  const asset = assets.find(item => item.id === assetId);
  const [templates, setTemplates] = useState<CreativeTemplate[]>([]);
  const [templateId, setTemplateId] = useState('');
  const [values, setValues] = useState<Record<string, string>>({});
  const template = templates.find(item => item.id === templateId);
  const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [configId, setConfigId] = useState('');
  const [count, setCount] = useState(1);
  const [currentTaskId, setCurrentTaskId] = useState('');
  const [prompt, setPrompt] = useState('');
  const [size, setSize] = useState('default');
  const [reference, setReference] = useState<File>();
  const [referencePreview, setReferencePreview] = useState('');
  const [history, setHistory] = useState<ImageTaskPage>();
  const [error, setError] = useState('');
  const [listError, setListError] = useState('');
  const [historyLoading, setHistoryLoading] = useState(false);
  const [pageVisible, setPageVisible] = useState(() => !document.hidden);
  const historyPoller = useRef<ReturnType<typeof startTaskPolling<ImageTaskPage>> | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingConfigs, setLoadingConfigs] = useState(false);
  const [requestId, setRequestId] = useState<string>();
  const [ambiguous, setAmbiguous] = useState(false);
  const alive = useRef(true);
  const referenceInput = useRef<HTMLInputElement>(null);
  const selectedConfig = configs.find((item) => item.id === configId);
  const canGenerate = !!selectedConfig?.has_api_key;

  useEffect(() => {
    let active = true;
    creativeRequest<Product[]>('products').then(items => {
      if (!active) return;
      setProducts(items);
      const wanted = new URLSearchParams(window.location.hash.split('?')[1] || '').get('product');
      const item = items.find(item => item.id === wanted);
      if (item) { setProductId(item.id); setValues(productValues(item)); }
      else if (wanted) setError('关联产品不可用，请重新选择产品。');
    }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let active = true; setAssets([]); setAssetsLoading(false);
    if (!productId) return;
    setAssetsLoading(true);
    creativeRequest<ProductAsset[]>(`products/${productId}/assets`).then(items => { if (active) setAssets(items); }).catch(err => { if (active) setError(err.message); }).finally(() => { if (active) setAssetsLoading(false); });
    return () => { active = false; };
  }, [productId]);

  useEffect(() => {
    let active = true;
    creativeRequest<CreativeTemplate[]>('templates').then(items => {
      if (!active) return;
      setTemplates(items);
      const wanted = new URLSearchParams(window.location.hash.split('?')[1] || '').get('template');
      const item = items.find(item => item.id === wanted);
      if (item) { setTemplateId(item.id); setSize(item.size); setCount(item.count); }
      else if (wanted) setError('关联模板不可用，可以选择其他模板或自由创作。');
    }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, []);

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
    return () => { alive.current = false; };
  }, []);

  useEffect(() => {
    const visibility = () => setPageVisible(!document.hidden);
    document.addEventListener('visibilitychange', visibility);
    return () => document.removeEventListener('visibilitychange', visibility);
  }, []);

  useEffect(() => {
    if (!active || !pageVisible) { setHistoryLoading(false); return; }
    const poller = startTaskPolling<ImageTaskPage>({
      load: async signal => readResponse(await fetch('/api/image-jobs/tasks?page_size=6', { cache: 'no-store', signal })) as Promise<ImageTaskPage>,
      pending: data => data.items.some(taskPending),
      onData: data => { setHistory(data); setListError(''); },
      onError: err => setListError(`${errorMessage(err)} 已停止自动刷新，可点击“刷新任务”重试读取。`),
      onLoading: setHistoryLoading,
    });
    historyPoller.current = poller;
    const focus = () => { void poller.refresh(); };
    window.addEventListener('focus', focus);
    return () => { poller.stop(); historyPoller.current = null; window.removeEventListener('focus', focus); };
  }, [active, pageVisible]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selectedConfig || busy) return;
    const id = requestId || crypto.randomUUID();
    setRequestId(id); setBusy(true); setError('');
    const form = new FormData();
    form.set('config_id', selectedConfig.config_id); form.set('model_name', selectedConfig.model_name); form.set('request_id', id); form.set('count', String(count));
    form.set('prompt', prompt); form.set('size', size);
    if (template) form.set('template', JSON.stringify({ id: template.id, revision: template.revision, variables: values }));
    if (product) form.set('product', JSON.stringify({ id: product.id, revision: product.revision, asset_id: assetId || null }));
    if (reference) form.set('reference', reference);
    try {
      const response = await fetch('/api/image-jobs/batch', { method: 'POST', body: form, signal: AbortSignal.timeout(30000) });
      const created = await readResponse(response) as CreatedImage[];
      if (!alive.current) return;
      setCurrentTaskId(created[0]?.task_id || id); setRequestId(undefined); setAmbiguous(false);
      void historyPoller.current?.refresh();
    } catch (err) {
      if (!alive.current) return;
      setError(`${errorMessage(err)} 若请求已到达后端，任务仍可能已创建。请先核对下方列表；重发相同提交会复用同一标识。`);
      setAmbiguous(true);
      void historyPoller.current?.refresh();
    } finally { if (alive.current) setBusy(false); }
  }

  function unlockDraft() {
    if (!window.confirm('请先核对任务列表。修改输入将放弃原提交标识；再次提交可能产生新的模型调用，是否继续？')) return;
    setAmbiguous(false); setRequestId(undefined); setError('');
  }

  return <section className="image-studio" aria-label="自由创作内容">
    <div className="studio-layout">
      <form className="studio-form" onSubmit={submit}>
        <div className="form-field"><label htmlFor="generation-config">生图模型</label><div className="input-with-action"><select id="generation-config" required disabled={busy || ambiguous} value={configId} onChange={(event) => setConfigId(event.target.value)}><option value="">请选择已配置的模型</option>{configs.map((item) => <option key={item.id} value={item.id} disabled={!item.model_name.trim()}>{item.name} · {item.model_name || '未设置模型'}</option>)}</select><button type="button" className="button-secondary" disabled={loadingConfigs || busy || ambiguous} onClick={refreshConfigs}>{loadingConfigs ? '读取中' : '刷新'}</button></div>{!loadingConfigs && !configs.some((item) => item.model_name.trim()) && <small>请先到<a href="#/settings">个人模型配置</a>保存图片模型。</small>}</div>
        <fieldset disabled={busy || ambiguous}>
          <div className="form-field"><label htmlFor="creative-product">产品资料</label><select id="creative-product" value={productId} onChange={e => { const item = products.find(item => item.id === e.target.value); setProductId(e.target.value); setAssetId(''); setValues(previous => ({ ...previous, ...productValues(item) })); }}><option value="">不关联产品，临时创作</option>{products.map(item => <option key={item.id} value={item.id}>{item.sku} · {item.name}</option>)}</select><small>产品信息会随本次创作保存。<a href="#/products">管理产品资料</a></small>{product && <small>{product.color || '颜色未填写'} · {product.dimensions || '尺寸未填写'} · 版本 {product.revision}</small>}</div>
          {product && <div className="form-field"><label htmlFor="creative-asset">产品素材参考图</label><select id="creative-asset" value={assetId} disabled={assetsLoading} onChange={e => { setAssetId(e.target.value); if (e.target.value) { setReference(undefined); if (referenceInput.current) referenceInput.current.value = ''; } }}><option value="">{assetsLoading ? '正在读取素材…' : '不使用素材库图片'}</option>{assets.map(item => <option key={item.id} value={item.id}>{item.kind} · {item.name}</option>)}</select>{asset && <div className="reference-preview"><img src={asset.image_url} alt={asset.name} /></div>}<small>一次选一张参考图；也可以使用下方临时上传。</small></div>}
          <div className="form-field"><label htmlFor="creative-template">创作模板</label><select id="creative-template" value={templateId} onChange={e => { const item = templates.find(item => item.id === e.target.value); setTemplateId(e.target.value); setValues(productValues(product)); if (item) { setSize(item.size); setCount(item.count); } else { setCount(1); } }}><option value="">自由创作</option>{templates.map(item => <option value={item.id} key={item.id}>{item.name} · 版本 {item.revision}</option>)}</select><small>{template?.purpose || '可套用已保存的制作方法，或直接填写图片要求。'} <a href="#/templates">管理模板</a></small></div>
          {template?.variables.map(key => <div className="form-field" key={key}><label htmlFor={`variable-${key}`}>{key}</label><input id={`variable-${key}`} required maxLength={2000} value={values[key] || ''} onChange={e => setValues(previous => ({ ...previous, [key]: e.target.value }))} /></div>)}
          {template && <details className="template-preview"><summary>查看模板要求和 Skill</summary><p>{template.prompt}</p>{template.skill && <p>{template.skill}</p>}{template.notes && <p>{template.notes}</p>}</details>}
          <div className="form-field"><label htmlFor="generation-prompt">{template ? "本次补充要求（可选）" : "图片要求"}</label><textarea id="generation-prompt" required={!template} maxLength={8000} rows={6} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="例如：将参考图中的凉棚置于现代庭院，保持立柱、横梁、棚顶结构和颜色，匹配自然光与真实比例。" /><small>{prompt.length} / 8000 字符</small></div>
          <ImageSizePicker id="generation-size" value={size} onChange={setSize} />
          <div className="form-field"><label htmlFor="generation-count">生成数量</label><select id="generation-count" value={count} onChange={(event) => setCount(Number(event.target.value))}>{Array.from({ length: 8 }, (_, index) => index + 1).map((value) => <option key={value} value={value}>{value} 张</option>)}</select><small>使用同一制作要求，每张独立生成，便于比较和挑选。</small></div>
          <div className="form-field"><label htmlFor="reference-image">产品参考图 <span>可选</span></label><input ref={referenceInput} id="reference-image" type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (file) setAssetId(''); if (file && file.size > 20 * 1024 * 1024) { setError('参考图不能超过 20 MB。'); event.target.value = ''; setReference(undefined); } else { setReference(file); setError(''); } }} /><small>单张 PNG、JPEG 或 WebP，最多 20 MB、2000 万像素。参考图将随任务发送到所选服务商。</small>{referencePreview && <div className="reference-preview"><img src={referencePreview} alt="本次产品参考图" /><button type="button" className="button-secondary" onClick={() => { setReference(undefined); if (referenceInput.current) referenceInput.current.value = ''; }}>移除参考图</button></div>}</div>
        </fieldset>
        {selectedConfig && !canGenerate && <p className="feedback feedback-warning">请先在<a href="#/settings">个人模型配置</a>填写并保存 API Key。</p>}
        {error && <div className="feedback feedback-error" role="alert">{error}</div>}
        <div className="form-actions">{ambiguous && <button type="button" className="button-secondary" onClick={unlockDraft}>核对后修改输入</button>}<button type="submit" className="button-primary" disabled={busy || !canGenerate || !selectedConfig?.model_name.trim() || (!template && !prompt.trim()) || !!template?.variables.some(key => !values[key]?.trim())}>{busy ? '正在提交…' : ambiguous ? '重发相同提交' : `生成 ${count} 张图片`}</button></div>
        <p className="form-footnote">本次将提交 {count} 张图片，按张调用所选服务商并消耗其额度。刷新或切换页面不会取消已提交任务。</p>
      </form>
      <div className="studio-result">
        {currentTaskId ? <TaskResultsPanel taskId={currentTaskId} active={active} /> : <div className="result-placeholder empty-result"><span className="step-icon">图片</span><h3>等待本次创作</h3><p>提交后在这里查看本次任务的图片和运行日志。</p></div>}
      </div>
    </div>
    <div className="section-heading history-heading"><h3>最近任务</h3><div className="history-actions"><button type="button" className="button-secondary" disabled={historyLoading} onClick={() => { void historyPoller.current?.refresh(); }}>{historyLoading ? '读取中…' : '刷新任务'}</button><a className="button-secondary" href="#/library">查看全部生成记录</a></div></div>
    {listError && <div className="feedback feedback-error" role="alert">{listError}</div>}
    <div className="job-history">{history?.items.map(task => <button type="button" key={task.id} className={`history-item ${currentTaskId === task.id ? 'history-selected' : ''}`} onClick={() => setCurrentTaskId(task.id)}><span className="history-image-label">{labels[task.status]}</span><span><strong>{kindLabels[task.kind]} · {task.title}</strong><small>{task.counts.total} 张 · {taskCounts(task)} · {formatTaskTime(task.created_at)}</small></span></button>)}</div>
  </section>;
}
