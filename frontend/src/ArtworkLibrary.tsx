import { apiFetch } from './apiFetch';
import { useEffect, useState, type FormEvent } from 'react';
import { creativeRequest, type CreativeTemplate } from './creativeApi';
import { type Product } from './productApi';
import ExportDownload from './ExportDownload';
import TaskResultsPanel from './TaskResultsPanel';
import { formatTaskTime, kindLabels, taskCounts, taskLabels as labels, taskPending, type ImageTaskPage, type ImageTaskDetail } from './imageTaskApi';
import { startTaskPolling } from './taskPolling';

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
  const [result, setResult] = useState<ImageTaskPage>(); const [loading, setLoading] = useState(true); const [error, setError] = useState(''); const [filterError, setFilterError] = useState('');
  const [expanded, setExpanded] = useState(''); const [linkedTask, setLinkedTask] = useState<ImageTaskDetail>();
  const [focusJob, setFocusJob] = useState(''); const [openError, setOpenError] = useState('');
  const [picked, setPicked] = useState<string[]>([]); const [pickError, setPickError] = useState('');
  const [pageVisible, setPageVisible] = useState(() => !document.hidden);
  useEffect(() => {
    const visibility = () => setPageVisible(!document.hidden);
    document.addEventListener('visibilitychange', visibility);
    return () => document.removeEventListener('visibilitychange', visibility);
  }, []);
  useEffect(() => {
    let active = true;
    const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
    const id = params.get('job'); const taskId = params.get('task');
    if (!id && !taskId) return;
    creativeRequest<ImageTaskDetail>(id ? `image-jobs/tasks/for-image/${encodeURIComponent(id)}` : `image-jobs/tasks/${encodeURIComponent(taskId!)}`).then(item => {
      if (active) { setLinkedTask(item); setExpanded(item.id); setFocusJob(id || ''); }
    }).catch(() => { if (active) setOpenError('无法打开这条生成任务，请在列表中重新选择。'); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    let active = true;
    Promise.all([creativeRequest<Product[]>('products'), creativeRequest<CreativeTemplate[]>('templates')]).then(([p, t]) => { if (active) { setProducts(p); setTemplates(t); } }).catch(() => { if (active) setFilterError('产品或模板选项读取失败，可使用关键词搜索，或刷新页面重试。'); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!pageVisible) { setLoading(false); return; }
    setLoading(true); setResult(undefined); setError('');
    const params = new URLSearchParams({ page: String(page), page_size: '8', status: appliedFilters.status, q: appliedFilters.query });
    if (appliedFilters.favoriteOnly) params.set('favorite', 'true');
    if (appliedFilters.notesOnly) params.set('has_notes', 'true');
    if (appliedFilters.productId) params.set('product_id', appliedFilters.productId);
    if (appliedFilters.templateId) params.set('template_id', appliedFilters.templateId);
    const poller = startTaskPolling<ImageTaskPage>({
      timeout: 12000, interval: 10000,
      load: async signal => {
        const response = await apiFetch(`/api/image-jobs/tasks?${params}`, { signal, cache: 'no-store' });
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '生成记录读取失败。');
        return data;
      },
      pending: data => data.items.some(taskPending),
      onData: data => { setResult(data); setError(''); const last = Math.max(1, Math.ceil(data.total / data.page_size)); if (page > last) setPage(last); },
      onError: err => setError(err instanceof Error && err.name !== 'AbortError' ? err.message : '读取超时，请点击“刷新记录”重试。'),
      onLoading: setLoading,
    });
    return () => poller.stop();
  }, [appliedFilters, page, attempt, pageVisible]);
  function reset() { const next = emptyFilters(); setFilters(next); setAppliedFilters(next); setPage(1); }
  function submitSearch(event: FormEvent) { event.preventDefault(); const next = { ...filters, query: filters.query.trim() }; setFilters(next); setAppliedFilters(next); setPage(1); }
  function changeFilter<K extends keyof RecordFilters>(key: K, value: RecordFilters[K]) { setFilters(previous => ({ ...previous, [key]: value })); }
  const filtersChanged = JSON.stringify(filters) !== JSON.stringify(appliedFilters);
  const hasCriteria = JSON.stringify(appliedFilters) !== JSON.stringify(emptyFilters());
  const appliedSummary = [labels[appliedFilters.status], appliedFilters.productId && (products.find(item => item.id === appliedFilters.productId)?.sku || '指定产品'), appliedFilters.templateId && (templates.find(item => item.id === appliedFilters.templateId)?.name || '指定模板'), appliedFilters.query && `关键词“${appliedFilters.query}”`, appliedFilters.favoriteOnly && '仅收藏', appliedFilters.notesOnly && '有经验备注'].filter(Boolean).join(' · ');
  const pages = Math.max(1, Math.ceil((result?.total || 0) / 8));
  function togglePick(ids: string[]) {
    setPickError('');
    if (ids.every(id => picked.includes(id))) setPicked(previous => previous.filter(id => !ids.includes(id)));
    else { const next = [...new Set([...picked, ...ids])]; if (next.length > 50) setPickError('每次最多选择 50 张，请先导出当前选择。'); else setPicked(next); }
  }
  function pickPage() {
    const next = [...new Set([...picked, ...(result?.items.flatMap(item => item.completed_job_ids) || [])])];
    if (next.length > 50) { setPickError('添加本页后将超过 50 张，请先导出当前选择。'); return; }
    setPicked(next); setPickError('');
  }
  return <section>
    <div className="section-heading"><div><p className="eyebrow">GENERATION HISTORY</p><h2>生成记录</h2></div><a className="button-primary" href="#/studio">开始图片创作</a></div>
    <p className="settings-intro">一次提交保存为一条任务，包含本次所有图片的运行结果和日志。展开任务可查看图片、定位错误或继续修改。</p>
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
    <div className="record-results-heading"><div><h3 id="record-results-title">记录列表 <span role="status">{loading ? '读取中…' : result ? `共 ${result.total} 个任务` : '暂未读取'}</span></h3><p className="record-applied">当前筛选：{appliedSummary}</p></div><button type="button" className="button-secondary" disabled={loading} onClick={() => setAttempt(value => value + 1)}>刷新记录</button></div>
    {error && <p className="feedback feedback-error" role="alert">{error} <button className="button-secondary" type="button" onClick={() => setAttempt(value => value + 1)}>重试</button></p>}
    {(picked.length > 0 || !!result?.items.some(item => item.completed_job_ids.length > 0)) && <div className="record-selection-bar"><span>{picked.length ? `已选择 ${picked.length} 张图片，可跨页选择` : '勾选生成图片后，可批量下载'}</span><div className="library-pick-actions"><button type="button" className="button-secondary" disabled={loading || !result?.items.some(item => item.completed_job_ids.length > 0)} onClick={pickPage}>选择本页图片</button>{picked.length > 0 && <button type="button" className="button-secondary" onClick={() => { setPicked([]); setPickError(''); }}>清空选择</button>}</div></div>}
    {picked.length > 0 && <section className="library-export" aria-label="批量下载"><ExportDownload jobIds={picked} count={picked.length} /></section>}
    {pickError && <p className="feedback feedback-warning" role="alert">{pickError}</p>}
    <div className="task-history-list" aria-busy={loading}>
      {[...(linkedTask && !result?.items.some(item => item.id === linkedTask.id) ? [linkedTask] : []), ...(result?.items || [])].map(item => <article className="task-history-card" key={item.id}>
        <div className="task-history-heading"><button type="button" className="task-history-toggle" aria-expanded={expanded === item.id} aria-controls={`task-content-${item.id}`} onClick={() => { setExpanded(previous => previous === item.id ? '' : item.id); setFocusJob(''); }}>
          <div className="task-history-title"><span className="task-kind">{kindLabels[item.kind]}</span><strong>{item.title}</strong><span className={`job-status job-${item.status}`}>{labels[item.status]}</span></div>
          <div className="task-history-meta"><time dateTime={item.created_at}>{formatTaskTime(item.created_at)}</time><span>{item.counts.total} 张 · {taskCounts(item)}</span><span>{item.model_name}</span></div>
          <span className="task-expand-label">{expanded === item.id ? '收起结果与日志 ▴' : '展开结果与日志 ▾'}</span>
        </button>{item.completed_job_ids.length > 0 && <label className="task-pick"><input type="checkbox" checked={item.completed_job_ids.every(id => picked.includes(id))} onChange={() => togglePick(item.completed_job_ids)} />选择本任务图片</label>}</div>
        {expanded === item.id && <div className="task-history-content" id={`task-content-${item.id}`}><TaskResultsPanel taskId={item.id} focusJobId={focusJob} /></div>}
      </article>)}
    </div>
    {!loading && !error && !result?.items.length && <div className="artwork-empty"><h3>{hasCriteria ? '没有符合条件的生成记录' : '还没有生成记录'}</h3><p>{hasCriteria ? '可以调整筛选条件后查询，或点击“重置”查看全部记录。' : '提交图片创作后，这里会自动保存任务进度、生成结果和修改版本。'}</p>{hasCriteria ? <button type="button" className="button-secondary" onClick={reset}>重置筛选</button> : <a className="button-primary" href="#/studio">开始图片创作</a>}</div>}
    {!!result?.total && <nav className="artwork-pagination" aria-label="生成记录分页"><button className="button-secondary" disabled={loading || page <= 1} onClick={() => setPage(value => value - 1)}>上一页</button><span>第 {page} / {pages} 页</span><button className="button-secondary" disabled={loading || page >= pages} onClick={() => setPage(value => value + 1)}>下一页</button></nav>}
    </section>

  </section>;
}
