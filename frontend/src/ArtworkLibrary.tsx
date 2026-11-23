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
interface RecordFilters { productId: string; templateId: string; status: string; query: string; favoriteOnly: boolean; notesOnly: boolean }
const emptyFilters = (): RecordFilters => ({ productId: '', templateId: '', status: 'all', query: '', favoriteOnly: false, notesOnly: false });
function initialFilters(): RecordFilters {
  const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
  const status = params.get('status') || 'all';
  return { ...emptyFilters(), status: Object.hasOwn(labels, status) ? status : 'all', favoriteOnly: params.get('favorite') === '1', notesOnly: window.location.hash.split('?')[0] === '#/cases' || params.get('notes') === '1' };
}

export default function ArtworkLibrary() {
  const [products, setProducts] = useState<Product[]>([]); const [templates, setTemplates] = useState<CreativeTemplate[]>([]);
  const [filters, setFilters] = useState<RecordFilters>(initialFilters);
  const [appliedFilters, setAppliedFilters] = useState<RecordFilters>(initialFilters);
  const [page, setPage] = useState(1); const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<ArtworkPage>(); const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [filterError, setFilterError] = useState('');
  const [selected, setSelected] = useState<Artwork>(); const [caseDirty, setCaseDirty] = useState(false); const [caseBusy, setCaseBusy] = useState(false);
  const [favoriteBusy, setFavoriteBusy] = useState(false); const [favoriteError, setFavoriteError] = useState('');
  const [detailError, setDetailError] = useState('');
  const [openError, setOpenError] = useState('');
  const [picked, setPicked] = useState<string[]>([]); const [pickError, setPickError] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    let active = true;
    const id = new URLSearchParams(window.location.hash.split('?')[1] || '').get('job');
    if (!id) return;
    creativeRequest<Artwork>(`image-jobs/${encodeURIComponent(id)}`).then(item => { if (active) setSelected(item); }).catch(() => { if (active) setOpenError('无法打开这条生成记录，请重新在生成记录中选择。'); });
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
      const params = new URLSearchParams({ page: String(page), page_size: '12', status: appliedFilters.status, q: appliedFilters.query });
      if (appliedFilters.favoriteOnly) params.set('favorite', 'true');
      if (appliedFilters.notesOnly) params.set('has_notes', 'true');
      if (appliedFilters.productId) params.set('product_id', appliedFilters.productId);
      if (appliedFilters.templateId) params.set('template_id', appliedFilters.templateId);
      try {
        const response = await fetch(`/api/image-jobs/library?${params}`, { signal: controller.signal, cache: 'no-store' });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '生成记录读取失败。');
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
  }, [appliedFilters, page, attempt]);
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
  function reset() { const next = emptyFilters(); setFilters(next); setAppliedFilters(next); setPage(1); }
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
  function submitSearch(event: FormEvent) { event.preventDefault(); const next = { ...filters, query: filters.query.trim() }; setFilters(next); setAppliedFilters(next); setPage(1); }
  function changeFilter<K extends keyof RecordFilters>(key: K, value: RecordFilters[K]) { setFilters(previous => ({ ...previous, [key]: value })); }
  const filtersChanged = JSON.stringify(filters) !== JSON.stringify(appliedFilters);
  const hasCriteria = JSON.stringify(appliedFilters) !== JSON.stringify(emptyFilters());
  const appliedSummary = [labels[appliedFilters.status], appliedFilters.productId && (products.find(item => item.id === appliedFilters.productId)?.sku || '指定产品'), appliedFilters.templateId && (templates.find(item => item.id === appliedFilters.templateId)?.name || '指定模板'), appliedFilters.query && `关键词“${appliedFilters.query}”`, appliedFilters.favoriteOnly && '仅收藏', appliedFilters.notesOnly && '有经验备注'].filter(Boolean).join(' · ');
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
    <div className="section-heading"><div><p className="eyebrow">GENERATION HISTORY</p><h2>生成记录</h2></div><a className="button-primary" href="#/studio">开始图片创作</a></div>
    <p className="settings-intro">每次图片生成和修改都会自动记录在这里，包括任务进度、生成图片和当时的制作要求。打开记录可查看详情、下载图片或继续修改。</p>
    {openError && <p className="feedback feedback-error" role="alert">{openError}</p>}
    <form className="record-filter-panel" aria-labelledby="record-filter-title" onSubmit={submitSearch}>
      <div className="record-filter-heading"><h3 id="record-filter-title">筛选记录</h3><p>设置条件后点击“查询”，结果显示在下方。</p></div>
      <div className="artwork-filters">
        <div className="form-field"><label htmlFor="artwork-search">关键词</label><input id="artwork-search" maxLength={200} value={filters.query} onChange={e => changeFilter('query', e.target.value)} placeholder="SKU、产品、模型、画面要求或经验" /></div>
        <div className="form-field"><label htmlFor="artwork-product">产品</label><select id="artwork-product" value={filters.productId} onChange={e => changeFilter('productId', e.target.value)}><option value="">全部产品</option>{products.map(item => <option key={item.id} value={item.id}>{item.sku} · {item.name}</option>)}</select></div>
        <div className="form-field"><label htmlFor="artwork-template">创作模板</label><select id="artwork-template" value={filters.templateId} onChange={e => changeFilter('templateId', e.target.value)}><option value="">全部模板</option>{templates.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
        <div className="form-field"><label htmlFor="artwork-status">任务状态</label><select id="artwork-status" value={filters.status} onChange={e => changeFilter('status', e.target.value)}>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
      </div>
      <div className="record-filter-footer"><div className="artwork-organization"><label><input type="checkbox" checked={filters.favoriteOnly} onChange={e => changeFilter('favoriteOnly', e.target.checked)} />仅收藏</label><label><input type="checkbox" checked={filters.notesOnly} onChange={e => changeFilter('notesOnly', e.target.checked)} />有经验备注</label></div><div className="record-query-actions"><button type="button" className="button-secondary" onClick={reset}>重置</button><button type="submit" className="button-primary" disabled={loading}>查询</button></div></div>
      {filtersChanged && <p className="filter-pending" role="status">筛选条件已修改，点击“查询”后生效。</p>}
      {filterError && <p className="feedback feedback-warning">{filterError}</p>}
    </form>
    <section className="record-results" aria-labelledby="record-results-title">
    <div className="record-results-heading"><div><h3 id="record-results-title">记录列表 <span role="status">{loading ? '读取中…' : result ? `共 ${result.total} 条` : '暂未读取'}</span></h3><p className="record-applied">当前筛选：{appliedSummary}</p></div><button type="button" className="button-secondary" disabled={loading} onClick={() => setAttempt(value => value + 1)}>刷新记录</button></div>
    {error && <p className="feedback feedback-error" role="alert">{error} <button className="button-secondary" type="button" onClick={() => setAttempt(value => value + 1)}>重试</button></p>}
    {(picked.length > 0 || !!result?.items.some(item => item.status === 'succeeded')) && <div className="record-selection-bar"><span>{picked.length ? `已选择 ${picked.length} 张图片，可跨页选择` : '勾选生成图片后，可批量下载'}</span><div className="library-pick-actions"><button type="button" className="button-secondary" disabled={loading || !result?.items.some(item => item.status === 'succeeded')} onClick={pickPage}>选择本页图片</button>{picked.length > 0 && <button type="button" className="button-secondary" onClick={() => { setPicked([]); setPickError(''); }}>清空选择</button>}</div></div>}
    {picked.length > 0 && <section className="library-export" aria-label="批量下载"><ExportDownload jobIds={picked} count={picked.length} /></section>}
    {pickError && <p className="feedback feedback-warning" role="alert">{pickError}</p>}
    <div className="artwork-grid" aria-busy={loading}>{result?.items.map(item => <article className="artwork-selectable" key={item.id}>{item.status === "succeeded" && <label className="artwork-selection-label"><input type="checkbox" checked={picked.includes(item.id)} onChange={() => togglePick(item.id)} aria-label={`选择图片：${item.shot_name || item.product_snapshot.sku || item.id}`} />勾选下载</label>}<button key={item.id} type="button" className="artwork-card" onClick={() => open(item)} aria-label={`查看生成记录：${item.product_snapshot.name || item.template_snapshot.name || '自由创作'}，${labels[item.status]}`}>
      {item.image_url ? <img src={item.image_url} alt={item.product_snapshot.name || '生成作品'} loading="lazy" /> : <div className="artwork-placeholder"><span className={`job-status job-${item.status}`}>{labels[item.status]}</span><p>{item.message}</p></div>}
      <div className="artwork-card-body"><div className="artwork-card-title"><strong>{item.shot_name || item.product_snapshot.sku || item.template_snapshot.name || '自由创作'}</strong>{item.is_favorite && <span className="case-badge">已收藏</span>}{item.case_id && <span className="case-badge">有经验</span>}</div>{item.image_url && <span className={`job-status job-${item.status}`}>{labels[item.status]}</span>}<p>{item.prompt}</p><small>{item.model_name} · {new Date(item.created_at).toLocaleString('zh-CN')}</small><span className="artwork-open">查看记录与图片</span></div></button></article>)}</div>
    {!loading && !error && !result?.items.length && <div className="artwork-empty"><h3>{hasCriteria ? '没有符合条件的生成记录' : '还没有生成记录'}</h3><p>{hasCriteria ? '可以调整筛选条件后查询，或点击“重置”查看全部记录。' : '提交图片创作后，这里会自动保存任务进度、生成结果和修改版本。'}</p>{hasCriteria ? <button type="button" className="button-secondary" onClick={reset}>重置筛选</button> : <a className="button-primary" href="#/studio">开始图片创作</a>}</div>}
    {!!result?.total && <nav className="artwork-pagination" aria-label="生成记录分页"><button className="button-secondary" disabled={loading || page <= 1} onClick={() => setPage(value => value - 1)}>上一页</button><span>第 {page} / {pages} 页</span><button className="button-secondary" disabled={loading || page >= pages} onClick={() => setPage(value => value + 1)}>下一页</button></nav>}
    </section>
    <dialog ref={dialog} className="artwork-dialog" aria-labelledby="artwork-detail-title" onCancel={e => { e.preventDefault(); close(); }}>
      {selected && <><div className="product-dialog-heading"><h2 id="artwork-detail-title">生成记录详情</h2><button className="button-secondary" disabled={caseBusy || favoriteBusy} onClick={close}>关闭</button></div><div className="artwork-detail-layout"><div>
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
