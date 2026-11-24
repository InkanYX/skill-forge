import { apiFetch } from './apiFetch';
import TaskResultsPanel from './TaskResultsPanel';
import ImageSizePicker, { formatImageSize } from './ImageSizePicker';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { creativeRequest, type CreativeTemplate } from './creativeApi';
import { listModelOptions as listConfigs, type ModelOption as ModelConfig } from './modelConfigApi';
import { productValues, type Product, type ProductAsset } from './productApi';
import TemplateVariableField from './TemplateVariableField';
import { CreationSkillPicker, useCreationSkill } from './CreationSkillContext';

interface Shot { id: string; name: string; prompt: string; size: string }
function defaultShots(): Shot[] {
  return [
    ['主体展示', '展示完整产品，背景干净，突出真实外形、材质和颜色。不要增加未随产品销售的配件。'],
    ['庭院场景', '将产品放置在现代庭院，保持真实比例和自然接触阴影，产品主体清晰完整。'],
    ['结构细节', '展示参考图中真实可见的立柱、横梁和连接结构，不自行设计被遮挡的结构。'],
    ['尺寸说明', '仅使用已确认的产品尺寸制作清晰的尺寸说明，不推测参数；尺寸未提供时不要添加尺寸数字或标签。'],
    ['使用场景', '表现产品在日常户外空间中的使用方式，保持尺度准确；不添加产品未包含的配件或未经确认的功能。'],
    ['材质近景', '展示参考图可见的表面纹理、涂层和细节，不虚构材质或性能，不夸大效果。'],
  ].map(([name, prompt]) => ({ id: crypto.randomUUID(), name, prompt, size: 'default' }));
}

