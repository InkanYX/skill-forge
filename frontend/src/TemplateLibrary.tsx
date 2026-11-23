import ImageSizePicker from './ImageSizePicker';
import { useEffect, useState, type FormEvent } from 'react';
import { creativeRequest, type CreativeTemplate } from './creativeApi';

const blank = () => ({ name: '', purpose: '', prompt: '', skill: '', skill_id: '', skill_revision: 0, skill_name: '', notes: '', size: 'default', count: 4, revision: 0 });
const examples = [
  { name: '凉棚 · 庭院场景', purpose: '用于 Listing 场景副图，展示真实庭院使用效果。', prompt: '以参考图中的{{产品名称}}为唯一产品依据，放置在{{场景}}。产品颜色为{{颜色}}，尺寸为{{尺寸}}。严格保留立柱数量、横梁连接、棚顶结构及比例，呈现真实自然光和接触阴影。', notes: '不得新增配件、改变结构或虚构承重、防水等性能。实拍和尺寸资料优先于文字推测。' },
  { name: '车棚 · 产品展示', purpose: '用于对比挑选产品展示构图。', prompt: '为{{产品名称}}制作写实产品展示图，背景为{{场景}}，颜色为{{颜色}}，尺寸为{{尺寸}}。以产品参考图为准，保持棚顶形态、支撑数量、连接件、材料纹理与产品比例。画面主体完整，边缘清晰。', notes: '不增加未随产品销售的配件。上架前人工核对产品结构、颜色及目标站点图片要求。' },
];

