import { apiFetch } from './apiFetch';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { imageConfigRequest, type ImageConfiguration } from './imageConfigApi';
import { listConfigs, type ModelConfig, type ProbeResult, type ConnectionResult } from './modelConfigApi';
import { formatTaskTime } from './imageTaskApi';
import ImageVerificationResult from './ImageVerificationResult';
import { startTaskPolling } from './taskPolling';

type CheckKind='connection'|'generate'|'edit';
const checkNames:Record<CheckKind,string>={connection:'连接检查',generate:'图片生成',edit:'参考图编辑'};
const activeStatus=(status?:string)=>status==='queued'||status==='running';
const capabilityLabel=(status?:string)=>status==='succeeded'?'已通过':status==='failed'?'失败':status==='unknown'?'待确认':activeStatus(status)?'验证中':status==='cancelled'?'已取消':'未验证';

export default function ImageSettings(){
  const [config,setConfig]=useState<ImageConfiguration|null>(null);
  const [name,setName]=useState('我的模型服务');const [url,setUrl]=useState('https://ai-gateway.valsun.cn/v1');const [key,setKey]=useState('');
  const [connections,setConnections]=useState<ModelConfig[]>([]);
  const [textConfigId,setTextConfigId]=useState('');const [textModel,setTextModel]=useState('');const [visionModel,setVisionModel]=useState('');
  const [candidates,setCandidates]=useState<string[]>([]);const [modelMessage,setModelMessage]=useState('');const [modelError,setModelError]=useState('');
  const [loading,setLoading]=useState(true);const [busy,setBusy]=useState('');const [dirty,setDirty]=useState(false);
  const [loadError,setLoadError]=useState('');const [saveError,setSaveError]=useState('');const [saved,setSaved]=useState(false);
  const [selected,setSelected]=useState<CheckKind>('connection');
  const [connection,setConnection]=useState<ConnectionResult & {time:string}>();const [connectionError,setConnectionError]=useState('');
  const [reference,setReference]=useState<File>();const [referencePreview,setReferencePreview]=useState('');
  const [authorized,setAuthorized]=useState(false);const [submitErrors,setSubmitErrors]=useState<Record<string,string>>({});
  const [ambiguous,setAmbiguous]=useState<Partial<Record<CheckKind,boolean>>>({});
  const [tasks,setTasks]=useState<Partial<Record<CheckKind,string>>>({});const [attempt,setAttempt]=useState(0);
  const requests=useRef<Partial<Record<CheckKind,string>>>({});const dirtyRef=useRef(dirty);dirtyRef.current=dirty;
  const fileInput=useRef<HTMLInputElement>(null);
  useEffect(()=>{
    const current=startTaskPolling<ImageConfiguration|null>({
      load:async signal=>{const response=await apiFetch('/api/image-configs',{signal,cache:'no-store'});const value=await response.json();if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'图片配置读取失败。');return value;},
      pending:value=>!!value&&[value.generation.status,value.edit.status].some(activeStatus),
      onData:value=>{setConfig(value);setLoadError('');if(!dirtyRef.current&&value){setName(value.name);setUrl(value.base_url);setTextConfigId(value.text_config_id||'');setTextModel(value.text_model_name||'');setVisionModel(value.vision_model_name||'');}},
      onError:err=>setLoadError(err instanceof Error?err.message:'配置读取失败。'),onLoading:setLoading,
    });return()=>current.stop();
  },[attempt]);
  useEffect(()=>{let active=true;listConfigs().then(items=>{if(active)setConnections(items);}).catch(()=>{if(active)setModelError('已有服务商连接读取失败，可刷新页面重试。');});return()=>{active=false;};},[]);
  useEffect(()=>{const unload=(event:BeforeUnloadEvent)=>{if(dirty)event.preventDefault();};window.addEventListener('beforeunload',unload);return()=>window.removeEventListener('beforeunload',unload);},[dirty]);
  useEffect(()=>{if(!reference){setReferencePreview('');return;}const value=URL.createObjectURL(reference);setReferencePreview(value);return()=>URL.revokeObjectURL(value);},[reference]);
  function changeDraft(){setDirty(true);setSaved(false);setSaveError('');setAuthorized(false);setConnection(undefined);setConnectionError('');}
  const submissionUnclear=Object.values(ambiguous).some(Boolean);
  async function save(event:FormEvent){
    event.preventDefault();if(busy||submissionUnclear)return;setBusy('save');setSaveError('');setSaved(false);
    try{const value=await imageConfigRequest<ImageConfiguration>('',{name,base_url:url,api_key:key||null,text_model_name:textModel,vision_model_name:visionModel,text_config_id:textConfigId||null});setConfig(value);setKey('');setDirty(false);setSaved(true);setConnection(undefined);setConnectionError('');setAuthorized(false);setTasks({});setSubmitErrors({});requests.current={};setAttempt(v=>v+1);}
    catch(err){setSaveError(err instanceof Error?err.message:'保存失败。');}finally{setBusy('');}
  }
  async function readTextModels(){
    if(busy)return;setBusy('models');setModelError('');setModelMessage('');
    try{const value=await imageConfigRequest<ProbeResult>('/models',{text_config_id:textConfigId||null});
      if(value.status==='ok'){setCandidates(value.models);setModelMessage(`已读取 ${value.models.length} 个模型，可选择或手动填写。`);}
      else setModelError(value.message);
    }catch(err){setModelError(err instanceof Error?err.message:'模型列表读取失败。');}finally{setBusy('');}
  }
  async function testConnection(){
    if(busy)return;setBusy('connection');setConnection(undefined);setConnectionError('');
    try{const result=await imageConfigRequest<ConnectionResult>('/connection',{});setConnection({...result,time:new Date().toISOString()});}
    catch(err){setConnectionError(err instanceof Error?err.message:'连接检查失败。');}finally{setBusy('');}
  }
  async function verify(kind:'generate'|'edit'){
    if(busy)return;setBusy(kind);setSubmitErrors(previous=>({...previous,[kind]:''}));
    const id=requests.current[kind]||crypto.randomUUID();requests.current[kind]=id;
    const body=new FormData();body.set('request_id',id);body.set('authorized','yes');if(kind==='edit'&&reference)body.set('reference',reference);
    let knownFailure=false;
    try{
      const response=await apiFetch(`/api/image-configs/verify/${kind}`,{method:'POST',body,signal:AbortSignal.timeout(30000)});
      knownFailure=response.status>=400&&response.status<500;
      const value=await response.json();
      if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'验证请求未完成，请检查配置和参考图。');
      setTasks(previous=>({...previous,[kind]:value.task_id}));delete requests.current[kind];setAmbiguous(previous=>({...previous,[kind]:false}));setAttempt(v=>v+1);
    }catch(err){setAmbiguous(previous=>({...previous,[kind]:!knownFailure}));setSubmitErrors(previous=>({...previous,[kind]:`${err instanceof Error?err.message:'验证提交失败。'}${knownFailure?'':' 提交结果无法确认，请先核对任务记录；重发将复用同一提交标识。'}`}));}
    finally{setBusy('');}
  }
  const usable=!!config?.has_api_key&&!dirty&&!busy&&!loadError;
  const ready=!!config?.has_api_key&&!dirty;
  const readiness=dirty?'配置有修改':!config?'尚未配置':!config.has_api_key?'需要填写密钥':'配置已保存，可直接创作';
  const result=selected==='generate'?config?.generation:selected==='edit'?config?.edit:undefined;
  const taskId=selected==='connection'?undefined:tasks[selected]||result?.task_id;
  const disabledReason=loadError?'请先重新读取配置。':!config?'请先保存接口信息。':dirty?'配置尚未保存，请先保存修改。':!config.has_api_key?'请重新填写并保存 API Key。':'';
  const busyVerification=activeStatus(result?.status);
  const alternate=connections.find(item=>item.id===textConfigId);
  const textModels=[...new Set([...candidates,...(alternate?.model_names||[]),textModel].filter(value=>!!value&&!value.startsWith('gpt-image-')))];
  return <section className="image-settings settings-redesign">
    <div className="settings-image-heading"><div><h2>模型配置</h2><p>连接服务商，再设置图片与文字用途的模型。同一服务商共用地址和密钥。</p></div><a href="#/studio" className={ready?'button-primary':'button-secondary'}>前往图片创作 ↗</a></div>
    <div className={`settings-readiness ${ready?'settings-readiness-ready':''}`} role="status"><span className="settings-readiness-dot"/><strong>{loading&&!config?'读取配置中…':readiness}</strong><div className="settings-capability-statuses">{([{label:"图片生成",status:config?.generation.status},{label:"参考图编辑",status:config?.edit.status}]).map(item=><span key={item.label} className={`settings-capability capability-${item.status||"unverified"}`}><span>{item.label}</span><b>{capabilityLabel(item.status)}</b></span>)}</div></div>
    {loadError&&<div className="settings-feedback settings-feedback-error" role="alert"><strong>配置读取失败</strong><p>{loadError}</p><button type="button" className="button-secondary" onClick={()=>setAttempt(v=>v+1)}>重新读取配置</button></div>}
    <div className="settings-image-layout">
      <section className="settings-surface settings-credentials" aria-labelledby="image-credentials-title"><header className="settings-surface-heading"><span className="settings-section-number">01</span><div><h3 id="image-credentials-title">服务商连接</h3><p>地址和密钥填写一次，按模型用途复用。</p></div>{dirty&&<span className="settings-unsaved">未保存</span>}</header>
        <form onSubmit={save}><fieldset disabled={loading&&!config||!!busy||submissionUnclear}>
          <div className="form-field"><label htmlFor="image-config-name">配置名称</label><input id="image-config-name" value={name} required maxLength={80} onChange={e=>{setName(e.target.value);changeDraft();}} /></div>
          <div className="form-field"><label htmlFor="image-base-url">接口地址 <span>Base URL</span></label><input id="image-base-url" value={url} required type="url" spellCheck={false} onChange={e=>{setUrl(e.target.value);changeDraft();}} /><small>填写基础地址（通常以 /v1 结尾），无需添加生图路径。</small></div>
          <div className="form-field"><div className="settings-field-label"><label htmlFor="image-api-key">API Key</label><span className={config?.has_api_key?'settings-key-ready':'settings-key-missing'}>{config?.has_api_key?'当前密钥可用':'尚未提供密钥'}</span></div><input id="image-api-key" type="password" autoComplete="off" value={key} placeholder={config?.has_api_key?'留空继续使用当前密钥':'粘贴此服务商的 API Key'} onChange={e=>{setKey(e.target.value);changeDraft();}} /><small>密钥仅保留在服务内存，服务重启后需重新填写。</small></div>
        <section className="settings-purpose-models" aria-labelledby="purpose-models-title"><h3 id="purpose-models-title">模型设置</h3>
          <div className="settings-purpose-image"><div className="settings-purpose-heading"><strong>图片生成与编辑</strong><span>固定规则</span></div><code>gpt-image-2.5-sunburst</code><div className="settings-purpose-tags"><span>high</span><span>auto</span><span>PNG</span></div><small>使用当前服务商连接，沿用标准生图规则。</small></div>
          <div className="settings-purpose-text"><div className="settings-purpose-heading"><strong>文字分析</strong><span>按需设置</span></div>
            <div className="form-field"><label htmlFor="text-model-connection">使用的服务商连接</label><select id="text-model-connection" value={textConfigId} onChange={event=>{const id=event.target.value;const existing=connections.find(item=>item.id===id);setTextConfigId(id);setTextModel(existing?.model_name||'');setCandidates([]);setModelMessage('');setModelError('');changeDraft();}}><option value="">共用当前服务商连接</option>{connections.map(item=><option key={item.id} value={item.id}>{item.name} · {item.base_url}</option>)}</select><small>{textConfigId?`沿用已有连接：${alternate?.base_url||'连接不存在，请重新选择'}。地址和密钥保持不变。`:'与图片生成共用已填写的 Base URL 和 API Key，无需重复配置。'}</small></div>
            <div className="form-field"><label htmlFor="text-purpose-model">文字模型</label><div className="input-with-action"><input id="text-purpose-model" list="text-model-options" maxLength={200} value={textModel} placeholder="选择或输入文字模型 ID" onChange={event=>{setTextModel(event.target.value);changeDraft();}} /><button type="button" className="button-secondary" disabled={!!busy||(!textConfigId&&(!config?.has_api_key||url!==config.base_url||!!key))} onClick={()=>void readTextModels()}>{busy==='models'?'读取中…':'读取模型'}</button></div><datalist id="text-model-options">{textModels.map(model=><option key={model} value={model}/>)}</datalist><small>可留空，后续用于文字分析、策划与提示词功能。</small></div>
