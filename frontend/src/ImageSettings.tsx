import { useEffect, useRef, useState, type FormEvent } from 'react';
import { apiFetch } from './apiFetch';
import { imageConfigRequest, type ImageConfiguration } from './imageConfigApi';
import type { ProbeResult, ConnectionResult } from './modelConfigApi';
import { readModels as readDraftModels, testConfig as testDraftConnection } from './modelConfigApi';
import ImageVerificationResult from './ImageVerificationResult';

type Kind = 'text' | 'vision' | 'generate' | 'edit' | 'tools';
type ParameterKey = 'request_parameters' | 'text_parameters' | 'vision_parameters';
type Options = Record<ParameterKey, Record<string, unknown>>;
type DraftParameters = Record<ParameterKey, string>;
type Feedback = { message: string; error?: boolean };
const kinds: Kind[] = ['text', 'tools', 'vision', 'generate', 'edit'];
const labels: Record<Kind, string> = { text: '文字调用', tools: '工具调用', vision: '图片理解', generate: '图片生成', edit: '图片编辑' };
const descriptions: Record<Kind, string> = {
  tools: '检查模型能否返回工具调用，用于读取技能、PDF 和产品图片；文字回复成功并不代表具备此能力。',
  text: '输入一段文字，查看模型的实际回复；也可直接运行简短的能力检查。',
  vision: '发送系统提供的测试图片，检查模型能否理解图片内容。',
  generate: '使用简短的测试提示词生成一张图片，结果会保存在生成记录中。',
  edit: '上传参考图，检查模型能否根据这张图片进行修改。结果会保存在生成记录中。',
};
const parameterFields: { key: ParameterKey; label: string; hint: string }[] = [
  { key: 'request_parameters', label: '图片生成与编辑', hint: '如 quality、size、output_format，以服务商文档为准。' },
  { key: 'text_parameters', label: '文字调用', hint: '如 temperature、max_tokens，以服务商文档为准。' },
  { key: 'vision_parameters', label: '图片理解', hint: '用于携带图片的文字请求。' },
];
const empty = (): Options => ({ request_parameters: {}, text_parameters: {}, vision_parameters: {} });
const toDraft = (options: Partial<Options> = {}): DraftParameters => ({
  request_parameters: JSON.stringify(options.request_parameters || {}, null, 2),
  text_parameters: JSON.stringify(options.text_parameters || {}, null, 2),
  vision_parameters: JSON.stringify(options.vision_parameters || {}, null, 2),
});
const stateLabel = (state?: string) => ({ supported: '已支持', unsupported: '不支持', error: '待确认' }[state || ''] || '未验证');

