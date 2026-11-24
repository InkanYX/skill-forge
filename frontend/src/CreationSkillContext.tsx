import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { useAuth } from './AuthGate';
import { listPackages, type SkillPackage } from './skillPackageApi';

interface SkillChoice { skill_id: string; version_id: string }
interface SkillState {
  packages: SkillPackage[]; selection: SkillChoice | null; ready: boolean; error: string;
  choose: (id: string) => void; append: (form: FormData) => void;
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
  const [selection, setSelection] = useState<SkillChoice | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    listPackages().then(items => {
      if (!alive) return;
      setPackages(items.filter(item => item.current_version && (item.source === 'builtin' || !item.owner_id || item.owner_id === user.id)));
    }).catch(err => { if (alive) setError(err instanceof Error ? err.message : '制作技能读取失败'); });
    return () => { alive = false; };
  }, [user.id]);
  const ready = packages.length > 0;
  function choose(id: string) {
    const item = packages.find(item => item.id === id);
    setSelection(item?.current_version ? {skill_id: item.id, version_id: item.current_version.id} : null);
  }
  function append(form: FormData) {
    if (!ready) throw new Error(error || '制作技能尚未就绪，请稍后重试。');
    if (!selection && !form.has('source_job_id') && !packages.some(item => item.name === 'premium-product-image-workflow' && item.source === 'builtin')) throw new Error('默认技能未启用，请选择其他制作技能。');
    if (selection) form.set('skill', JSON.stringify(selection));
  }
  return <Context.Provider value={{packages, selection, ready, error, choose, append}}>{children}</Context.Provider>;
}

export function CreationSkillPicker({ inherited }: {inherited?: {name: string; version: string}}) {
  const {packages, selection, ready, error, choose} = useCreationSkill();
  const recommended = packages.find(item => item.name === 'premium-product-image-workflow' && item.source === 'builtin');
  const name = (id: string) => id === 'premium-product-image-workflow' ? '商品图工作流' : id === 'amazon-a-plus' ? 'A+ 制作规范' : id;
  return <section className="creation-skill-bar" aria-label="制作技能">
    <div className="form-field"><label htmlFor="creation-skill">制作技能 · 每次创作都会应用</label>
      <select id="creation-skill" value={selection?.skill_id || ''} disabled={!ready} onChange={event => choose(event.target.value)}>
        <option value="">{inherited ? `沿用来源：${name(inherited.name)} · ${inherited.version}` : recommended ? `${name(recommended.name)} · ${recommended.current_version?.version_label}（默认）` : ready ? '请选择制作技能' : '正在读取默认技能…'}</option>
        {packages.map(item => <option key={item.id} value={item.id}>{name(item.name)} · {item.current_version?.version_label}</option>)}
      </select>
      <small>自动按用途读取规范，A+ 任务会组合配套规则；本次使用的版本随结果保存。<a href="#/skills">管理技能库</a></small>
      <small>使用已配置的文字模型整理要求；视觉模型留空时，图片待人工审核。</small>
    </div>
    {error && <p className="feedback feedback-error" role="alert">{error}</p>}
  </section>;
}
