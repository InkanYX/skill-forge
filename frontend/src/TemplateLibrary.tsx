import ImageSizePicker from './ImageSizePicker';
import { useEffect, useState, type FormEvent } from 'react';
import { creativeRequest, type CreativeTemplate, type CreativeSkill } from './creativeApi';

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
  const [skills, setSkills] = useState<CreativeSkill[]>([]);
  const [skillError, setSkillError] = useState('');
  const linkedSkill = skills.find(item => item.id === draft.skill_id);
  async function refreshSkills() { try { setSkills(await creativeRequest<CreativeSkill[]>('skills')); setSkillError(''); } catch { setSkillError('Skill 列表读取失败，可刷新重试；本模板已有内容会保留。'); } }
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
  useEffect(() => { let active = true; creativeRequest<CreativeSkill[]>('skills').then(value => { if (active) setSkills(value); }).catch(() => { if (active) setSkillError('Skill 列表读取失败，可刷新重试。'); }); return () => { active = false; }; }, []);
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
    <p className="settings-intro">这里保存“怎么画”：画面要求、Skill、注意事项和默认出图参数。生图时套用模板，再选择产品或填写具体信息；产品实拍在产品资料中维护。</p>
    <div className="creation-modes"><span className="creation-mode-active">创作模板</span><a href="#/skills">Skill 管理</a></div>
    <div className="settings-layout"><aside className="config-list"><div className="list-title">已保存模板 · {items.length}</div>{items.map(item => <button type="button" key={item.id} disabled={busy} className={`config-item ${id === item.id ? 'config-item-active' : ''}`} onClick={() => edit(item)}><strong>{item.name}</strong><small>版本 {item.revision} · {item.variables.length} 项产品信息</small></button>)}{!items.length && <p className="empty-config">还没有模板，从右侧示例开始。</p>}</aside>
    <form className="config-form" onSubmit={save}><fieldset disabled={busy}>
      {!id && <div className="example-actions">{examples.map(example => <button type="button" className="button-secondary" key={example.name} onClick={() => { if (dirty && !window.confirm('用示例替换当前未保存的内容？')) return; setDraft({ ...blank(), ...example }); setDirty(true); }}>{example.name}</button>)}</div>}
      <div className="form-field"><label htmlFor="template-name">模板名称</label><input id="template-name" required maxLength={100} value={draft.name} onChange={e => change('name', e.target.value)} /></div>
      <div className="form-field"><label htmlFor="template-purpose">适用用途</label><input id="template-purpose" maxLength={1000} value={draft.purpose} onChange={e => change('purpose', e.target.value)} /></div>
      <div className="form-field"><label htmlFor="template-prompt">画面要求</label><textarea id="template-prompt" required rows={6} maxLength={12000} value={draft.prompt} onChange={e => change('prompt', e.target.value)} /><small>使用 {'{{产品名称}}'}、{'{{颜色}}'} 等占位符，套用时自动生成填写项。</small></div>
      <div className="form-field"><label htmlFor="template-skill-source">Skill 来源</label><div className="input-with-action"><select id="template-skill-source" value={draft.skill_id} onChange={e => { const item = skills.find(skill => skill.id === e.target.value); if (item && draft.skill.trim() && draft.skill !== item.content && !window.confirm('用所选 Skill 替换本模板当前内容？')) return; setDraft(previous => ({ ...previous, skill_id: item?.id || '', skill_revision: item?.revision || 0, skill_name: item?.name || '', skill: item?.content ?? previous.skill })); setDirty(true); setMessage(''); }}><option value="">仅在本模板内编写</option>{draft.skill_id && !linkedSkill && <option value={draft.skill_id}>{draft.skill_name || '已关联 Skill'} · 固定版本 {draft.skill_revision}</option>}{skills.map(item => <option key={item.id} value={item.id}>{item.name} · 最新版本 {item.revision}</option>)}</select><button type="button" className="button-secondary" onClick={refreshSkills}>刷新</button></div>{skillError && <small>{skillError}</small>}{draft.skill_id && <small>当前固定使用 {draft.skill_name} · 版本 {draft.skill_revision}。保存模板不会自动切到新版本。</small>}{linkedSkill && linkedSkill.revision > draft.skill_revision && <div className="feedback feedback-warning">此 Skill 已更新至版本 {linkedSkill.revision}。<button type="button" className="button-secondary" onClick={() => { setDraft(previous => ({ ...previous, skill: linkedSkill.content, skill_revision: linkedSkill.revision, skill_name: linkedSkill.name })); setDirty(true); setMessage('已同步到草稿，请保存模板使其生效。'); }}>同步最新版到草稿</button></div>}</div>
      <div className="form-field"><label htmlFor="template-skill">自然语言 Skill 内容</label><textarea id="template-skill" readOnly={!!draft.skill_id} rows={5} maxLength={20000} value={draft.skill} onChange={e => change('skill', e.target.value)} placeholder="粘贴你的制作方法、分析要点和检查要求" />{!draft.skill_id && <input aria-label="导入 Skill 文件" type="file" accept=".md,.txt,text/plain,text/markdown" onChange={async e => { const file = e.target.files?.[0]; if (!file) return; if (file.size > 100000) { setError('Skill 文件不能超过 100 KB。'); return; } const text = await file.text(); if (text.length > 20000) { setError('Skill 不能超过 20000 字符。'); return; } change('skill', text); setError(''); e.target.value = ''; }} />}<small>{draft.skill_id ? '关联内容只读。修改公共内容请到 Skill 管理；选择“仅在本模板内编写”可复制为本模板内容。' : '支持粘贴或导入 Markdown／TXT，也可以从上方 Skill 库关联。'} 内容作为自然语言指令，不执行脚本或自动多步骤流程。</small></div>
      <div className="form-field"><label htmlFor="template-notes">注意事项</label><textarea id="template-notes" rows={3} maxLength={2000} value={draft.notes} onChange={e => change('notes', e.target.value)} /></div>
      <div className="template-defaults"><ImageSizePicker id="template-size" value={draft.size} onChange={value => change('size', value)} label="默认尺寸" /><div className="form-field"><label htmlFor="template-count">默认数量</label><select id="template-count" value={draft.count} onChange={e => change('count', Number(e.target.value))}>{[1,2,3,4,5,6,7,8].map(n => <option key={n} value={n}>{n} 张</option>)}</select></div></div>
      <p className="form-footnote">自动识别的填写项：{variables.join('、') || '无'}</p>
    </fieldset>{error && <p className="feedback feedback-error" role="alert">{error}</p>}{message && <p className="feedback feedback-success" role="status">{message}</p>}<div className="form-actions">{id && !dirty && <a className="button-secondary" href={`#/studio?template=${id}`}>使用此模板</a>}<button className="button-primary" disabled={busy}>{busy ? '保存中…' : '保存模板'}</button></div></form></div>
  </section>;
}
