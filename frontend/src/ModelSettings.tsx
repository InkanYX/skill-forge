import { useEffect, useRef, useState, type FormEvent } from 'react';
import { listConfigs, saveConfig, testConfig, type ConfigDraft, type ModelConfig, type ProbeResult } from './modelConfigApi';

const emptyDraft = (): ConfigDraft => ({ name: '我的模型接口', base_url: '', api_key: '', model_name: '' });
const messageOf = (error: unknown) => error instanceof Error ? error.message : '操作失败，请检查后端连接。';

export default function ModelSettings() {
  const [configs, setConfigs] = useState<ModelConfig[]>([]);
  const [selected, setSelected] = useState<string>();
  const [draft, setDraft] = useState<ConfigDraft>(emptyDraft);
  const [models, setModels] = useState<string[]>([]);
  const [result, setResult] = useState<ProbeResult>();
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState<'load' | 'save' | 'test' | null>('load');
  const [dirty, setDirty] = useState(false);
  const mounted = useRef(true);
  const active = configs.find((item) => item.id === selected);

  useEffect(() => {
    mounted.current = true;
    listConfigs().then((items) => { if (mounted.current) setConfigs(items); })
      .catch((err: unknown) => { if (mounted.current) setError(messageOf(err)); })
      .finally(() => { if (mounted.current) setBusy(null); });
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    const handler = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault(); };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  function change(field: keyof ConfigDraft, value: string) {
    setDraft((previous) => ({ ...previous, [field]: value }));
    setDirty(true);
    setNotice('');
    if (field === 'base_url' || field === 'api_key') { setResult(undefined); setModels([]); }
  }

  function selectConfig(id?: string) {
    if (dirty && !window.confirm('当前修改尚未保存，确定切换配置吗？')) return;
    const item = configs.find((config) => config.id === id);
    setSelected(id);
    setDraft(item ? { name: item.name, base_url: item.base_url, model_name: item.model_name, api_key: '' } : emptyDraft());
    setDirty(false); setModels([]); setResult(undefined); setError(''); setNotice('');
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    setBusy('save'); setError(''); setNotice('');
    try {
      const item = await saveConfig(draft, selected);
      if (!mounted.current) return;
      setConfigs((items) => [...items.filter((config) => config.id !== item.id), item]);
      setSelected(item.id);
      setDraft({ name: item.name, base_url: item.base_url, model_name: item.model_name, api_key: '' });
      setDirty(false); setNotice('配置已保存。密钥已加密存储，页面不回显。');
    } catch (err) { if (mounted.current) setError(messageOf(err)); }
    finally { if (mounted.current) setBusy(null); }
  }

  async function handleTest() {
    if (!draft.base_url.trim() || (!draft.api_key.trim() && !active?.has_api_key)) {
      setError('请先填写接口地址与 API Key。'); return;
    }
    setBusy('test'); setError(''); setNotice(''); setResult(undefined); setModels([]);
    try {
      const value = await testConfig(draft, selected);
      if (!mounted.current) return;
      setResult(value); setModels(value.models);
    } catch (err) { if (mounted.current) setError(messageOf(err)); }
    finally { if (mounted.current) setBusy(null); }
  }

  return <section className="model-settings" aria-labelledby="model-settings-heading">
    <div className="section-heading"><div><p className="eyebrow">YOUR MODEL CONNECTIONS</p><h2 id="model-settings-heading">个人模型配置</h2></div><button className="button-secondary" disabled={busy !== null} onClick={() => selectConfig()}>新建配置</button></div>
    <p className="settings-intro">填写服务商地址和自己的密钥，保存后用于后续图片制作。当前支持 OpenAI 兼容的模型列表查询。</p>
    <div className="settings-layout">
      <aside className="config-list" aria-label="已保存的接口配置">
        <div className="list-title">已保存的配置 <span>{configs.length}</span></div>
        {busy === 'load' && <p className="empty-config">正在读取配置…</p>}
        {busy !== 'load' && configs.length === 0 && <p className="empty-config">还没有接口配置。<br />填写右侧信息即可保存。</p>}
        {configs.map((item) => <button key={item.id} type="button" className={`config-item ${selected === item.id ? 'config-item-active' : ''}`} disabled={busy !== null} onClick={() => selectConfig(item.id)}><strong>{item.name}</strong><span>{item.base_url}</span><small>{item.model_name || '尚未指定模型'}</small></button>)}
      </aside>
      <form className="config-form" onSubmit={handleSave}>
        <fieldset disabled={busy !== null}>
          <legend>{active ? '编辑接口配置' : '新建接口配置'}</legend>
          <div className="form-field"><label htmlFor="config-name">配置名称</label><input id="config-name" value={draft.name} maxLength={80} required onChange={(event) => change('name', event.target.value)} placeholder="例如：我的图片服务" /></div>
          <div className="form-field"><label htmlFor="base-url">接口地址 <span>Base URL</span></label><input id="base-url" type="url" value={draft.base_url} maxLength={2048} required onChange={(event) => change('base_url', event.target.value)} placeholder="https://api.example.com/v1" aria-describedby="base-url-help" /><small id="base-url-help">填写服务商提供的公开 HTTPS 基础地址。支持 /v1 等自定义前缀，不要填写 /responses 等具体接口。</small></div>
          <div className="form-field"><label htmlFor="api-key">API Key {active?.has_api_key && <span className="saved-key">已保存</span>}</label><input id="api-key" type="password" autoComplete="new-password" spellCheck={false} maxLength={4096} value={draft.api_key} required={!active?.has_api_key} onChange={(event) => change('api_key', event.target.value)} placeholder={active?.has_api_key ? '留空保留原密钥；输入新值可替换' : '填写你的服务商密钥'} aria-describedby="api-key-help" /><small id="api-key-help">密钥仅发往本机后端与指定服务商，不写入浏览器本地存储。更改接口地址时需要重新填写密钥。</small></div>
          <div className="form-field"><label htmlFor="model-name">模型名称 <span>可手动填写</span></label><input id="model-name" list="provider-models" maxLength={200} value={draft.model_name} onChange={(event) => change('model_name', event.target.value)} placeholder="测试连接后选择，或填写服务商给出的模型 ID" /><datalist id="provider-models">{models.map((model) => <option key={model} value={model} />)}</datalist><small>模型列表不支持查询时，也可以手动填写。保存配置不代表模型已经通过生图验证。</small></div>
        </fieldset>
        {error && <div className="feedback feedback-error" role="alert">{error}</div>}
        {result && <div className={`feedback feedback-${result.status === 'ok' ? 'success' : result.status === 'error' ? 'error' : 'warning'}`} role="status"><strong>{result.status === 'ok' ? `已读取 ${result.models.length} 个模型` : result.status === 'unsupported' ? '需要手动配置模型' : '连接测试未通过'}</strong><p>{result.message}</p></div>}
        {models.length > 0 && <div className="model-picker" aria-label="选择服务商模型">{models.slice(0, 24).map((model) => <button type="button" key={model} title={model} disabled={busy !== null} className={draft.model_name === model ? 'model-selected' : ''} onClick={() => change('model_name', model)}>{model}</button>)}{models.length > 24 && <small>更多模型可在上方输入框搜索选择。</small>}</div>}
        {notice && <div className="feedback feedback-success" role="status">{notice}</div>}
        <div className="form-actions"><button type="button" className="button-secondary" disabled={busy !== null} onClick={handleTest}>{busy === 'test' ? '正在测试…' : '测试连接 / 读取模型'}</button><button className="button-primary" type="submit" disabled={busy !== null}>{busy === 'save' ? '正在保存…' : '保存配置'}</button></div>
        <p className="form-footnote">连接测试仅请求模型列表，不发送图片、不执行生图。配置保存在本机；团队账号与权限将在后续接入。</p>
      </form>
    </div>
  </section>;
}
