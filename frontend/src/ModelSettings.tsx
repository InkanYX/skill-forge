import { useEffect, useRef, useState, type FormEvent } from 'react';
import { listConfigs, saveConfig, testConfig, readModels, type ConfigDraft, type ModelConfig, type ProbeResult, type ConnectionResult } from './modelConfigApi';

const emptyDraft = (): ConfigDraft => ({ name: '我的模型接口', base_url: '', api_key: '', model_name: '', model_names: [] });
const messageOf = (error: unknown) => error instanceof Error ? error.message : '操作失败，请检查后端连接。';

export default function ModelSettings() {
  const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [selected, setSelected] = useState<string>();
  const [draft, setDraft] = useState<ConfigDraft>(emptyDraft);
  const [models, setModels] = useState<string[]>([]);
  const [manualModel, setManualModel] = useState('');
  const [modelSearch, setModelSearch] = useState('');
  const [result, setResult] = useState<ProbeResult>();
  const [connectionResult, setConnectionResult] = useState<ConnectionResult>();
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState<'load' | 'save' | 'test' | 'models' | null>('load');
  const [dirty, setDirty] = useState(false);
  const mounted = useRef(true);
  const active = configs.find((item) => item.id === selected);

  useEffect(() => {
    mounted.current = true;
    listConfigs().then((items) => {
      if (!mounted.current) return;
      setConfigs(items);
      const item = items[0];
      if (item) {
        setSelected(item.id);
        setDraft({ name: item.name, base_url: item.base_url, model_name: item.model_name, model_names: item.model_names, api_key: '' });
      }
    })
      .catch((err: unknown) => { if (mounted.current) setError(messageOf(err)); })
      .finally(() => { if (mounted.current) setBusy(null); });
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  function change(field: Exclude<keyof ConfigDraft, 'model_names'>, value: string) {
    setDraft((previous) => ({ ...previous, [field]: value }));
    setDirty(true);
    setNotice('');
    if (field === 'base_url' || field === 'api_key') { setResult(undefined); setConnectionResult(undefined); setModels([]); }
  }

  function chooseModels(names: string[]) {
    setDraft(previous => ({ ...previous, model_names: names, model_name: names.includes(previous.model_name) ? previous.model_name : names[0] || '' }));
    setDirty(true); setNotice(''); setError('');
  }

  function toggleModel(name: string) {
    if (!draft.model_names.includes(name) && draft.model_names.length >= 50) { setError('每份配置最多保存 50 个模型。'); return; }
    chooseModels(draft.model_names.includes(name) ? draft.model_names.filter(model => model !== name) : [...draft.model_names, name]);
  }

  function addManualModel() {
    const name = manualModel.trim();
    if (!name) return;
    if (name.length > 200) { setError('模型 ID 最多 200 字符。'); return; }
    if (!draft.model_names.includes(name)) {
      if (draft.model_names.length >= 50) { setError('每份配置最多保存 50 个模型。'); return; }
      chooseModels([...draft.model_names, name]);
    }
    setManualModel('');
  }

  function selectConfig(id: string) {
    if (dirty && !window.confirm('当前修改尚未保存，确定切换配置吗？')) return;
    const item = configs.find((config) => config.id === id);
    setSelected(id);
    setDraft(item ? { name: item.name, base_url: item.base_url, model_name: item.model_name, model_names: item.model_names, api_key: '' } : emptyDraft());
    setDirty(false); setModels([]); setManualModel(''); setModelSearch(''); setResult(undefined); setConnectionResult(undefined); setError(''); setNotice('');
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    const names = [...new Set([...draft.model_names, ...(manualModel.trim() ? [manualModel.trim()] : [])])];
    if (!names.length) { setError('请至少选择或添加一个模型。'); return; }
    if (names.length > 50) { setError('每份配置最多保存 50 个模型。'); return; }
    setBusy('save'); setError(''); setNotice('');
    try {
      const item = await saveConfig({ ...draft, model_names: names, model_name: draft.model_name || names[0] }, selected);
      if (!mounted.current) return;
      setConfigs((items) => [...items.filter((config) => config.id !== item.id), item]);
      setSelected(item.id);
      setDraft({ name: item.name, base_url: item.base_url, model_name: item.model_name, model_names: item.model_names, api_key: '' });
      setManualModel(''); setDirty(false); setNotice(`配置已保存，${item.model_names.length} 个模型可在创作页面选择。密钥已加密存储，页面不回显。`);
    } catch (err) { if (mounted.current) setError(messageOf(err)); }
    finally { if (mounted.current) setBusy(null); }
  }

  async function handleProbe(action: 'test' | 'models') {
    if (busy !== null) return;
    if (!draft.base_url.trim() || (!draft.api_key.trim() && !active?.has_api_key)) {
      setError('请先填写接口地址与 API Key。'); return;
    }
    setBusy(action); setError(''); setNotice('');
    if (action === 'test') setConnectionResult(undefined);
    else { setResult(undefined); setModels([]); }
    try {
      if (action === 'test') {
        const value = await testConfig(draft, selected);
        if (mounted.current) setConnectionResult(value);
      } else {
        const value = await readModels(draft, selected);
        if (mounted.current) { setResult(value); setModels(value.models); }
      }
    } catch (err) { if (mounted.current) setError(messageOf(err)); }
    finally { if (mounted.current) setBusy(null); }
  }

  return <section className="model-settings" aria-labelledby="model-settings-heading">
    <div className="section-heading"><div><p className="eyebrow">YOUR MODEL CONNECTIONS</p><h2 id="model-settings-heading">个人模型配置</h2></div></div>
    <p className="settings-intro">一份服务商地址和 API Key 可以保存多个图片模型。勾选需要使用的模型并设定默认模型，制作页面直接选择即可。</p>
    <div className="settings-layout">
      <aside className="config-list" aria-label="已保存的接口配置">
        <div className="list-title">已保存的配置 <span>{configs.length}</span></div>
        {busy === 'load' && <p className="empty-config">正在读取配置…</p>}
        {busy !== 'load' && configs.length === 0 && <p className="empty-config">还没有接口配置。<br />填写右侧信息即可保存。</p>}
        {configs.map((item) => <button key={item.id} type="button" className={`config-item ${selected === item.id ? 'config-item-active' : ''}`} disabled={busy !== null} onClick={() => selectConfig(item.id)}><strong>{item.name}</strong><span>{item.base_url}</span><small>{item.model_names.length} 个模型 · 默认：{item.model_name || '未设置'}</small></button>)}
      </aside>
      <form className="config-form" onSubmit={handleSave}>
        <fieldset disabled={busy !== null}>
          <legend>接口配置</legend>
          <div className="form-field"><label htmlFor="config-name">配置名称</label><input id="config-name" value={draft.name} maxLength={80} required onChange={(event) => change('name', event.target.value)} placeholder="例如：我的图片服务" /></div>
          <div className="form-field"><label htmlFor="base-url">接口地址 <span>Base URL</span></label><input id="base-url" type="url" value={draft.base_url} maxLength={2048} required onChange={(event) => change('base_url', event.target.value)} placeholder="https://api.example.com/v1" aria-describedby="base-url-help" /><small id="base-url-help">填写服务商提供的公开 HTTPS 基础地址。支持 /v1 等自定义前缀，不要填写 /responses 等具体接口。</small></div>
          <div className="form-field"><label htmlFor="api-key">API Key {active?.has_api_key && <span className="saved-key">已保存</span>}</label><input id="api-key" type="password" autoComplete="new-password" spellCheck={false} maxLength={4096} value={draft.api_key} required={!active?.has_api_key} onChange={(event) => change('api_key', event.target.value)} placeholder={active?.has_api_key ? '留空保留原密钥；输入新值可替换' : '填写你的服务商密钥'} aria-describedby="api-key-help" /><small id="api-key-help">密钥仅发往本机后端与指定服务商，不写入浏览器本地存储。更改接口地址时需要重新填写密钥。</small></div>
          <div className="form-field"><label htmlFor="model-name">添加模型 <span>可添加多个</span></label><div className="input-with-action"><input id="model-name" maxLength={200} value={manualModel} onChange={event => { setManualModel(event.target.value); setDirty(true); }} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); addManualModel(); } }} placeholder="输入服务商给出的模型 ID，再点击添加" /><button type="button" className="button-secondary" disabled={!manualModel.trim()} onClick={addManualModel}>添加</button></div><small>可以逐个手动添加，也可以读取服务商模型列表后多选。仅添加支持图片生成或编辑的模型。</small></div>
          <div className="configured-models"><h3>已选模型 · {draft.model_names.length} / 50</h3>{draft.model_names.length ? <div className="model-picker">{draft.model_names.map(name => <button key={name} type="button" onClick={() => toggleModel(name)} aria-label={`移除模型 ${name}`}>{name} ×</button>)}</div> : <p className="form-footnote">尚未添加模型。</p>}</div>
          {!!draft.model_names.length && <div className="form-field"><label htmlFor="default-model">默认模型</label><select id="default-model" value={draft.model_name} onChange={event => change('model_name', event.target.value)}>{draft.model_names.map(name => <option key={name} value={name}>{name}</option>)}</select><small>创作时仍可切换到其他已选模型。</small></div>}
        </fieldset>
        {error && <div className="feedback feedback-error" role="alert">{error}</div>}
        {connectionResult && <div className={`feedback feedback-${connectionResult.status === 'ok' ? 'success' : connectionResult.status === 'error' ? 'error' : 'warning'}`} role="status"><strong>{connectionResult.status === 'ok' ? '连接测试通过' : connectionResult.status === 'unsupported' ? '连接验证受限' : '连接测试未通过'}</strong><p>{connectionResult.message}</p></div>}
        {result && <div className={`feedback feedback-${result.status === 'ok' ? 'success' : result.status === 'error' ? 'error' : 'warning'}`} role="status"><strong>{result.status === 'ok' ? `已读取 ${result.models.length} 个模型` : result.status === 'unsupported' ? '需要手动添加模型' : '模型列表读取失败'}</strong><p>{result.message}</p></div>}
        {models.length > 0 && <section className="provider-models"><div className="form-field"><label htmlFor="model-search">服务商模型列表 · 可多选</label><input id="model-search" value={modelSearch} onChange={event => setModelSearch(event.target.value)} placeholder="搜索模型 ID" /></div><div className="model-picker" aria-label="选择服务商模型">{models.filter(name => name.toLowerCase().includes(modelSearch.trim().toLowerCase())).map(model => <button type="button" key={model} title={model} aria-pressed={draft.model_names.includes(model)} disabled={busy !== null} className={draft.model_names.includes(model) ? 'model-selected' : ''} onClick={() => toggleModel(model)}>{draft.model_names.includes(model) ? '✓ ' : ''}{model}</button>)}</div>{!models.some(name => name.toLowerCase().includes(modelSearch.trim().toLowerCase())) && <p className="form-footnote">没有匹配的模型，也可以在上方手动添加。</p>}</section>}
        {notice && <div className="feedback feedback-success" role="status">{notice}</div>}
        <div className="form-actions"><button type="button" className="button-secondary" disabled={busy !== null} onClick={() => handleProbe('test')}>{busy === 'test' ? '正在测试…' : '测试连接'}</button><button type="button" className="button-secondary" disabled={busy !== null} onClick={() => handleProbe('models')}>{busy === 'models' ? '正在读取…' : '读取模型'}</button><button className="button-primary" type="submit" disabled={busy !== null}>{busy === 'save' ? '正在保存…' : '保存配置'}</button></div>
        <p className="form-footnote">测试连接只检查接口响应，不加载模型列表；读取模型单独获取可选列表。两者均不发送图片、不执行生图，也不会自动保存配置。</p>
      </form>
    </div>
  </section>;
}
