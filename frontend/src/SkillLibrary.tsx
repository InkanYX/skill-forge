import { useEffect, useRef, useState, type FormEvent } from 'react';
import { creativeRequest, type CreativeSkill } from './creativeApi';

const blank = () => ({ name: '', purpose: '', content: '', revision: 0 });
interface SkillVersion { revision: number; name: string; updated_at: string }
export default function SkillLibrary() {
  const [items, setItems] = useState<CreativeSkill[]>([]); const [selected, setSelected] = useState<CreativeSkill>(); const [preview, setPreview] = useState<CreativeSkill>();
  const [versions, setVersions] = useState<SkillVersion[]>([]); const [search, setSearch] = useState('');
  const [draft, setDraft] = useState(blank); const [editingId, setEditingId] = useState(''); const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false); const [dirty, setDirty] = useState(false); const [historyBusy, setHistoryBusy] = useState(false);
  const [error, setError] = useState(''); const [formError, setFormError] = useState(''); const [notice, setNotice] = useState('');
  const dialog = useRef<HTMLDialogElement>(null); const nameInput = useRef<HTMLInputElement>(null); const mounted = useRef(true);
  const variables = [...new Set([...(preview?.content || '').matchAll(/\{\{\s*([^{}\n]{1,40}?)\s*\}\}/g)].map(match => match[1].trim()))];
  useEffect(() => {
    mounted.current = true;
    creativeRequest<CreativeSkill[]>('skills').then(value => { if (mounted.current) setItems(value); }).catch(err => { if (mounted.current) setError(err.message); }).finally(() => { if (mounted.current) setLoading(false); });
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    let active = true; setPreview(selected); setVersions([]);
    if (!selected) return;
    creativeRequest<SkillVersion[]>(`skills/${selected.id}/versions`).then(value => { if (active) setVersions(value); }).catch(err => { if (active) setError(err.message); });
    return () => { active = false; };
  }, [selected]);
  useEffect(() => { if (editing) { dialog.current?.showModal(); nameInput.current?.focus(); } else dialog.current?.close(); }, [editing]);
  useEffect(() => {
    const unload = (event: BeforeUnloadEvent) => { if (dirty || busy) event.preventDefault(); };
    const leave = (event: MouseEvent) => { const link = event.target instanceof Element ? event.target.closest('a') : null; if ((dirty || busy) && link?.getAttribute('href')?.startsWith('#/') && !window.confirm('Skill 尚未保存，确定离开吗？')) event.preventDefault(); };
    window.addEventListener('beforeunload', unload); document.addEventListener('click', leave, true);
    return () => { window.removeEventListener('beforeunload', unload); document.removeEventListener('click', leave, true); };
  }, [dirty, busy]);
  function openEditor(item?: CreativeSkill) { setDraft(item ? { name: item.name, purpose: item.purpose, content: item.content, revision: item.revision } : blank()); setEditingId(item?.id || ''); setEditing(true); setDirty(false); setFormError(''); setNotice(''); }
  function closeEditor() { if (busy || (dirty && !window.confirm('放弃尚未保存的 Skill 修改？'))) return; setEditing(false); setDirty(false); setFormError(''); }
  function change(field: keyof ReturnType<typeof blank>, value: string) { setDraft(previous => ({ ...previous, [field]: value })); setDirty(true); }
  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setFormError('');
    try {
      const value = await creativeRequest<CreativeSkill>(editingId ? `skills/${editingId}` : 'skills', draft, editingId ? 'PUT' : 'POST');
      if (!mounted.current) return;
      setItems(previous => [value, ...previous.filter(item => item.id !== value.id)]); setSelected(value); setDirty(false); setEditing(false); setError(''); setNotice(`Skill 已保存为版本 ${value.revision}。可在创作模板中关联使用。`);
    } catch (err) { if (mounted.current) setFormError(err instanceof Error ? err.message : '保存失败'); } finally { if (mounted.current) setBusy(false); }
  }
  async function importFile(file?: File) {
    if (!file) return;
    if (!/\.(md|txt)$/i.test(file.name) || file.size > 100000) { setFormError('请选择 100 KB 以内的 Markdown 或 TXT 文件。'); return; }
    setBusy(true); setFormError('');
    try {
      const content = await file.text();
      if (content.length > 20000) { setFormError('Skill 内容不能超过 20000 字符。'); return; }
      setDraft(previous => ({ ...previous, name: previous.name || file.name.replace(/\.(md|txt)$/i, '').slice(0,100), content })); setDirty(true);
    } catch { setFormError('文件读取失败，请重新选择。'); } finally { setBusy(false); }
  }
  async function viewVersion(revision: number) {
    if (!selected) return; setHistoryBusy(true); setError('');
    try { setPreview(await creativeRequest<CreativeSkill>(`skills/${selected.id}?revision=${revision}`)); } catch (err) { setError(err instanceof Error ? err.message : '读取版本失败'); } finally { setHistoryBusy(false); }
  }
  return <section><div className="section-heading"><div><p className="eyebrow">YOUR REUSABLE SKILLS</p><h2>Skill 管理</h2></div><button type="button" className="button-primary" disabled={loading || busy || historyBusy} onClick={() => openEditor()}>新建 / 导入 Skill</button></div><div className="creation-modes"><a href="#/templates">创作模板</a><span className="creation-mode-active">Skill 管理</span></div><p className="settings-intro">Skill 保存可复用的制作方法，模板保存具体用途和参数。同一份 Skill 可以关联多个模板；内容作为自然语言指令使用。</p>
    {error && <p className="feedback feedback-error" role="alert">{error}</p>}{notice && <p className="feedback feedback-success" role="status">{notice}</p>}
    <div className="settings-layout"><aside className="config-list"><div className="form-field"><label htmlFor="skill-search">搜索 Skill</label><input id="skill-search" value={search} onChange={e => setSearch(e.target.value)} placeholder="名称、用途或内容关键词" /></div>{loading && <p className="empty-config">正在读取…</p>}{items.filter(item => `${item.name} ${item.purpose} ${item.content}`.toLowerCase().includes(search.toLowerCase())).map(item => <button type="button" className={`config-item ${selected?.id === item.id ? 'config-item-active' : ''}`} key={item.id} disabled={historyBusy} onClick={() => { setSelected(item); setNotice(''); setError(''); }}><strong>{item.name}</strong><small>版本 {item.revision} · {item.purpose || '未填写用途'}</small></button>)}{!loading && !items.length && <p className="empty-config">还没有 Skill，点击右侧按钮导入已有内容。</p>}</aside>
    <div className="config-form">{selected && preview ? <><div className="section-heading"><h3>{preview.name}</h3><button type="button" className="button-secondary" disabled={historyBusy} onClick={() => openEditor(selected)}>编辑最新版</button></div><p className="settings-intro">{preview.purpose || '未填写用途'}</p><div className="form-field"><label htmlFor="skill-version">查看版本</label><select id="skill-version" disabled={historyBusy} value={preview.revision} onChange={e => void viewVersion(Number(e.target.value))}>{versions.length ? versions.map(item => <option key={item.revision} value={item.revision}>版本 {item.revision} · {new Date(item.updated_at).toLocaleString('zh-CN')}</option>) : <option value={preview.revision}>版本 {preview.revision}</option>}</select></div><p className="form-footnote">填写项：{variables.join('、') || '无'}。当前内容 {preview.content.length} 字符。</p><pre className="skill-content">{preview.content}</pre><div className="result-actions"><a className="button-secondary" href={`/api/skills/${preview.id}/download?revision=${preview.revision}`}>导出此版本 Markdown</a><a className="button-primary" href="#/templates">到创作模板中关联</a></div><p className="form-footnote">编辑会保存新版本。已关联模板保持原版本，需要在模板中主动同步并保存。</p></> : <div className="product-welcome"><span className="step-icon">自然语言 Skill</span><h3>把你写好的制作方法保存到这里</h3><p>例如“保持车棚产品结构”的制作要求。导入一次，多个创作模板即可复用，不用反复复制。</p><button type="button" className="button-primary" disabled={loading} onClick={() => openEditor()}>导入第一份 Skill</button><small>支持 Markdown / TXT，最多 100 KB、20000 字符。</small></div>}</div></div>
    <dialog ref={dialog} className="product-dialog skill-dialog" aria-labelledby="skill-editor-title" onCancel={e => { e.preventDefault(); closeEditor(); }}><div className="product-dialog-heading"><h2 id="skill-editor-title">{editingId ? '编辑 Skill' : '新建 / 导入 Skill'}</h2><button className="button-secondary" disabled={busy} onClick={closeEditor}>关闭</button></div><p className="settings-intro">粘贴已有内容，或选择 Markdown / TXT 文件导入。文件里的内容仅作为自然语言指令保存。</p><form onSubmit={save}><fieldset disabled={busy} className="set-fieldset"><div className="form-field"><label htmlFor="skill-name">Skill 名称</label><input ref={nameInput} id="skill-name" required maxLength={100} value={draft.name} onChange={e => change('name', e.target.value)} placeholder="例如：凉棚结构保真" /></div><div className="form-field"><label htmlFor="skill-purpose">适用用途（选填）</label><input id="skill-purpose" maxLength={1000} value={draft.purpose} onChange={e => change('purpose', e.target.value)} /></div><div className="form-field"><label htmlFor="skill-import">导入已有文件</label><input id="skill-import" type="file" accept=".md,.txt,text/plain,text/markdown" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; if (!file) return; if (draft.content.trim() && !window.confirm('用文件内容替换当前草稿内容？')) return; void importFile(file); }} /></div><div className="form-field"><label htmlFor="skill-content">自然语言内容</label><textarea id="skill-content" required rows={9} maxLength={20000} value={draft.content} onChange={e => change('content', e.target.value)} placeholder="粘贴你已经写好的 Skill" /><small>{draft.content.length} / 20000 字符。不执行脚本或自动多步骤流程。</small></div></fieldset>{formError && <p className="feedback feedback-error" role="alert">{formError}</p>}<div className="form-actions"><button type="button" className="button-secondary" disabled={busy} onClick={closeEditor}>取消</button><button className="button-primary" disabled={busy}>{busy ? '处理中…' : editingId ? '保存新版本' : '保存 Skill'}</button></div></form></dialog>
  </section>;
}