export default function TemplateLibrary() {
  const [items, setItems] = useState<CreativeTemplate[]>([]);
  const [id, setId] = useState('');
  const [draft, setDraft] = useState(blank);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  useEffect(() => {
    const unload = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); };
    const leave = (event: MouseEvent) => {
      const link = event.target instanceof Element ? event.target.closest('a') : null;
      if (dirty && link?.getAttribute('href')?.startsWith('#/') && !window.confirm('模板尚未保存，确定离开此页面吗？')) event.preventDefault();
    };
    window.addEventListener('beforeunload', unload); document.addEventListener('click', leave, true);
    return () => { window.removeEventListener('beforeunload', unload); document.removeEventListener('click', leave, true); };
  }, [dirty]);
  useEffect(() => { let active = true; creativeRequest<CreativeTemplate[]>('templates').then(value => { if (active) setItems(value); }).catch(err => { if (active) setError(String(err.message)); }); return () => { active = false; }; }, []);
  const readOnly = !!id && items.find(item=>item.id===id)?.can_edit === false;
  const variables = [...new Set([...`${draft.prompt}\n${draft.skill}\n${draft.notes}`.matchAll(/\{\{\s*([^{}\n]{1,40}?)\s*\}\}/g)].map(match => match[1].trim()))];
  function edit(value?: CreativeTemplate) {
    if (dirty && !window.confirm('当前内容尚未保存，是否放弃修改？')) return;
    setId(value?.id || ''); setDraft(value ? { ...blank(), ...value, skill_id: value.skill_id || '', skill_revision: value.skill_revision || 0, skill_name: value.skill_name || '' } : blank()); setDirty(false); setError(''); setMessage('');
  }
  function change(key: keyof ReturnType<typeof blank>, value: string | number) { setDraft(previous => ({ ...previous, [key]: value })); setDirty(true); setMessage(''); }
  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setMessage('');
    try {
      const { name, purpose, prompt, skill, skill_id, skill_revision, notes, size, count, revision } = draft;
      const value = await creativeRequest<CreativeTemplate>(id ? `templates/${id}` : 'templates', { name, purpose, prompt, skill, skill_id: skill_id || null, skill_revision, notes, size, count, revision }, id ? 'PUT' : 'POST');
      setItems(previous => [value, ...previous.filter(item => item.id !== value.id)]); setId(value.id); setDraft({ ...blank(), ...value, skill_id: value.skill_id || '', skill_revision: value.skill_revision || 0, skill_name: value.skill_name || '' }); setDirty(false); setMessage('模板已保存，可以用于图片创作。');
    } catch (err) { setError(err instanceof Error ? err.message : '保存失败'); } finally { setBusy(false); }
  }
  return <section><div className="section-heading"><div><p className="eyebrow">REUSABLE CREATIVE METHODS</p><h2>创作模板</h2></div><button className="button-secondary" disabled={busy} onClick={() => edit()}>新建模板</button></div>
    <p className="settings-intro">这里保存“怎么画”：画面要求、注意事项和默认出图参数。生图时套用模板，再选择产品或填写具体信息；产品实拍在产品资料中维护。</p>
    <div className="settings-layout"><aside className="config-list"><div className="list-title">已保存模板 · {items.length}</div>{items.map(item => <button type="button" key={item.id} disabled={busy} className={`config-item ${id === item.id ? 'config-item-active' : ''}`} onClick={() => edit(item)}><strong>{item.name}</strong><small>版本 {item.revision} · {item.variables.length} 项产品信息</small></button>)}{!items.length && <p className="empty-config">还没有模板，从右侧示例开始。</p>}</aside>
    <form className="config-form" onSubmit={save}>{readOnly && <p className="shared-readonly">团队共享模板，仅作者或管理员可修改。<button type="button" className="button-secondary" onClick={()=>{setId("");setDraft({...draft,name:draft.name+" · 副本",revision:0});setDirty(true);}}>复制为我的模板</button></p>}<fieldset disabled={busy || readOnly}>
      {!id && <div className="example-actions">{examples.map(example => <button type="button" className="button-secondary" key={example.name} onClick={() => { if (dirty && !window.confirm('用示例替换当前未保存的内容？')) return; setDraft({ ...blank(), ...example }); setDirty(true); }}>{example.name}</button>)}</div>}
      <div className="form-field"><label htmlFor="template-name">模板名称</label><input id="template-name" required maxLength={100} value={draft.name} onChange={e => change('name', e.target.value)} /></div>
      <div className="form-field"><label htmlFor="template-purpose">适用用途</label><input id="template-purpose" maxLength={1000} value={draft.purpose} onChange={e => change('purpose', e.target.value)} /></div>
      <div className="form-field"><label htmlFor="template-prompt">画面要求</label><textarea id="template-prompt" required rows={8} maxLength={12000} value={draft.prompt} onChange={e => change('prompt', e.target.value)} /><small>使用 {'{{产品名称}}'}、{'{{颜色}}'} 等占位符，套用时自动生成填写项。制作方法、分析要点和检查要求也写在这里。</small></div>
      {draft.skill.trim() && <p className="form-footnote">此模板包含旧版 Skill 内容，仍会参与生成。</p>}
      <div className="form-field"><label htmlFor="template-notes">注意事项</label><textarea id="template-notes" rows={3} maxLength={2000} value={draft.notes} onChange={e => change('notes', e.target.value)} /></div>
      <div className="template-defaults"><ImageSizePicker id="template-size" value={draft.size} onChange={value => change('size', value)} label="默认画幅" /><div className="form-field"><label htmlFor="template-count">默认数量</label><select id="template-count" value={draft.count} onChange={e => change('count', Number(e.target.value))}>{[1,2,3,4,5,6,7,8].map(n => <option key={n} value={n}>{n} 张</option>)}</select></div></div>
      <p className="form-footnote">自动识别的填写项：{variables.join('、') || '无'}</p>
    </fieldset>{error && <p className="feedback feedback-error" role="alert">{error}</p>}{message && <p className="feedback feedback-success" role="status">{message}</p>}<div className="form-actions">{id && !dirty && <a className="button-secondary" href={`#/studio?template=${id}`}>使用此模板</a>}<button className="button-primary" disabled={busy || readOnly}>{busy ? '保存中…' : '保存模板'}</button></div></form></div>
  </section>;
}
