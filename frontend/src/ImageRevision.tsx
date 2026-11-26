import { createRequestId } from './requestId';
import { apiFetch } from './apiFetch';
import TaskResultsPanel from './TaskResultsPanel';
import ImageSizePicker from './ImageSizePicker';
import { useEffect, useState, type FormEvent } from 'react';
import { creativeRequest } from './creativeApi';
import { listModelOptions as listConfigs, type ModelOption as ModelConfig } from './modelConfigApi';
import RevisionTrail from './RevisionTrail';
import { CreationSkillPicker, useCreationSkill } from './CreationSkillContext';
import { useAuth } from './AuthGate';
import { rememberCreation } from './resumeCreation';

interface RevisionJob {
  execution_profile?: {skill_workflow?: {primary: {name: string; version: string}}};
  id: string; task_id: string; config_id: string; model_name: string; size: string; status: string; message: string; prompt: string;
  image_url: string | null; preview_url?: string | null; parent_job_id: string | null; product_snapshot: { sku?: string; name?: string };
}
export default function ImageRevision() {
  const {user}=useAuth();
  const creationSkill = useCreationSkill();
  const sourceId = new URLSearchParams(window.location.hash.split('?')[1] || '').get('source') || '';
  const [source, setSource] = useState<RevisionJob>(); const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [configId, setConfigId] = useState(''); const [prompt, setPrompt] = useState(''); const [count, setCount] = useState(1); const [size, setSize] = useState('default');
  const [loading, setLoading] = useState(true); const [attempt, setAttempt] = useState(0); const [sourceError, setSourceError] = useState(''); const [error, setError] = useState('');
  const [busy, setBusy] = useState(false); const [requestId, setRequestId] = useState(''); const [ambiguous, setAmbiguous] = useState(false);
  const [currentTaskId, setCurrentTaskId] = useState('');
  useEffect(()=>{if(currentTaskId)rememberCreation(user.id,'#/studio?task='+encodeURIComponent(currentTaskId),'图片修改任务');},[currentTaskId,user.id]);
  const model = configs.find(item => item.id === configId);
  useEffect(() => {
    let active = true; setLoading(true); setSourceError('');
    if (!sourceId) { setSourceError('请先从生成记录选择一张已完成图片，再点击“继续修改”。'); setLoading(false); return; }
    Promise.all([creativeRequest<RevisionJob>(`image-jobs/${encodeURIComponent(sourceId)}`), listConfigs()]).then(([item, connections]) => {
      if (!active) return;
      if (item.status !== 'succeeded' || !item.image_url) { setSourceError('这张作品尚未完成，请在完成后继续修改。'); return; }
      setSource(item); setConfigs(connections); setSize(item.size);
      setConfigId(connections.find(c => c.config_id === item.config_id && c.model_name === item.model_name)?.id || connections.find(c => c.config_id === item.config_id)?.id || connections.find(c => c.model_name.trim())?.id || '');
    }).catch(err => { if (active) setSourceError(err instanceof Error ? err.message : '无法读取来源作品。'); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [sourceId, attempt]);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!source || !model || busy) return;
    const id = requestId || createRequestId(); setRequestId(id); setBusy(true); setError('');
    const body = new FormData();
    for (const [key, value] of Object.entries({ config_id: model.config_id, model_name: model.model_name, request_id: id, source_job_id: source.id, prompt, count: String(count), size })) body.set(key, value);
    try {
      creationSkill.append(body);
      const response = await apiFetch('/api/image-jobs/batch', { method: 'POST', body, signal: AbortSignal.timeout(30000) }); const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '修改任务提交失败。');
      const items = value as RevisionJob[]; setCurrentTaskId(items[0]?.task_id || id); setAmbiguous(false); setRequestId('');
    } catch (err) { setError(`${err instanceof Error ? err.message : '提交结果无法确认。'} 请先核对生成记录。重发相同提交会复用原任务。`); setAmbiguous(true); }
    finally { setBusy(false); }
  }
  function unlock() { if (window.confirm('请先核对生成记录。修改输入后再次提交会创建新任务，是否继续？')) { setAmbiguous(false); setRequestId(''); setError(''); } }
  return <section><div className="section-heading"><div><p className="eyebrow">REFINE YOUR IMAGE</p><h2>继续修改</h2></div><a className="button-secondary" href="#/library">返回生成记录</a></div><p className="settings-intro">描述哪里不对、希望如何调整。文本模型先理解要求，视觉模型核对来源图片，再依据 Skill 整理局部编辑提示词并修改原图。分析记录与提示词可在结果中查看，每次另存新版本。</p>
    <CreationSkillPicker inherited={source?.execution_profile?.skill_workflow?.primary} />
    {loading && <p role="status">正在读取来源作品…</p>}{sourceError && <p className="feedback feedback-error" role="alert">{sourceError} {sourceId && <button className="button-secondary" onClick={() => setAttempt(value => value + 1)}>重新读取</button>}</p>}
    {!loading && !sourceError && source && <><div className="revision-layout"><section className="revision-source"><h3>来源作品</h3><a href={source.image_url!} target="_blank" rel="noreferrer"><img src={source.preview_url || source.image_url!} alt="本次修改的来源作品" /></a><p>{source.product_snapshot.sku ? `${source.product_snapshot.sku} · ${source.product_snapshot.name}` : '未关联产品资料'}</p><small>原模型：{source.model_name}。沿用来源作品保存的产品资料和模板记录。</small><details><summary>查看来源制作要求</summary><p className="case-prompt">{source.prompt}</p></details></section>
    <form className="revision-form" onSubmit={submit}><fieldset disabled={busy || ambiguous}><div className="form-field"><label htmlFor="revision-model">生图模型</label><select id="revision-model" required value={configId} onChange={e => setConfigId(e.target.value)}><option value="">请选择已配置模型</option>{configs.map(item => <option key={item.id} value={item.id} disabled={!item.model_name.trim()}>{item.name} · {item.model_name || '未指定模型'}</option>)}</select><small>使用当前保存的配置调用图片编辑接口。<a href="#/settings">管理模型配置</a></small></div>
    <div className="form-field"><label htmlFor="revision-prompt">本次修改要求</label><textarea id="revision-prompt" required maxLength={8000} rows={6} value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="例如：将背景换成现代庭院，调整为柔和的傍晚光线，保持产品结构、颜色和构图。" /><small>明确写出需要变化和需要保留的内容。</small></div>
    <div className="template-defaults"><div className="form-field"><label htmlFor="revision-count">生成新版本数量</label><select id="revision-count" value={count} onChange={e => setCount(Number(e.target.value))}>{Array.from({length:16},(_,i)=><option key={i+1} value={i+1}>{i+1} 张</option>)}</select></div><ImageSizePicker id="revision-size" value={size} onChange={setSize} /></div></fieldset>
    {model && !model.has_api_key && <p className="feedback feedback-warning">请先在<a href="#/settings">个人模型配置</a>填写并保存 API Key。</p>}
    {error && <p className="feedback feedback-error" role="alert">{error}</p>}<div className="form-actions">{ambiguous && <button type="button" className="button-secondary" onClick={unlock}>核对后修改输入</button>}<button className="button-primary" disabled={busy || !model?.has_api_key || !model?.model_name.trim() || !prompt.trim()}>{busy ? '正在提交分析任务…' : ambiguous ? '重发相同提交' : `分析并修改 · ${count} 张新版本`}</button></div><p className="form-footnote">依次调用已配置的文本模型、视觉模型和图片编辑模型；分析失败或需要补充时不调用生图。来源图片作为实际编辑参考，每张另存新版本，原图保留；模型调用会消耗相应额度。</p></form></div>
    {currentTaskId && <section className="revision-results"><h3>本次修改结果</h3><TaskResultsPanel taskId={currentTaskId} /></section>}
    <RevisionTrail jobId={source.id} /></>}
  </section>;
}
