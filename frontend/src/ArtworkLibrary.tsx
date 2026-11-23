import { formatImageSize } from './ImageSizePicker';
import TaskCancel from './TaskCancel';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { creativeRequest, type CreativeTemplate, type TemplateSnapshot } from './creativeApi';
import { type Product, type ProductSnapshot } from './productApi';
import ExperienceEditor from './ExperienceEditor';
import RevisionTrail from './RevisionTrail';
import ExportDownload from './ExportDownload';

interface Artwork {
  id: string; status: string; message: string; config_name: string; model_name: string; prompt: string;
  size: string; mode: string; created_at: string; image_url: string | null; reference_url: string | null;
  product_snapshot: ProductSnapshot; template_snapshot: TemplateSnapshot; case_id: string | null;
  parent_job_id: string | null; edit_instruction: string;
  set_id: string | null; set_name: string; shot_name: string;
  is_favorite: boolean;
}
interface ArtworkPage { items: Artwork[]; total: number; page: number; page_size: number }
const labels: Record<string, string> = { all: '全部状态', succeeded: '已完成', queued: '排队中', running: '生成中', failed: '未完成', unknown: '结果待确认', cancelled: '已取消' };

export default function ArtworkLibrary() {
  const [products, setProducts] = useState<Product[]>([]); const [templates, setTemplates] = useState<CreativeTemplate[]>([]);
  const [productId, setProductId] = useState(''); const [templateId, setTemplateId] = useState(''); const [status, setStatus] = useState(() => { const value = new URLSearchParams(window.location.hash.split('?')[1] || '').get('status') || 'succeeded'; return Object.hasOwn(labels, value) ? value : 'succeeded'; });
  const [search, setSearch] = useState(''); const [query, setQuery] = useState(''); const [page, setPage] = useState(1); const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<ArtworkPage>(); const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [filterError, setFilterError] = useState('');
  const [selected, setSelected] = useState<Artwork>(); const [caseDirty, setCaseDirty] = useState(false); const [caseBusy, setCaseBusy] = useState(false);
  const [favoriteOnly, setFavoriteOnly] = useState(() => new URLSearchParams(window.location.hash.split('?')[1] || '').get('favorite') === '1');
  const [notesOnly, setNotesOnly] = useState(() => window.location.hash.split('?')[0] === '#/cases' || new URLSearchParams(window.location.hash.split('?')[1] || '').get('notes') === '1');
  const [favoriteBusy, setFavoriteBusy] = useState(false); const [favoriteError, setFavoriteError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [openError, setOpenError] = useState('');
  const [picked, setPicked] = useState<string[]>([]); const [pickError, setPickError] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    let active = true;
    const id = new URLSearchParams(window.location.hash.split('?')[1] || '').get('job');
    if (!id) return;
    creativeRequest<Artwork>(`image-jobs/${encodeURIComponent(id)}`).then(item => { if (active) setSelected(item); }).catch(() => { if (active) setOpenError('无法打开这条作品记录，请重新在作品库中选择。'); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    Promise.all([creativeRequest<Product[]>('products'), creativeRequest<CreativeTemplate[]>('templates')]).then(([p, t]) => { if (active) { setProducts(p); setTemplates(t); } }).catch(() => { if (active) setFilterError('产品或模板选项读取失败，可使用关键词搜索，或刷新页面重试。'); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true; let timer: number; let controller: AbortController;
    setLoading(true); setResult(undefined); setError('');
    async function load() {
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 12000);
      const params = new URLSearchParams({ page: String(page), page_size: '12', status, q: query });
      if (favoriteOnly) params.set('favorite', 'true');
      if (notesOnly) params.set('has_notes', 'true');
      if (productId) params.set('product_id', productId);
      if (templateId) params.set('template_id', templateId);
      try {
        const response = await fetch(`/api/image-jobs/library?${params}`, { signal: controller.signal, cache: 'no-store' });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '作品读取失败。');
        if (active) {
          setResult(data); setError('');
          const last = Math.max(1, Math.ceil(data.total / data.page_size));
          if (page > last) setPage(last);
        }
      } catch (err) { if (active) setError(err instanceof Error && err.name !== 'AbortError' ? err.message : '读取超时，请检查后端并重试。'); }
      finally { window.clearTimeout(timeout); if (active) { setLoading(false); timer = window.setTimeout(load, 10000); } }
    }
    void load();
    return () => { active = false; window.clearTimeout(timer); controller?.abort(); };
  }, [productId, templateId, status, query, page, attempt, favoriteOnly, notesOnly]);
  useEffect(() => { if (selected) dialog.current?.showModal(); else dialog.current?.close(); }, [selected?.id]);
  useEffect(() => {
    if (!selected || !['queued', 'running'].includes(selected.status)) return;
    const id = selected.id;
    let active = true; let timer: number;
    async function update() {
      try {
        const item = await creativeRequest<Artwork>(`image-jobs/${id}`);
        if (active) { setDetailError(''); setSelected(previous => previous?.id === id ? { ...previous, ...item, case_id: previous.case_id } : previous); }
      } catch { if (active) setDetailError('详情状态暂未更新，正在重试。'); }
      finally { if (active) timer = window.setTimeout(update, 3000); }
    }
    void update();
    return () => { active = false; window.clearTimeout(timer); };
  }, [selected?.id, selected?.status]);
  function reset() { setProductId(''); setTemplateId(''); setStatus('succeeded'); setSearch(''); setQuery(''); setPage(1); setFavoriteOnly(false); setNotesOnly(false); }
  function open(item: Artwork) { setSelected(item); setCaseDirty(false); setCaseBusy(false); setDetailError(''); setFavoriteError(''); }
  function close() { if (caseBusy || favoriteBusy || (caseDirty && !window.confirm('经验备注尚未保存，确定关闭吗？'))) return false; setSelected(undefined); setCaseDirty(false); return true; }
  async function toggleFavorite() {
    if (!selected || favoriteBusy) return;
    const id = selected.id;
    const form = new FormData(); form.set('favorite', String(!selected.is_favorite));
    setFavoriteBusy(true); setFavoriteError('');
    try {
      const response = await fetch(`/api/image-jobs/${id}/favorite`, { method: 'POST', body: form, signal: AbortSignal.timeout(12000) });
      const item = await response.json();
      if (!response.ok) throw new Error(typeof item.detail === 'string' ? item.detail : '收藏操作未完成，请重试。');
      setSelected(previous => previous?.id === id ? { ...previous, is_favorite: item.is_favorite } : previous);
      setAttempt(value => value + 1);
    } catch (err) { setFavoriteError(err instanceof Error ? err.message : '收藏操作未完成，请重试。'); }
    finally { setFavoriteBusy(false); }
  }
  function submitSearch(event: FormEvent) { event.preventDefault(); setQuery(search.trim()); setPage(1); }
  const pages = Math.max(1, Math.ceil((result?.total || 0) / 12));
  function togglePick(id: string) {
    setPickError('');
    if (picked.includes(id)) setPicked(previous => previous.filter(item => item !== id));
    else if (picked.length >= 50) setPickError('每次最多选择 50 张，请先导出当前选择。');
    else setPicked(previous => [...previous, id]);
  }
  function pickPage() {
    const next = [...new Set([...picked, ...(result?.items.filter(item => item.status === 'succeeded').map(item => item.id) || [])])];
    if (next.length > 50) { setPickError('添加本页后将超过 50 张，请先导出当前选择。'); return; }
    setPicked(next); setPickError('');
  }
  return <section>
    <div className="section-heading"><div><p className="eyebrow">YOUR CREATIVE OUTPUT</p><h2>作品库</h2></div><a className="button-primary" href="#/studio">开始图片创作</a></div>
    <p className="settings-intro">这里保存生成结果和修改记录。点击图片可下载、继续修改、收藏或记录经验；产品实拍在“产品资料”维护，制作方法在“创作模板”维护。</p>
    <div className="artwork-organization" aria-label="作品整理筛选"><label><input type="checkbox" checked={favoriteOnly} onChange={e => { setFavoriteOnly(e.target.checked); setPage(1); }} />仅收藏</label><label><input type="checkbox" checked={notesOnly} onChange={e => { setNotesOnly(e.target.checked); setPage(1); }} />有经验备注</label><span>收藏图片和记录经验可以分别进行。</span></div>
    {openError && <p className="feedback feedback-error" role="alert">{openError}</p>}
    <div className="artwork-filters"><form className="artwork-search" onSubmit={submitSearch}><div className="form-field"><label htmlFor="artwork-search">搜索作品</label><input id="artwork-search" maxLength={200} value={search} onChange={e => setSearch(e.target.value)} placeholder="SKU、产品、画面要求或经验内容" /></div><button className="button-secondary">搜索</button></form>
    <div className="form-field"><label htmlFor="artwork-product">产品</label><select id="artwork-product" value={productId} onChange={e => { setProductId(e.target.value); setPage(1); }}><option value="">全部产品</option>{products.map(item => <option key={item.id} value={item.id}>{item.sku} · {item.name}</option>)}</select></div>
    <div className="form-field"><label htmlFor="artwork-template">模板</label><select id="artwork-template" value={templateId} onChange={e => { setTemplateId(e.target.value); setPage(1); }}><option value="">全部模板</option>{templates.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
    <div className="form-field"><label htmlFor="artwork-status">状态</label><select id="artwork-status" value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div></div>
    <div className="artwork-summary"><span role="status">{loading ? '正在读取作品…' : `共 ${result?.total || 0} 项${query ? ` · 搜索“${query}”` : ''}`}</span><div><button type="button" className="button-secondary" onClick={reset}>重置筛选</button><button type="button" className="button-secondary" disabled={loading} onClick={() => setAttempt(value => value + 1)}>刷新</button></div></div>
    {filterError && <p className="feedback feedback-warning">{filterError}</p>}{error && <p className="feedback feedback-error" role="alert">{error} <button className="button-secondary" type="button" onClick={() => setAttempt(value => value + 1)}>重试</button></p>}
    <section className="library-export" aria-label="批量导出"><div className="library-pick-actions"><strong>批量导出 · 已选 {picked.length} 张</strong><button type="button" className="button-secondary" disabled={loading || !result?.items.some(item => item.status === 'succeeded')} onClick={pickPage}>选择本页已完成</button><button type="button" className="button-secondary" disabled={!picked.length} onClick={() => { setPicked([]); setPickError(''); }}>清空选择</button></div><ExportDownload jobIds={picked} count={picked.length} />{pickError && <p className="feedback feedback-warning" role="alert">{pickError}</p>}</section>
    <div className="artwork-grid" aria-busy={loading}>{result?.items.map(item => <article className="artwork-selectable" key={item.id}><label className="artwork-selection-label"><input type="checkbox" checked={picked.includes(item.id)} disabled={item.status !== "succeeded"} onChange={() => togglePick(item.id)} aria-label={`选择作品：${item.shot_name || item.product_snapshot.sku || item.id}`} />{item.status === "succeeded" ? "选择" : "仅已完成可选"}</label><button key={item.id} type="button" className="artwork-card" onClick={() => open(item)} aria-label={`查看作品：${item.product_snapshot.name || item.template_snapshot.name || '自由创作'}，${labels[item.status]}`}>
      {item.image_url ? <img src={item.image_url} alt={item.product_snapshot.name || '生成作品'} loading="lazy" /> : <div className="artwork-placeholder"><span className={`job-status job-${item.status}`}>{labels[item.status]}</span><p>{item.message}</p></div>}
      <div className="artwork-card-body"><div className="artwork-card-title"><strong>{item.product_snapshot.sku || item.template_snapshot.name || '自由创作'}</strong>{item.is_favorite && <span className="case-badge">已收藏</span>}{item.case_id && <span className="case-badge">有经验</span>}</div><p>{item.prompt}</p><small>{item.model_name} · {new Date(item.created_at).toLocaleString('zh-CN')}</small><span className="artwork-open">查看详情</span></div></button></article>)}</div>
    {!loading && !error && !result?.items.length && <div className="artwork-empty"><h3>当前没有符合条件的作品</h3><p>{favoriteOnly || notesOnly ? '可取消整理筛选查看其他作品。在作品详情中可以收藏图片、填写经验备注。' : '先完成一次图片创作，图片就会自动出现在这里。查看排队或失败的任务，请将状态切换为“全部状态”。'}</p><a className="button-primary" href="#/studio">去创作图片</a></div>}
    {!!result?.total && <nav className="artwork-pagination" aria-label="作品分页"><button className="button-secondary" disabled={loading || page <= 1} onClick={() => setPage(value => value - 1)}>上一页</button><span>第 {page} / {pages} 页</span><button className="button-secondary" disabled={loading || page >= pages} onClick={() => setPage(value => value + 1)}>下一页</button></nav>}
    <dialog ref={dialog} className="artwork-dialog" aria-labelledby="artwork-detail-title" onCancel={e => { e.preventDefault(); close(); }}>
      {selected && <><div className="product-dialog-heading"><h2 id="artwork-detail-title">作品详情</h2><button className="button-secondary" disabled={caseBusy || favoriteBusy} onClick={close}>关闭</button></div><div className="artwork-detail-layout"><div>
        {selected.image_url ? selected.parent_job_id && selected.reference_url ? <div className="revision-comparison"><figure><figcaption>修改前</figcaption><a href={selected.reference_url} target="_blank" rel="noreferrer"><img src={selected.reference_url} alt="修改前的来源图片" /></a></figure><figure><figcaption>修改后</figcaption><a href={selected.image_url} target="_blank" rel="noreferrer"><img src={selected.image_url} alt="修改后的新版本" /></a></figure></div> : <a href={selected.image_url} target="_blank" rel="noreferrer"><img className="artwork-detail-image" src={selected.image_url} alt="生成作品大图" /></a> : <div className="result-placeholder"><strong>{labels[selected.status]}</strong><p>{selected.message}</p></div>}
        <div className="result-actions">{selected.image_url && <a className="button-primary" href={`${selected.image_url}?download=true`}>下载 PNG</a>}{selected.reference_url && <a className="button-secondary" href={selected.reference_url} target="_blank" rel="noreferrer">查看参考图</a>}</div>
        <TaskCancel key={selected.id} jobId={selected.id} status={selected.status} onChanged={reply => { if (reply.status === "cancelled") setSelected(previous => previous ? { ...previous, status: "cancelled", message: reply.message || "已取消排队。" } : previous); setAttempt(value => value + 1); }} />{detailError && <p className="feedback feedback-warning">{detailError}</p>}
        {selected.image_url && <p><a className="button-primary" href={`#/edit?source=${selected.id}`} onClick={e => { if (!close()) e.preventDefault(); }}>继续修改这张图</a></p>}
        {selected.status === 'unknown' && <p className="feedback feedback-warning">请先核对服务商的生成与计费记录。本任务不会自动重试。</p>}
        {selected.status === 'succeeded' && <><button type="button" className="button-secondary" aria-pressed={selected.is_favorite} disabled={favoriteBusy} onClick={toggleFavorite}>{favoriteBusy ? '保存中…' : selected.is_favorite ? '取消收藏' : '收藏这张图'}</button>{favoriteError && <p className="feedback feedback-error" role="alert">{favoriteError}</p>}<ExperienceEditor key={selected.id} jobId={selected.id} onDirtyChange={setCaseDirty} onSavingChange={setCaseBusy} onSaved={note => { setSelected(previous => previous ? { ...previous, case_id: note.id } : previous); setAttempt(value => value + 1); }} /></>}
      </div><div className="artwork-record"><span className={`job-status job-${selected.status}`}>{labels[selected.status]}</span><dl className="job-details"><div><dt>模型</dt><dd>{selected.config_name} · {selected.model_name}</dd></div><div><dt>创建时间</dt><dd>{new Date(selected.created_at).toLocaleString('zh-CN')}</dd></div><div><dt>制作方式</dt><dd>{selected.mode === 'edit' ? '参考图编辑' : '文字生图'}</dd></div><div><dt>请求尺寸</dt><dd>{formatImageSize(selected.size)}</dd></div></dl>
        <details open><summary>完整制作要求</summary><p className="case-prompt">{selected.prompt}</p></details>
        {selected.product_snapshot.id && <details><summary>当时的产品资料 · {selected.product_snapshot.sku}</summary><p>{selected.product_snapshot.name} · 版本 {selected.product_snapshot.revision}</p><p>{selected.product_snapshot.color} · {selected.product_snapshot.dimensions}</p><p>{selected.product_snapshot.facts}</p><p>{selected.product_snapshot.notes}</p></details>}
        {selected.template_snapshot.id && <details><summary>当时的模板 · {selected.template_snapshot.name}</summary><p>版本 {selected.template_snapshot.revision}</p><p>{Object.entries(selected.template_snapshot.values || {}).map(([key, value]) => `${key}：${value}`).join('；')}</p><p>{selected.template_snapshot.prompt}</p><p>{selected.template_snapshot.skill_name && `Skill：${selected.template_snapshot.skill_name} · 版本 ${selected.template_snapshot.skill_revision}`}</p>{selected.template_snapshot.skill && <p>Skill：{selected.template_snapshot.skill}</p>}<p>{selected.template_snapshot.notes}</p></details>}
        {selected.edit_instruction && <p>本次修改：{selected.edit_instruction}</p>}
        {selected.set_id && <p>套图：{selected.set_name} · {selected.shot_name} <a className="button-secondary" href={`#/sets?set=${selected.set_id}`} onClick={e => { if (!close()) e.preventDefault(); }}>查看整套图片</a></p>}
        <RevisionTrail jobId={selected.id} onNavigate={e => { if (!close()) e.preventDefault(); }} />
      </div></div></>}
    </dialog>
  </section>;
}