export default function ImageSettings() {
  const [config, setConfig] = useState<ImageConfiguration | null>(null);
  const [name, setName] = useState('我的模型连接');
  const [url, setUrl] = useState('');
  const [key, setKey] = useState('');
  const [models, setModels] = useState<string[]>([]);
  const [model, setModel] = useState('');
  const [planningModel, setPlanningModel] = useState('');
  const [imageModel, setImageModel] = useState('');
  const [added, setAdded] = useState('');
  const [candidates, setCandidates] = useState<string[]>([]);
  const [options, setOptions] = useState<Record<string, Options>>({});
  const [params, setParams] = useState<DraftParameters>(toDraft());
  const [autoReview, setAutoReview] = useState(false);
  const [generationPath, setGenerationPath] = useState('/images/generations');
  const [editPath, setEditPath] = useState('/images/edits');
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [busy, setBusy] = useState('');
  const [feedback, setFeedback] = useState<Feedback>();
  const [connectionFeedback, setConnectionFeedback] = useState<Feedback>();
  const [modelFeedback, setModelFeedback] = useState<Feedback>();
  const [attempt, setAttempt] = useState(0);
  const [kind, setKind] = useState<Kind>('text');
  const [prompt, setPrompt] = useState('');
  const [output, setOutput] = useState('');
  const [runError, setRunError] = useState('');
  const [runTime, setRunTime] = useState('');
  const [reference, setReference] = useState<File>();
  const [authorized, setAuthorized] = useState(false);
  const [taskId, setTaskId] = useState('');
  const [taskPending, setTaskPending] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const ids = useRef<Partial<Record<Kind, string>>>({});
  const dirtyRef = useRef(dirty);
  dirtyRef.current = dirty;

  function clearResult() {
    setTaskId(''); setRunError(''); setOutput(''); setRunTime(''); setAuthorized(false);
  }
  function change() {
    setDirty(true); setFeedback(undefined); setConnectionFeedback(undefined); setAuthorized(false);
  }
  function parsed(): Options {
    return Object.fromEntries(parameterFields.map(({ key: field, label }) => {
      let value: unknown;
      try { value = JSON.parse(params[field]); }
      catch { throw new Error('“' + label + '”参数不是有效的 JSON，请展开可选请求参数检查。'); }
      if (!value || typeof value !== 'object' || Array.isArray(value)) {
        throw new Error('“' + label + '”参数需为 JSON 对象，例如 {}。');
      }
      return [field, value];
    })) as Options;
  }
  function choose(id: string): boolean {
    if (id === model) return true;
    try {
      const active = parsed();
      setOptions(previous => ({ ...previous, ...(model ? { [model]: active } : {}) }));
      setModel(id); setParams(toDraft(options[id] || empty())); change(); clearResult();
      return true;
    } catch (err) {
      setFeedback({ message: err instanceof Error ? err.message : '请检查参数。', error: true });
      return false;
    }
  }
  function addModel() {
    const id = added.trim();
    if (!id) return;
    if (choose(id)) {
      setModels(previous => previous.includes(id) ? previous : [...previous, id]);
      setAdded(''); setModelFeedback(undefined);
    }
  }

  useEffect(() => {
    let alive = true;
    imageConfigRequest<ImageConfiguration | null>().then(value => {
      if (!alive) return;
      setConfig(value); setLoadError('');
      if (value && !dirtyRef.current) {
        setName(value.name); setUrl(value.base_url); const names = value.model_names || []; setModels(names); setModel(names.includes(value.model_name) ? value.model_name : names[0] || '');
        setOptions(value.model_settings || {}); setParams(toDraft(value));
        setAutoReview(value.auto_review); setGenerationPath(value.generation_path); setEditPath(value.edit_path);
        setPlanningModel(value.planning_model_name || ''); setImageModel(value.image_model_name || '');
      }
    }).catch(err => { if (alive) setLoadError(err.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [attempt]);

  async function save(event: FormEvent) {
    event.preventDefault(); setFeedback(undefined);
    if (!model || !models.length) {
      setFeedback({ message: '请先添加一个模型，再保存配置。', error: true }); return;
    }
    setBusy('save');
    try {
      const active = parsed();
      const all = Object.fromEntries(Object.entries({ ...options, [model]: active })
        .filter(([id]) => models.includes(id))
        .map(([id, item]) => [id, {
          request_parameters: item.request_parameters || {}, text_parameters: item.text_parameters || {},
          vision_parameters: item.vision_parameters || {},
        }]));
      const value = await imageConfigRequest<ImageConfiguration>('', {
        name, base_url: url, api_key: key || null, model_name: model, model_names: models,
        model_options: all, ...active, auto_review: autoReview, generation_path: generationPath, edit_path: editPath,
        planning_model_name: planningModel, image_model_name: imageModel,
      });
      setConfig(value); setKey(''); setDirty(false); clearResult();
      setFeedback({ message: '配置已保存，可以前往图片创作，也可按需检查模型能力。' });
      setAttempt(previous => previous + 1);
    } catch (err) {
      setFeedback({ message: err instanceof Error ? err.message : '保存失败', error: true });
    } finally { setBusy(''); }
  }
  async function readModels() {
    setBusy('models'); setModelFeedback(undefined);
    try {
      const value = key.trim()
        ? await readDraftModels({ name, base_url: url, api_key: key, model_name: '', model_names: [] })
        : await imageConfigRequest<ProbeResult>('/models', {});
      if (value.status !== 'ok') throw new Error(value.message);
      setCandidates(value.models);
      setModelFeedback({ message: '已读取 ' + value.models.length + ' 个模型，可搜索选择后添加。' });
    } catch (err) { setModelFeedback({ message: err instanceof Error ? err.message : '读取失败', error: true }); }
    finally { setBusy(''); }
  }
  async function connection() {
    setBusy('connection'); setConnectionFeedback(undefined);
    try {
      const value = key.trim()
        ? await testDraftConnection({ name, base_url: url, api_key: key, model_name: '', model_names: [] })
        : await imageConfigRequest<ConnectionResult>('/connection', {});
      setConnectionFeedback({ message: value.message, error: value.status !== 'ok' });
    } catch (err) { setConnectionFeedback({ message: err instanceof Error ? err.message : '连接失败', error: true }); }
    finally { setBusy(''); }
  }
  async function run(test: boolean) {
    setBusy(kind); setRunError(''); setOutput(''); setRunTime(''); setTaskId('');
    let knownRejection = false;
    const imageTest = kind === 'generate' || kind === 'edit';
    try {
      let reply: Response;
      if (!test && kind === 'text') {
        reply = await apiFetch('/api/image-configs/text', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt, model_name: model }),
          signal: AbortSignal.timeout(75000),
        });
      } else {
        const id = ids.current[kind] || crypto.randomUUID(); ids.current[kind] = id;
        const body = new FormData(); body.set('request_id', id); body.set('authorized', 'yes'); body.set('model_name', model);
        if (kind === 'edit' && reference) body.set('reference', reference);
        reply = await apiFetch('/api/image-configs/verify/' + kind, { method: 'POST', body, signal: AbortSignal.timeout(kind === 'vision' ? 200000 : 130000) });
      }
      knownRejection = reply.status >= 400 && reply.status < 500;
      const value = await reply.json();
      if (!reply.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '调用失败（HTTP ' + reply.status + '）');
      if (value.task_id) { setTaskId(value.task_id); setTaskPending(true); }
      else {
        setOutput(typeof value.output === 'string' ? value.output : JSON.stringify(value.output) || '');
        if (value.capability?.state !== 'supported') {
          setRunError(value.capability?.diagnostic?.response_body || value.capability?.message || '能力未确认');
        }
      }
      delete ids.current[kind]; setUncertain(false); setAttempt(previous => previous + 1);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : '调用失败');
      if (imageTest && !knownRejection) setUncertain(true);
      else { delete ids.current[kind]; setUncertain(false); }
    } finally { setRunTime(new Date().toLocaleString('zh-CN', { hour12: false })); setBusy(''); }
  }

  const locked = loading || !!loadError || !!busy || uncertain || taskPending;
  const ready = !!config?.has_api_key && !dirty && !loading && !loadError && !busy && !taskPending;
  const canInspectConnection = !locked && !!url.trim() && (!!key.trim() || (!!config?.has_api_key && url === config.base_url));
  const evidence = config?.model_settings?.[model]?.capabilities || (config?.model_name === model ? config.capabilities : {}) || {};
  const needsSave = dirty || !config;
  const checkHint = needsSave ? '请保存配置后再调用。' : !config?.has_api_key ? '请填写 API Key 并保存后再调用。' : '';
  const imageTest = kind === 'generate' || kind === 'edit';

  return <section className="model-connection-page">
    <header className="model-page-heading">
      <div><h2>个人模型配置</h2><p>连接服务商、添加模型，创作时直接选用。能力检查可按需进行。</p></div>
      <a className="button-secondary" href="#/studio">前往图片创作 ↗</a>
    </header>
    {loadError && <div className="feedback feedback-error" role="alert">配置读取失败：{loadError} <button type="button" className="button-secondary" onClick={() => { setLoading(true); setAttempt(previous => previous + 1); }}>重新读取</button></div>}
    {loading && <p role="status" className="model-muted">正在读取配置…</p>}

    <form onSubmit={save} className="model-setup-form">
      <section className="model-config-card" aria-labelledby="connection-heading">
        <header className="model-card-heading">
          <div className="model-section-title"><span className="model-section-index" aria-hidden="true">01</span><div><h3 id="connection-heading">接口连接</h3><p>同一连接下可添加多个模型，统一使用这里的地址与密钥。</p></div></div>
          <span className={'model-key-state ' + (config?.has_api_key ? 'is-ready' : '')}>{config?.has_api_key ? '密钥已就绪' : '待填写密钥'}</span>
        </header>
        <fieldset disabled={locked} className="model-card-body">
          <div className="model-credentials-grid">
            <div className="form-field"><label htmlFor="connection-name">连接名称</label><input id="connection-name" required value={name} onChange={event => { setName(event.target.value); change(); }} placeholder="例如：团队常用服务商" /></div>
            <div className="form-field"><label htmlFor="connection-url">接口地址 <span>Base URL</span></label><input id="connection-url" required type="url" value={url} onChange={event => { setUrl(event.target.value); setCandidates([]); change(); }} placeholder="https://api.example.com/v1" /></div>
            <div className="form-field"><label htmlFor="connection-key">API Key</label><input id="connection-key" type="password" autoComplete="off" value={key} placeholder={config?.has_api_key ? '留空沿用当前密钥' : '填写服务商密钥'} onChange={event => { setKey(event.target.value); change(); }} /></div>
          </div>
          <div className="model-connection-tools"><p className="model-muted">OpenAI 兼容协议 · 密钥仅在后端服务运行期间保管，重启后需重新填写。</p><button type="button" className="button-secondary" disabled={!canInspectConnection} onClick={() => void connection()}>{busy === 'connection' ? '连接测试中…' : '测试连接'}</button></div>
          {connectionFeedback && <p className={'feedback feedback-' + (connectionFeedback.error ? 'error' : 'success')} role={connectionFeedback.error ? 'alert' : 'status'}>{connectionFeedback.message}</p>}
          <details className="model-advanced"><summary>自定义图片接口路径 <span>通常无需修改</span></summary><div className="model-path-grid">
            <div className="form-field"><label htmlFor="generation-path">图片生成路径</label><input id="generation-path" value={generationPath} onChange={event => { setGenerationPath(event.target.value); change(); }} /></div>
            <div className="form-field"><label htmlFor="edit-path">图片编辑路径</label><input id="edit-path" value={editPath} onChange={event => { setEditPath(event.target.value); change(); }} /></div>
          </div></details>
        </fieldset>
      </section>

      <section className="model-config-card" aria-labelledby="models-heading">
        <header className="model-card-heading"><div className="model-section-title"><span className="model-section-index" aria-hidden="true">02</span><div><h3 id="models-heading">可用模型 <span className="model-count">{models.length}</span></h3><p>手动添加模型 ID，或读取服务商列表后选择。点击模型查看参数和能力；创作默认分工在下方单独设置。</p></div></div></header>
        <fieldset disabled={locked} className="model-card-body">
          <div className="form-field model-add-field"><label htmlFor="add-model">添加模型</label><div className="model-add-row"><input id="add-model" list="available-models" maxLength={200} value={added} onChange={event => setAdded(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); addModel(); } }} placeholder={candidates.length ? '搜索已读取的模型，或填写模型 ID' : '填写完整模型 ID'} /><button type="button" className="button-secondary" disabled={!added.trim()} onClick={addModel}>添加</button><button type="button" className="button-secondary" disabled={!canInspectConnection} onClick={() => void readModels()}>{busy === 'models' ? '读取中…' : '读取模型'}</button></div><datalist id="available-models">{candidates.map(id => <option key={id} value={id} />)}</datalist>{!canInspectConnection && !busy && <small>填写接口地址和 API Key 后即可读取模型，也可以直接手动添加。</small>}</div>
          {modelFeedback && <p className={'feedback feedback-' + (modelFeedback.error ? 'error' : 'success')} role={modelFeedback.error ? 'alert' : 'status'}>{modelFeedback.message}</p>}
          <div className="model-registered-list" aria-label="已添加的模型">{models.length ? models.map(id => <button type="button" key={id} className={'model-registered-item ' + (model === id ? 'is-selected' : '')} aria-pressed={model === id} onClick={() => choose(id)}><span aria-hidden="true" className="model-radio-dot" /><strong>{id}</strong>{model === id && <span className="model-default-tag">正在查看</span>}</button>) : <p className="model-empty">尚未添加模型。填写服务商提供的模型 ID 后点击“添加”。</p>}</div>
          {model && <details className="model-advanced"><summary>可选请求参数 <span>当前模型 · 未填写时采用服务商默认值</span></summary><p className="model-muted model-parameter-model">适用于 <strong>{model}</strong>，切换模型可分别配置。</p><div className="model-parameter-grid">{parameterFields.map(field => <div className="form-field" key={field.key}><label htmlFor={'params-' + field.key}>{field.label}</label><textarea id={'params-' + field.key} rows={5} spellCheck={false} value={params[field.key]} onChange={event => { setParams(previous => ({ ...previous, [field.key]: event.target.value })); change(); }} /><small>{field.hint}</small></div>)}</div></details>}
          <div className="model-review-option"><label><input type="checkbox" checked={autoReview} onChange={event => { setAutoReview(event.target.checked); change(); }} /><span>生成后自动看图质检 <small>可选</small></span></label><p>使用分析与策划模型检查生成图片，需具备图片理解能力；关闭时由人工检查。</p></div>
        </fieldset>
      </section>

      <section className="model-config-card" aria-labelledby="creation-defaults-heading">
        <header className="model-card-heading"><div><h3 id="creation-defaults-heading">创作默认设置</h3><p>同一服务商的两个模型可共用地址和密钥。这里的选择独立于上方正在查看的模型。</p></div></header>
        <fieldset disabled={locked} className="model-card-body model-path-grid">
          <div className="form-field"><label htmlFor="default-planner">分析与策划</label><select id="default-planner" value={planningModel} onChange={event => { setPlanningModel(event.target.value); change(); }}><option value="">新建任务时选择</option>{models.map(id => <option key={id} value={id}>{id}</option>)}</select><small>用于读取技能、分析产品、讨论卖点、编写图需和提示词。</small></div>
          <div className="form-field"><label htmlFor="default-image-model">图片制作</label><select id="default-image-model" value={imageModel} onChange={event => { setImageModel(event.target.value); change(); }}><option value="">制作图片时选择</option>{models.map(id => <option key={id} value={id}>{id}</option>)}</select><small>确认提示词后才调用；不按模型名称推断生图能力。</small></div>
        </fieldset>
      </section>
      <div className="model-save-bar"><p className={dirty ? 'model-draft-state' : 'model-muted'}>{dirty ? '有未保存的修改' : config ? '配置已保存' : '填写接口信息并添加模型后保存'}<small>保存不会调用模型，也不会自动验证能力。</small></p><button className="button-primary" disabled={locked}>{busy === 'save' ? '保存中…' : '保存配置'}</button></div>
      {feedback && <p className={'feedback feedback-' + (feedback.error ? 'error' : 'success')} role={feedback.error ? 'alert' : 'status'}>{feedback.message}</p>}
    </form>

    <section className="model-config-card model-check-card" aria-labelledby="checks-heading">
      <header className="model-card-heading"><div className="model-section-title"><span className="model-section-index" aria-hidden="true">03</span><div><h3 id="checks-heading">调用与能力检查 <span className="model-optional-tag">可选</span></h3><p>各项能力独立检查，未验证也可以使用模型。仅点击调用后请求服务商，可能计费。</p></div></div></header>
      <div className="model-card-body">
        <div className="model-check-target"><span>当前模型</span><strong>{model || '尚未选择模型'}</strong></div>
        <div className="model-capability-grid" role="tablist" aria-label="能力检查类型">{kinds.map(operation => {
          const state = evidence[operation]?.model === model ? evidence[operation]?.state : undefined;
          return <button type="button" key={operation} id={'check-tab-' + operation} role="tab" aria-selected={kind === operation} aria-controls="model-check-panel" disabled={!!busy || uncertain || taskPending} className={'model-capability-button ' + (kind === operation ? 'is-active' : '')} onClick={() => { setKind(operation); clearResult(); }}><span>{labels[operation]}</span><span className={'model-capability-state state-' + (state || 'unverified')}><i aria-hidden="true" />{stateLabel(state)}</span></button>;
        })}</div>
        <div id="model-check-panel" className="model-check-panel" role="tabpanel" aria-labelledby={'check-tab-' + kind}>
          <div className="model-check-description"><h4>{labels[kind]}</h4><p>{descriptions[kind]}</p></div>
          {kind === 'text' && <div className="form-field"><label htmlFor="model-text-input">文字内容</label><textarea id="model-text-input" rows={4} maxLength={16000} disabled={!!busy} value={prompt} onChange={event => setPrompt(event.target.value)} placeholder="输入文字，查看这个模型的实际回复…" /></div>}
          {kind === 'edit' && <div className="form-field model-reference-field"><label htmlFor="test-reference">测试参考图</label><input id="test-reference" type="file" disabled={!!busy || uncertain || taskPending} accept="image/png,image/jpeg,image/webp" onChange={event => { setReference(event.target.files?.[0]); setAuthorized(false); }} /><small>{reference ? '已选择：' + reference.name : '支持 PNG、JPEG、WebP。请选择已授权上传至该服务商的图片。'}</small></div>}
          {imageTest && <label className="model-check-consent"><input type="checkbox" disabled={!!busy || taskPending} checked={authorized} onChange={event => setAuthorized(event.target.checked)} /><span>允许向当前服务商提交本次图片测试{kind === 'edit' ? '及参考图' : ''}，可能产生模型费用。</span></label>}
          <div className="model-check-actions">{kind === 'text' && <button type="button" className="button-primary" disabled={!ready || !model || !prompt.trim()} onClick={() => void run(false)}>{busy === 'text' ? '调用中…' : '发送文字'}</button>}<button type="button" className={kind === 'text' ? 'button-secondary' : 'button-primary'} disabled={!ready || !model || (imageTest && (!authorized || (kind === 'edit' && !reference)))} onClick={() => void run(true)}>{busy === kind ? '调用中…' : taskPending ? '测试进行中…' : uncertain ? '重发同一验证请求' : kind === 'text' ? '快速检查文字能力' : '检查' + labels[kind] + '能力'}</button>{checkHint && <span>{checkHint}</span>}</div>
          {uncertain && <p className="feedback feedback-warning">提交结果待确认，请先核对生成记录和服务商状态；重发会复用本次请求标识。</p>}
          {(output || runError || taskId || busy === kind) && <section className="model-call-result" aria-label="本次调用结果"><header><h4>本次调用结果</h4>{runTime && !taskId && <time>{runTime}</time>}</header>{busy === kind && <p className="model-muted" role="status">等待服务商返回…</p>}{runError && <pre className="model-response-error" role="alert">{runError}</pre>}{output && <pre className="model-response-text">{output}</pre>}{taskId && <ImageVerificationResult key={taskId} taskId={taskId} onFinished={() => { setTaskPending(false); setAttempt(previous => previous + 1); }} />}</section>}
        </div>
      </div>
    </section>
  </section>;
}