<div className="form-field"><label htmlFor="vision-purpose-model">视觉模型（Agent 质检）</label><div className="input-with-action"><input id="vision-purpose-model" list="vision-model-options" maxLength={200} value={visionModel} placeholder="选择或输入支持图片输入的模型 ID" onChange={event=>{setVisionModel(event.target.value);changeDraft();}} /><button type="button" className="button-secondary" disabled={!!busy||(!textConfigId&&(!config?.has_api_key||url!==config.base_url||!!key))} onClick={()=>void readTextModels()}>{busy==='models'?'读取中…':'读取模型'}</button></div><datalist id="vision-model-options">{textModels.map(model=><option key={model} value={model}/>)}</datalist><small>{visionModel?'视觉模型将用于 Agent 出图后的自动质检。':'可留空；不填则 Agent 只能以“待人工审核”结束。'}</small></div>
            {modelMessage&&<p className="settings-model-message" role="status">{modelMessage}</p>}{modelError&&<p className="settings-model-error" role="alert">{modelError}</p>}
          </div>
        </section>
        </fieldset>
        <div className="settings-save-row"><button type="submit" className="button-primary" disabled={!!busy||loading&&!config||submissionUnclear}>{busy==='save'?'正在保存…':'保存模型配置'}</button>{config&&!dirty&&!saved&&<span>已保存 · {formatTaskTime(config.updated_at)}</span>}</div>
        {saveError&&<div className="settings-feedback settings-feedback-error" role="alert"><strong>保存失败</strong><p>{saveError}</p></div>}{saved&&<div className="settings-feedback settings-feedback-success" role="status"><strong>模型配置已保存</strong><p>可直接开始创作，也可按需检查连接和图片能力。</p></div>}
        </form>
        <details className="settings-rule-details"><summary>查看生图执行规则</summary><p>提示词保存原文并提交；有参考图时调用编辑接口。每张独立执行，失败不自动重试，保留原生图与调用记录。</p></details>
      </section>
      <section className="settings-surface settings-validation" aria-labelledby="image-validation-title"><header className="settings-surface-heading"><span className="settings-section-number">02</span><div><h3 id="image-validation-title">接口检查 <span className="settings-optional-label">可选</span></h3><p>用于排查问题，不影响直接创作。</p></div></header>
        <div className="settings-check-tabs" role="tablist" aria-label="图片接口检查类型">{(['connection','generate','edit'] as const).map(kind=><button type="button" role="tab" key={kind} id={`check-tab-${kind}`} aria-controls={`check-panel-${kind}`} aria-selected={selected===kind} onClick={()=>setSelected(kind)}>{checkNames[kind]}<span className={`settings-check-dot ${kind==='connection'?(connection?.status==='ok'?'check-pass':connection?'check-fail':''):config?.[kind==='generate'?'generation':'edit'].status==='succeeded'?'check-pass':config?.[kind==='generate'?'generation':'edit'].status==='failed'?'check-fail':''}`}/></button>)}</div>
        <div className="settings-check-content" role="tabpanel" id={`check-panel-${selected}`} aria-labelledby={`check-tab-${selected}`}>
          <div className="settings-check-intro"><h4>{selected==='connection'?'检查接口是否响应':selected==='generate'?'验证能否生成图片':'验证能否根据参考图修改'}</h4><p>{selected==='connection'?'只检查地址和认证响应，不生成图片，也不验证图片能力。':selected==='generate'?'发送固定测试要求，生成 1 张简单测试图。返回图片后才判定通过。':'将选定参考图的背景改为浅蓝色，检查接口能否接收图片并完成编辑。'}</p></div>
          {disabledReason&&<p className="settings-check-prerequisite">{disabledReason}</p>}
          {selected==='edit'&&<div className="settings-reference"><label htmlFor="verification-reference">编辑测试参考图</label><input ref={fileInput} id="verification-reference" type="file" accept="image/png,image/jpeg,image/webp" disabled={!!busy||!!ambiguous.edit||busyVerification} onChange={e=>{const file=e.target.files?.[0];if(file&&file.size>20*1024*1024){setSubmitErrors(previous=>({...previous,edit:'参考图不能超过 20 MB。'}));e.target.value='';setReference(undefined);return;}setReference(file);setSubmitErrors(previous=>({...previous,edit:''}));delete requests.current.edit;setAuthorized(false);}} />{referencePreview&&<div className="settings-reference-preview"><img src={referencePreview} alt="即将用于编辑验证的参考图"/><span>{reference?.name}</span><button type="button" disabled={!!busy||!!ambiguous.edit||busyVerification} onClick={()=>{setReference(undefined);setAuthorized(false);if(fileInput.current)fileInput.current.value='';}}>移除</button></div>}<small>选择已获授权的 PNG、JPEG 或 WebP，最多 20 MB。</small></div>}
          {selected!=='connection'&&<label className="settings-test-authorization"><input type="checkbox" checked={authorized} onChange={e=>setAuthorized(e.target.checked)} />允许向当前服务商发送本次测试{selected==='edit'?'及所选参考图':''}（1 张，可能计费）</label>}
          <div className="settings-run-check"><button type="button" className="button-primary" disabled={!usable||(selected!=='connection'&&(!authorized||selected==='edit'&&!reference||busyVerification))} onClick={()=>selected==='connection'?void testConnection():void verify(selected)}>{busy===selected?'正在提交…':selected==='connection'?'测试连接':ambiguous[selected]?'重发同一验证请求':busyVerification?'验证进行中…':`开始${selected==='generate'?'生图':'编辑'}验证 · 1 张`}</button><span>{selected==='connection'?'不会调用生图接口':!authorized?'请先勾选测试授权':selected==='edit'&&!reference?'请先选择参考图':'使用已保存的接口配置'}</span></div>
          <div className="settings-check-results" aria-live="polite"><div className="settings-check-results-heading"><h4>检查结果</h4>{selected!=='connection'&&result&&<span>{capabilityLabel(result.status)}</span>}</div>
            {selected==='connection'?busy==='connection'?<p className="verification-loading" role="status">正在等待接口响应…</p>:connectionError?<div className="settings-feedback settings-feedback-error" role="alert"><strong>连接检查未完成</strong><p>{connectionError}</p></div>:connection?<div className={`verification-outcome verification-outcome-${connection.status==='ok'?'success':connection.status==='unsupported'?'warning':'error'}`}><span className="verification-outcome-icon" aria-hidden="true">{connection.status==='ok'?'✓':'!'}</span><div><strong>{connection.status==='ok'?'接口连接正常':connection.status==='unsupported'?'接口已响应，检查方式不受支持':'连接检查失败'}</strong><p>{connection.message}</p><time dateTime={connection.time}>{formatTaskTime(connection.time)}</time></div></div>:<div className="settings-result-empty"><span aria-hidden="true">⌁</span><strong>尚未检查连接</strong><p>点击“测试连接”，响应结果会显示在这里。</p></div>:<>{submitErrors[selected]&&<div className="settings-feedback settings-feedback-error" role="alert"><strong>{ambiguous[selected]?'提交结果待确认':'验证未能提交'}</strong><p>{submitErrors[selected]}</p>{ambiguous[selected]&&<a href="#/library">先核对任务记录 ↗</a>}</div>}{taskId?<ImageVerificationResult key={taskId} taskId={taskId} onFinished={()=>setAttempt(v=>v+1)} />:!submitErrors[selected]&&<div className="settings-result-empty"><span aria-hidden="true">▧</span><strong>尚未进行{selected==='generate'?'生图':'编辑'}验证</strong><p>测试图片、接口错误和返回时间会显示在这里。</p></div>}</>}
          </div>
        </div>
      </section>
    </div>
  </section>;
}
