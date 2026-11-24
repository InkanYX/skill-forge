import { useEffect, useState, type KeyboardEvent } from 'react';
import ImageStudio from './ImageStudio';
import ImageSetStudio from './ImageSetStudio';
import AgentStudio from './AgentStudio';
import { CreationSkillPicker } from './CreationSkillContext';

type Mode = 'free' | 'set';
const modeOf = (route: string): Mode => {
  const mode = new URLSearchParams(route.split('?')[1] || '').get('mode');
  return mode === 'set' ? mode : 'free';
};
const modes: { id: Mode; label: string; description: string }[] = [
  { id: 'free', label: '自由创作 · 同一要求生成多张候选图', description: '选择已配置的模型、填写画面要求，一次生成多张候选图。添加产品参考图，可在原图基础上制作。' },
  { id: 'set', label: '成套制作 · 为每张图片安排不同用途', description: '为同一产品安排不同用途的图片。先编辑清单，再逐张检查，最后统一提交；同一参考图和公共要求会用于每张图片。' },
];

export default function ImageCreation({ route }: { route: string }) {
  const [mode, setMode] = useState<Mode>(() => modeOf(route));
  const [visited, setVisited] = useState(() => ({ free: modeOf(route) === 'free', set: modeOf(route) === 'set' }));
  const runId = new URLSearchParams(route.split('?')[1] || '').get('run');

  useEffect(() => {
    const next = modeOf(route);
    setMode(next); setVisited(previous => ({ ...previous, [next]: true }));
  }, [route]);

  function selectMode(next: Mode) {
    setMode(next); setVisited(previous => ({ ...previous, [next]: true }));
    const params = new URLSearchParams(window.location.hash.split('?')[1] || '');
    if (next !== 'free') params.set('mode', next); else params.delete('mode');
    const query = params.toString();
    // Keep the shared header and scroll position; selecting a tab is not a
    // page navigation. The URL still restores the selected mode on refresh.
    window.history.replaceState(window.history.state, '', `#/studio${query ? `?${query}` : ''}`);
  }

  function navigateTabs(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const target = event.key === 'Home' ? 0 : event.key === 'End' ? modes.length - 1
      : event.key === 'ArrowRight' ? (index + 1) % modes.length
      : event.key === 'ArrowLeft' ? (index + modes.length - 1) % modes.length : -1;
    if (target < 0) return;
    event.preventDefault(); selectMode(modes[target].id);
    document.getElementById(`creation-tab-${modes[target].id}`)?.focus();
  }

  return <section aria-labelledby="image-studio-heading">
    <div className="section-heading"><div><p className="eyebrow">CREATE YOUR NEXT IMAGES</p><h2 id="image-studio-heading">图片创作</h2></div><span>一次制作 1–8 张</span></div>
    {runId ? <><a className="button-secondary" href="#/studio">开始新的创作</a><AgentStudio key={runId} route={route} detailOnly /></> : <>
    <CreationSkillPicker />
    <div className="creation-modes" role="tablist" aria-label="图片创作方式">{modes.map((item, index) => <button key={item.id} type="button" role="tab" id={`creation-tab-${item.id}`} aria-controls={`creation-panel-${item.id}`} aria-selected={mode === item.id} tabIndex={mode === item.id ? 0 : -1} className={mode === item.id ? 'creation-mode-active' : ''} onClick={() => selectMode(item.id)} onKeyDown={event => navigateTabs(event, index)}>{item.label}</button>)}</div>
    {modes.map(item => <div key={item.id} role="tabpanel" id={`creation-panel-${item.id}`} aria-labelledby={`creation-tab-${item.id}`} hidden={mode !== item.id}>
      {visited[item.id] && <><p className="settings-intro">{item.description}</p>{item.id === 'free' ? <ImageStudio active={mode === 'free'} /> : <ImageSetStudio showSkillPicker={false} />}</>}
    </div>)}
    </>}
  </section>;
}