export default function ImageSetStudio({ showSkillPicker = true }: {showSkillPicker?: boolean}) {
  const creationSkill = useCreationSkill();
  const setId = new URLSearchParams(window.location.hash.split('?')[1] || '').get('set') || '';
  const [configs, setConfigs] = useState<ModelConfig[]>([]); const [products, setProducts] = useState<Product[]>([]); const [templates, setTemplates] = useState<CreativeTemplate[]>([]);
  const [configId, setConfigId] = useState(''); const [productId, setProductId] = useState(''); const [assetId, setAssetId] = useState(''); const [assets, setAssets] = useState<ProductAsset[]>([]);
  const [templateId, setTemplateId] = useState(''); const [values, setValues] = useState<Record<string, string>>({});
  const [name, setName] = useState('产品图片套图'); const [common, setCommon] = useState('保持同一产品的结构、比例、颜色和材质一致。使用真实自然光，不虚构参数或产品性能。');
  const [shots, setShots] = useState<Shot[]>(defaultShots); const [reference, setReference] = useState<File>(); const [preview, setPreview] = useState('');
  const [loading, setLoading] = useState(!setId); const [busy, setBusy] = useState(false); const [dirty, setDirty] = useState(false); const [error, setError] = useState('');
  const [review, setReview] = useState(false); const [requestId, setRequestId] = useState(''); const [ambiguous, setAmbiguous] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null); const referenceInput = useRef<HTMLInputElement>(null);
  const product = products.find(item => item.id === productId); const template = templates.find(item => item.id === templateId); const model = configs.find(item => item.id === configId);
  const canGenerate = !!model?.has_api_key && creationSkill.ready;
  useEffect(() => {
    if (setId) return;
    let active = true;
    Promise.all([listConfigs(), creativeRequest<Product[]>('products'), creativeRequest<CreativeTemplate[]>('templates')]).then(([c, p, t]) => {
      if (active) { setConfigs(c); setProducts(p); setTemplates(t); setConfigId(c.find(item => item.model_name.trim())?.id || ''); }
    }).catch(err => { if (active) setError(err.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [setId]);
  useEffect(() => {
    let active = true; setAssets([]);
    if (!productId) return;
    creativeRequest<ProductAsset[]>(`products/${productId}/assets`).then(value => { if (active) setAssets(value); }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [productId]);
  useEffect(() => { if (!reference) { setPreview(''); return; } const url = URL.createObjectURL(reference); setPreview(url); return () => URL.revokeObjectURL(url); }, [reference]);
  useEffect(() => { if (review) dialog.current?.showModal(); else dialog.current?.close(); }, [review]);
  useEffect(() => {
    const unload = (event: BeforeUnloadEvent) => { if (dirty || busy || ambiguous) event.preventDefault(); };
    const leave = (event: MouseEvent) => { const link = event.target instanceof Element ? event.target.closest('a') : null; if ((dirty || busy || ambiguous) && link?.getAttribute('href')?.startsWith('#/') && !window.confirm('清单尚未提交或提交结果未确认，确定离开吗？')) event.preventDefault(); };
    window.addEventListener('beforeunload', unload); document.addEventListener('click', leave, true);
    return () => { window.removeEventListener('beforeunload', unload); document.removeEventListener('click', leave, true); };
  }, [dirty, busy, ambiguous]);
  function changeShot(id: string, patch: Partial<Shot>) { setShots(previous => previous.map(item => item.id === id ? { ...item, ...patch } : item)); }
  function move(index: number, direction: number) { setDirty(true); setShots(previous => { const next = [...previous]; [next[index], next[index + direction]] = [next[index + direction], next[index]]; return next; }); }
  function reviewPlan(event: FormEvent) { event.preventDefault(); setError(''); setReview(true); }
  function unlock() { if (window.confirm('请先在生成记录核对。修改清单后再次提交可能创建新任务，是否继续？')) { setAmbiguous(false); setRequestId(''); setReview(false); setError(''); } }
  async function generate() {
    if (busy || !model) return;
    const id = requestId || crypto.randomUUID(); setRequestId(id); setBusy(true); setError('');
    const body = new FormData(); body.set('config_id', model.config_id); body.set('model_name', model.model_name); body.set('request_id', id); body.set('prompt', common);
    body.set('plan', JSON.stringify({ name, shots: shots.map(({ name, prompt, size }) => ({ name, prompt, size })) }));
    if (product) body.set('product', JSON.stringify({ id: product.id, revision: product.revision, asset_id: assetId || null }));
    if (template) body.set('template', JSON.stringify({ id: template.id, revision: template.revision, variables: values }));
    if (reference) body.set('reference', reference);
    try {
      creationSkill.append(body);
      const response = await apiFetch('/api/image-jobs/sets', { method: 'POST', body, signal: AbortSignal.timeout(30000) }); const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '清单提交失败。');
      setDirty(false); setAmbiguous(false); setReview(false); window.location.hash = `#/sets?set=${id}`;
    } catch (err) { setError(`${err instanceof Error ? err.message : '提交结果无法确认。'} 请先在生成记录核对，重发相同提交会复用原任务。`); setAmbiguous(true); }
    finally { setBusy(false); }
  }
  if (setId) return <section><div className="section-heading"><h2>成套制作结果</h2><a className="button-primary" href="#/sets">新建一套图片</a></div><TaskResultsPanel taskId={setId} /></section>;
  return <section aria-label="成套制作内容">
    {showSkillPicker && <CreationSkillPicker />}
    <form onSubmit={reviewPlan} onChange={() => setDirty(true)}><fieldset disabled={loading || busy || ambiguous} className="set-fieldset"><div className="set-context"><div className="form-field"><label htmlFor="set-name">套图名称</label><input id="set-name" required maxLength={100} value={name} onChange={e => setName(e.target.value)} placeholder="例如：灰色凉棚 · Listing 图片" /></div><div className="form-field"><label htmlFor="set-model">生图模型</label><select id="set-model" required value={configId} onChange={e => setConfigId(e.target.value)}><option value="">请选择已配置模型</option>{configs.map(item => <option key={item.id} value={item.id} disabled={!item.model_name.trim()}>{item.name} · {item.model_name || '未设置模型'}</option>)}</select><small>没有可用模型？<a href="#/settings">前往配置</a></small></div>
    <div className="form-field"><label htmlFor="set-product">产品资料</label><select id="set-product" value={productId} onChange={e => { const item = products.find(p => p.id === e.target.value); setProductId(e.target.value); setAssetId(''); setValues(previous => ({ ...previous, ...productValues(item) })); }}><option value="">临时制作，不关联产品</option>{products.map(item => <option key={item.id} value={item.id}>{item.sku} · {item.name}</option>)}</select></div>
    {product && <div className="form-field"><label htmlFor="set-asset">产品参考素材</label><select id="set-asset" value={assetId} onChange={e => { setAssetId(e.target.value); if (e.target.value) { setReference(undefined); if (referenceInput.current) referenceInput.current.value = ''; } }}><option value="">不使用素材库图片</option>{assets.map(item => <option key={item.id} value={item.id}>{item.kind} · {item.name}</option>)}</select></div>}
    <div className="form-field"><label htmlFor="set-reference">临时上传参考图（可选）</label><input ref={referenceInput} id="set-reference" type="file" accept="image/png,image/jpeg,image/webp" onChange={e => { const file = e.target.files?.[0]; if (file && file.size > 20 * 1024 * 1024) { setError('参考图不能超过 20 MB。'); setReference(undefined); setAssetId(''); e.target.value = ''; return; } setReference(file); if (file) setAssetId(''); }} /><small>建议提供同一产品参考图，最多 20 MB。选择后会替代素材库参考图。</small>{(preview || assetId) && <div className="reference-preview"><img src={preview || assets.find(item => item.id === assetId)?.image_url} alt="本套共用参考图" /><button type="button" className="button-secondary" onClick={() => { setDirty(true); setReference(undefined); setAssetId(''); if (referenceInput.current) referenceInput.current.value = ''; }}>移除参考图</button></div>}</div>
    <div className="form-field"><label htmlFor="set-template">共用创作模板（可选）</label><select id="set-template" value={templateId} onChange={e => { setTemplateId(e.target.value); setValues(productValues(product)); }}><option value="">不套用模板</option>{templates.map(item => <option key={item.id} value={item.id}>{item.name} · 版本 {item.revision}</option>)}</select><small>所选模板会应用于每张图片，再追加各自要求。</small></div>
    {template?.variables.map(key => <TemplateVariableField key={key} name={key} value={values[key] || ''} product={product} idPrefix="set-var" onChange={value => setValues(previous => ({ ...previous, [key]: value }))} />)}
    <div className="form-field set-common"><label htmlFor="set-common">整套公共要求</label><textarea id="set-common" rows={3} maxLength={8000} value={common} onChange={e => setCommon(e.target.value)} /></div></div>
    <div className="section-heading"><h3>图片清单 · {shots.length} 张</h3><button type="button" className="button-secondary" disabled={shots.length >= 8} onClick={() => { setDirty(true); setShots(previous => [...previous, { id: crypto.randomUUID(), name: '', prompt: '', size: 'default' }]); }}>添加一张</button></div>
    <div className="shot-list">{shots.map((shot, index) => <article className="shot-card" key={shot.id}><div className="shot-card-heading"><strong>第 {index + 1} 张</strong><div><button type="button" disabled={index === 0} onClick={() => move(index, -1)}>上移</button><button type="button" disabled={index === shots.length - 1} onClick={() => move(index, 1)}>下移</button><button type="button" disabled={shots.length === 1} onClick={() => { setDirty(true); setShots(previous => previous.filter(item => item.id !== shot.id)); }}>移除</button></div></div><div className="form-field"><label htmlFor={`shot-name-${shot.id}`}>图片用途</label><input id={`shot-name-${shot.id}`} required maxLength={80} value={shot.name} onChange={e => changeShot(shot.id, { name: e.target.value })} placeholder="例如：结构细节" /></div><div className="form-field"><label htmlFor={`shot-prompt-${shot.id}`}>这张图片的要求</label><textarea id={`shot-prompt-${shot.id}`} required maxLength={4000} rows={3} value={shot.prompt} onChange={e => changeShot(shot.id, { prompt: e.target.value })} /></div><ImageSizePicker id={`shot-size-${shot.id}`} value={shot.size} onChange={value => changeShot(shot.id, { size: value })} /></article>)}</div></fieldset>
    {model && !canGenerate && <p className="feedback feedback-warning">请先在<a href="#/settings">个人模型配置</a>填写并保存 API Key。</p>}
    {loading && <p role="status">正在读取配置…</p>}{error && !review && <p className="feedback feedback-error" role="alert">{error}</p>}<div className="form-actions">{ambiguous && <button type="button" className="button-secondary" onClick={unlock}>核对后修改清单</button>}<button className="button-primary" aria-describedby="set-submit-help" disabled={loading || busy || !model?.model_name.trim() || !canGenerate}>{ambiguous ? '核对并重发' : `检查 ${shots.length} 张生成清单`}</button></div>{!loading && !model?.model_name.trim() && <p id="set-submit-help" className="feedback feedback-warning">请先选择已配置的图片模型，才能检查生成清单。<a href="#/settings">前往个人模型配置</a></p>}<p className="form-footnote">检查清单不会调用模型。确认生成后，每张图片独立调用服务商并消耗额度；生成结果和文字、尺寸标注需人工核对。</p></form>
    <dialog ref={dialog} className="product-dialog set-review" aria-labelledby="set-review-title" onCancel={e => { e.preventDefault(); if (!busy) setReview(false); }}><h2 id="set-review-title">确认生成清单</h2><p>{name} · {shots.length} 张 · {model?.name} / {model?.model_name}</p><p>产品：{product ? `${product.sku} · ${product.name}` : '临时制作'} · 参考图：{reference?.name || assets.find(item => item.id === assetId)?.name || '未提供'}</p><p className="case-prompt">公共要求：{common}</p>{template && <details><summary>共用模板 · {template.name} · 版本 {template.revision}</summary><p className="case-prompt">{template.prompt}</p><p className="case-prompt">{template.skill}</p><p>{Object.entries(values).map(([key, value]) => `${key}：${value}`).join('；')}</p></details>}<ol className="set-review-list">{shots.map(shot => <li key={shot.id}><strong>{shot.name} · {formatImageSize(shot.size)}</strong><p>{shot.prompt}</p></li>)}</ol>{error && <p className="feedback feedback-error" role="alert">{error}</p>}<p className="form-footnote">本次将提交 {shots.length} 张图片并消耗服务商额度。没有点击确认前不会生成。</p><div className="form-actions">{ambiguous ? <button type="button" className="button-secondary" disabled={busy} onClick={unlock}>核对后修改清单</button> : <button type="button" className="button-secondary" disabled={busy} onClick={() => setReview(false)}>返回修改</button>}<button type="button" className="button-primary" disabled={busy || !canGenerate} onClick={generate}>{busy ? '提交中…' : ambiguous ? '重发相同提交' : `确认生成 ${shots.length} 张`}</button></div></dialog>
  </section>;
}
