import { useEffect, useRef, useState, type FormEvent } from 'react';
import { creativeRequest } from './creativeApi';
import { uploadAsset, type Product, type ProductAsset } from './productApi';

const blank = () => ({ sku: '', name: '', category: '凉棚', dimensions: '', color: '', facts: '', notes: '', revision: 0 });
export default function ProductLibrary() {
  const [products, setProducts] = useState<Product[]>([]);
  const [id, setId] = useState(''); const [draft, setDraft] = useState(blank);
  const [assets, setAssets] = useState<ProductAsset[]>([]); const [search, setSearch] = useState('');
  const [kind, setKind] = useState('产品实拍'); const [busy, setBusy] = useState(false); const [dirty, setDirty] = useState(false);
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [assetsLoading, setAssetsLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const dialog = useRef<HTMLDialogElement>(null);
  const skuInput = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; creativeRequest<Product[]>('products').then(value => { if (mounted.current) setProducts(value); }).catch(err => { if (mounted.current) setError(err.message); }).finally(() => { if (mounted.current) setLoading(false); }); return () => { mounted.current = false; }; }, []);
  useEffect(() => { if (creating) { dialog.current?.showModal(); skuInput.current?.focus(); } else { dialog.current?.close(); } }, [creating]);
  useEffect(() => { let active = true; setAssets([]); if (!id) return; setAssetsLoading(true); creativeRequest<ProductAsset[]>(`products/${id}/assets`).then(value => { if (active) setAssets(value); }).catch(err => { if (active) setError(err.message); }).finally(() => { if (active) setAssetsLoading(false); }); return () => { active = false; }; }, [id]);
  useEffect(() => {
    const unload = (e: BeforeUnloadEvent) => { if (dirty || busy) e.preventDefault(); };
    const leave = (e: MouseEvent) => { const link = e.target instanceof Element ? e.target.closest('a') : null; if ((dirty || busy) && link?.getAttribute('href')?.startsWith('#/') && !window.confirm('内容尚未保存或正在上传，确定离开吗？')) e.preventDefault(); };
    window.addEventListener('beforeunload', unload); document.addEventListener('click', leave, true);
    return () => { window.removeEventListener('beforeunload', unload); document.removeEventListener('click', leave, true); };
  }, [dirty, busy]);
  function select(product?: Product) {
    if (dirty && !window.confirm('当前修改尚未保存，是否放弃修改？')) return;
    setId(product?.id || ''); setDraft(product ? { ...product } : blank()); setDirty(false); setError(''); setNotice('');
    setCreating(!product);
  }
  function cancelCreate() {
    if (busy || (dirty && !window.confirm('放弃本次尚未保存的产品信息？'))) return;
    setCreating(false); setDirty(false); setDraft(blank()); setError('');
  }
  function change(key: keyof ReturnType<typeof blank>, value: string) { setDraft(previous => ({ ...previous, [key]: value })); setDirty(true); setNotice(''); }
  async function save(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('');
    const {sku, name, category, dimensions, color, facts, notes, revision} = draft;
    try {
      const product = await creativeRequest<Product>(id ? `products/${id}` : 'products', {sku, name, category, dimensions, color, facts, notes, revision}, id ? 'PUT' : 'POST');
      if (!mounted.current) return;
      setProducts(previous => [product, ...previous.filter(item => item.id !== product.id)]); setId(product.id); setDraft(product); setCreating(false); setDirty(false); setNotice('产品资料已保存。下一步：在下方添加实拍图，或点击“用此产品创作”。');
    } catch (err) { if (mounted.current) setError(err instanceof Error ? err.message : '保存失败'); } finally { if (mounted.current) setBusy(false); }
  }
  async function upload(files: File[]) {
    if (!files.length || !id) return;
    if (files.length > 8 || files.some(file => file.size > 20 * 1024 * 1024)) { setError('每次最多上传 8 张，每张不超过 20 MB。'); return; }
    setBusy(true); setError(''); setNotice(''); let completed = 0;
    try {
      for (const file of files) {
        const asset = await uploadAsset(id, file, kind); completed += 1;
        if (!mounted.current) return;
        setAssets(previous => [asset, ...previous.filter(item => item.id !== asset.id)]);
      }
      setNotice(`已上传 ${completed} 张素材。`);
    } catch (err) { if (mounted.current) setError(`已完成 ${completed} 张。${err instanceof Error ? err.message : '上传失败'} 请刷新查看素材列表后再补传。`); }
    finally { if (mounted.current) setBusy(false); }
  }
  const productForm = <form onSubmit={save}><fieldset disabled={busy} className="product-fields"><div className="template-defaults"><div className="form-field"><label htmlFor="product-sku">SKU <span>必填 · 产品唯一编号</span></label><input ref={skuInput} id="product-sku" required maxLength={100} value={draft.sku} onChange={e => change('sku', e.target.value)} placeholder="例如：PERGOLA-GRAY-3X4" /></div><div className="form-field"><label htmlFor="product-category">品类</label><select id="product-category" value={draft.category} onChange={e => change('category', e.target.value)}>{['凉棚','车棚','其他'].map(value => <option key={value}>{value}</option>)}</select></div></div>
    <div className="form-field"><label htmlFor="product-name">产品名称 <span>必填</span></label><input id="product-name" required maxLength={120} value={draft.name} onChange={e => change('name', e.target.value)} placeholder="例如：3 × 4 米灰色铝制凉棚" /></div>
    <details className="product-optional" open={id ? true : undefined}><summary>补充尺寸、颜色与制作要求（选填）</summary><div className="form-field"><label htmlFor="product-dimensions">尺寸（含单位）</label><input id="product-dimensions" maxLength={300} value={draft.dimensions} onChange={e => change('dimensions', e.target.value)} placeholder="例如：长 4 m × 宽 3 m × 高 2.5 m" /></div>
    <div className="form-field"><label htmlFor="product-color">颜色</label><input id="product-color" maxLength={200} value={draft.color} onChange={e => change('color', e.target.value)} placeholder="例如：深灰色" /></div>
    <div className="form-field"><label htmlFor="product-facts">材质、结构与已确认特征</label><textarea id="product-facts" rows={3} maxLength={4000} value={draft.facts} onChange={e => change('facts', e.target.value)} placeholder="例如：铝制框架、四根立柱；只填写已确认的事实" /></div>
    <div className="form-field"><label htmlFor="product-notes">制作注意事项</label><textarea id="product-notes" rows={3} maxLength={2000} value={draft.notes} onChange={e => change('notes', e.target.value)} placeholder="例如：保持横梁与立柱连接结构，不新增侧帘" /></div></details></fieldset>
    {error && <p className="feedback feedback-error" role="alert">{error}</p>}
    <div className="form-actions">{creating && <button type="button" className="button-secondary" disabled={busy} onClick={cancelCreate}>取消</button>}{id && !dirty && <a className="button-secondary" href={`#/studio?product=${id}`}>用此产品创作</a>}<button className="button-primary" disabled={busy}>{busy ? '保存中…' : creating ? '保存并添加素材' : '保存修改'}</button></div></form>;
  return <section><div className="section-heading"><div><p className="eyebrow">YOUR PRODUCT LIBRARY</p><h2>产品资料</h2></div><button className="button-primary" disabled={busy || creating} onClick={() => select()}>新建产品</button></div><p className="settings-intro">这里保存产品本身的信息和原始素材：SKU、尺寸、颜色、实拍图。生图时直接选用；生成结果保存在生成记录。</p>
    <div className="settings-layout"><aside className="config-list"><div className="form-field"><label htmlFor="product-search">搜索产品</label><input id="product-search" value={search} onChange={e => setSearch(e.target.value)} placeholder="SKU 或产品名称" /></div>{products.filter(item => `${item.sku} ${item.name}`.toLowerCase().includes(search.toLowerCase())).map(item => <button type="button" key={item.id} disabled={busy} className={`config-item ${id === item.id ? 'config-item-active' : ''}`} onClick={() => select(item)}><strong>{item.name}</strong><small>{item.sku} · {item.category}</small></button>)}{loading ? <p className="empty-config">正在读取产品…</p> : !products.length ? <p className="empty-config">还没有产品资料。点击“新建产品”开始。</p> : !products.some(item => `${item.sku} ${item.name}`.toLowerCase().includes(search.toLowerCase())) && <p className="empty-config">没有匹配的产品，试试其他 SKU 或名称。</p>}</aside>
    <div className="config-form">
    {id ? <><div className="product-editor-heading"><h3>编辑产品 · {draft.name}</h3><span>基本信息</span></div>{productForm}</> : <div className="product-welcome"><span className="step-icon">产品资料</span><h3>{products.length ? '选择一个产品，查看资料和素材' : '先保存一款产品，下次出图直接复用'}</h3><p>例如：一款灰色凉棚的 SKU、尺寸和实拍图。保存后，在“图片创作”中选择它，就不用每次重新填写和上传。</p><button type="button" className="button-primary" disabled={busy || creating || loading} onClick={() => select()}>新建产品资料</button><small>只需填写 SKU 和产品名称即可保存，其他信息可以稍后补充。</small></div>}
    {error && !id && !creating && <p className="feedback feedback-error" role="alert">{error}</p>}
    {notice && <p className="feedback feedback-success" role="status">{notice}</p>}
    {id && <section className="product-assets"><h3>产品素材 · {assets.length} 张</h3><div className="form-field"><label htmlFor="asset-kind">素材类型</label><select id="asset-kind" value={kind} disabled={busy} onChange={e => setKind(e.target.value)}>{['产品实拍','结构细节','尺寸图','其他'].map(value => <option key={value}>{value}</option>)}</select></div><div className="form-field"><label htmlFor="asset-upload">添加图片</label><input id="asset-upload" type="file" multiple accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={e => { const files = Array.from(e.target.files || []); e.target.value = ''; void upload(files); }} /><small>每次最多 8 张，每张 20 MB、2000 万像素以内。上传仅保存到本机，生成时才发送选中的参考图。</small></div>{assetsLoading && <p>正在读取素材…</p>}<div className="asset-grid">{assets.map(asset => <a key={asset.id} className="asset-card" href={asset.image_url} target="_blank" rel="noreferrer"><img src={asset.image_url} alt={asset.name} loading="lazy" /><strong>{asset.kind}</strong><small>{asset.name}</small></a>)}</div></section>}
    </div></div>
    <dialog ref={dialog} className="product-dialog" aria-labelledby="new-product-title" aria-describedby="new-product-description" onCancel={e => { e.preventDefault(); cancelCreate(); }}>
      <div className="product-dialog-heading"><h2 id="new-product-title">新建产品资料</h2><button type="button" className="button-secondary" disabled={busy} onClick={cancelCreate} aria-label="关闭新建产品">关闭</button></div>
      <p id="new-product-description" className="settings-intro">先填写 SKU 和产品名称，保存后即可添加实拍图。带“必填”的两项完成就能建档。</p>
      {creating && productForm}
    </dialog>
    </section>;
}
