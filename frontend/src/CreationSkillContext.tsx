import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { useAuth } from './AuthGate';
import { listPackages, type SkillPackage } from './skillPackageApi';

interface SkillState {
  packages: SkillPackage[]; selectedIds: string[]; mode: 'auto' | 'manual'; allowAuto: boolean;
  ready: boolean; error: string; reload: () => Promise<void>;
  setMode: (mode: 'auto' | 'manual') => void; toggle: (id: string) => void;
  setAllowAuto: (value: boolean) => void; append: (form: FormData) => void;
}
const Context = createContext<SkillState | null>(null);
export function useCreationSkill() {
  const value = useContext(Context);
  if (!value) throw new Error('缺少创作技能上下文');
  return value;
}
export function CreationSkillProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [packages, setPackages] = useState<SkillPackage[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [mode, setMode] = useState<'auto' | 'manual'>('auto');
  const [allowAuto, setAllowAuto] = useState(false);
  const [error, setError] = useState('');
  async function reload() {
    try {
      const items = await listPackages();
      const available = items.filter(item => item.current_version && (item.source === 'builtin' || !item.owner_id || item.owner_id === user.id));
      setPackages(available); setError('');
      setSelectedIds(previous => previous.filter(id => available.some(item => item.id === id)));
    } catch (err) { setError(err instanceof Error ? err.message : '制作技能读取失败'); }
  }
  useEffect(() => {
    let alive = true;
    const refresh = () => { if (alive) void reload(); };
    refresh();
    window.addEventListener('skill-forge:skills-changed', refresh);
    window.addEventListener('focus', refresh);
    return () => {
      alive = false;
      window.removeEventListener('skill-forge:skills-changed', refresh);
      window.removeEventListener('focus', refresh);
    };
    // Reload when the account changes; task versions are pinned by the backend.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user.id]);
  function toggle(id: string) {
    setSelectedIds(previous => previous.includes(id) ? previous.filter(value => value !== id) : [...previous, id]);
  }
  const ready = !error && packages.length > 0 && (mode === 'auto' || selectedIds.length > 0);
  function append(form: FormData) {
    if (!ready) throw new Error(error || (mode === 'manual' ? '请至少指定一个技能。' : '制作技能尚未就绪，请重新读取。'));
    // Continuations retain the source's frozen library unless explicitly overridden.
    if (mode === 'auto' && form.has('source_job_id')) return;
    const skills = selectedIds.map(id => {
      const item = packages.find(value => value.id === id);
      if (!item?.current_version) throw new Error('指定技能已不可用，请重新选择。');
      return { skill_id: item.id, version_id: item.current_version.id };
    });
    form.set('skill', JSON.stringify({ mode, skills: mode === 'manual' ? skills : [], allow_auto: mode === 'auto' || allowAuto }));
  }
  return <Context.Provider value={{ packages, selectedIds, mode, allowAuto, ready, error, reload, setMode, toggle, setAllowAuto, append }}>{children}</Context.Provider>;
}

export function CreationSkillPicker({ inherited }: { inherited?: { name: string; version: string } }) {
  const state = useCreationSkill();
  const [expanded, setExpanded] = useState(false);
  const [search, setSearch] = useState('');
  const visible = state.packages.filter(item => (item.name + ' ' + item.description).toLowerCase().includes(search.toLowerCase()));
  return <section className="creation-skill-choice" aria-label="制作技能">
    <div className="creation-skill-choice-heading"><div><strong>制作技能</strong><span>{state.mode === 'auto' ? inherited ? '沿用来源任务的技能范围' : '自动选择' : '已指定 ' + state.selectedIds.length + ' 个技能'}</span></div>
      <button type="button" className="button-secondary" aria-expanded={expanded} onClick={() => setExpanded(value => !value)}>{expanded ? '收起选择' : '调整技能'}</button>
    </div>
    <p>{state.mode === 'auto' ? inherited ? '继续使用来源任务锁定的技能版本；AI 按本轮要求读取相关资料。' : 'AI 从已启用、本人可用的技能中选择，并按需读取相关资料。' : '勾选的技能会固定加载；相关参考文件由 AI 按需读取。'}</p>
    {state.mode === 'manual' && state.selectedIds.length > 0 && <div className="creation-selected-skills">{state.packages.filter(item => state.selectedIds.includes(item.id)).map(item => <span key={item.id}>{item.name}</span>)}</div>}
    {expanded && <div className="creation-skill-options">
      <div className="creation-skill-mode"><label><input type="radio" name="creation-skill-mode" checked={state.mode === 'auto'} onChange={() => state.setMode('auto')} />自动选择</label><label><input type="radio" name="creation-skill-mode" checked={state.mode === 'manual'} onChange={() => state.setMode('manual')} />指定技能</label></div>
      {state.mode === 'manual' && <label className="creation-skill-extra"><input type="checkbox" checked={state.allowAuto} onChange={event => state.setAllowAuto(event.target.checked)} />允许 AI 额外搭配其他可用技能</label>}
      <div className="form-field"><label htmlFor="creation-skill-search">{state.mode === 'auto' ? '可自动选用的技能' : '选择必须使用的技能'}</label><input id="creation-skill-search" value={search} onChange={event => setSearch(event.target.value)} placeholder="搜索名称或用途" /></div>
      <div className="creation-skill-catalog">{visible.map(item => <label className="creation-skill-option" key={item.id}>
        {state.mode === 'manual' && <input type="checkbox" checked={state.selectedIds.includes(item.id)} disabled={state.selectedIds.length >= 12 && !state.selectedIds.includes(item.id)} onChange={() => state.toggle(item.id)} />}
        <span><strong>{item.name}</strong><small>{item.description || '未填写用途说明'}</small></span>
      </label>)}</div>
      {!visible.length && <p>没有匹配的可用技能。</p>}
      <div className="creation-skill-links"><button type="button" onClick={() => void state.reload()}>刷新列表</button><a href="#/skills">管理技能库 ↗</a></div>
    </div>}
    {state.error && <p className="feedback feedback-error" role="alert">{state.error}</p>}
    {!state.error && !state.packages.length && <p className="form-footnote">正在读取可用技能；若尚未导入，请到技能库添加并启用。</p>}
  </section>;
}
