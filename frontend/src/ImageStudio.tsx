import { useEffect, useRef, useState, type FormEvent } from 'react';
import { apiFetch } from './apiFetch';
import { listModelOptions, type ModelOption } from './modelConfigApi';
import { creativeRequest, type CreativeTemplate } from './creativeApi';
import { productValues, type Product, type ProductAsset } from './productApi';
import TemplateVariableField from './TemplateVariableField';
import ImageSizePicker from './ImageSizePicker';
import TaskResultsPanel from './TaskResultsPanel';
import { useCreationSkill } from './CreationSkillContext';
import { projectRequest, type Project } from './creationProjectApi';
import { useAuth } from './AuthGate';
import { rememberCreation } from './resumeCreation';

export default function ImageStudio({onDraftChange,onSubmittingChange}:{onDraftChange?:(dirty:boolean)=>void;onSubmittingChange?:(busy:boolean)=>void}={}){
  const {user}=useAuth();
  const skill=useCreationSkill();const [models,setModels]=useState<ModelOption[]>([]);const [modelId,setModelId]=useState('');
  const [prompt,setPrompt]=useState('');const [size,setSize]=useState('default');const [count,setCount]=useState(1);
  const [reference,setReference]=useState<File>();const [preview,setPreview]=useState('');const input=useRef<HTMLInputElement>(null);
  const [taskId,setTaskId]=useState(()=>new URLSearchParams(window.location.hash.split('?')[1]).get('task')||'');const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [reading,setReading]=useState(false);
  useEffect(()=>{if(taskId)rememberCreation(user.id,'#/studio?task='+encodeURIComponent(taskId),'直接生图任务');},[taskId,user.id]);
  const [uncertain,setUncertain]=useState(false);const requestId=useRef<string|undefined>(undefined);const alive=useRef(true);
  // Old deep links can still reuse stored data, without a second management UI here.
  const [product,setProduct]=useState<Product>();const [template,setTemplate]=useState<CreativeTemplate>();
  const [assets,setAssets]=useState<ProductAsset[]>([]);const [assetId,setAssetId]=useState('');const [values,setValues]=useState<Record<string,string>>({});
  const [products,setProducts]=useState<Project[]>([]);const [experienceProduct,setExperienceProduct]=useState('');
  const selected=models.find(item=>item.id===modelId);const locked=busy||uncertain;
  useEffect(()=>{onDraftChange?.(!!(prompt.trim()||reference||product||template||experienceProduct||size!=='default'||count!==1));},[prompt,reference,product,template,experienceProduct,size,count,onDraftChange]);
  useEffect(()=>{onSubmittingChange?.(busy);return()=>{onSubmittingChange?.(false);};},[busy,onSubmittingChange]);
  async function loadModels(){setReading(true);try{const items=await listModelOptions();if(alive.current){setModels(items);setModelId(previous=>items.some(item=>item.id===previous)?previous:items[0]?.id||'');}}catch(err){if(alive.current)setError(err instanceof Error?err.message:'模型读取失败');}finally{if(alive.current)setReading(false);}}
  useEffect(()=>{alive.current=true;void loadModels();const params=new URLSearchParams(window.location.hash.split('?')[1]);
    projectRequest<Project[]>('?kind=product').then(items=>{if(alive.current)setProducts(items);}).catch(err=>{if(alive.current)setError(err.message);});
    if(params.get('product'))creativeRequest<Product[]>('products').then(items=>{const item=items.find(value=>value.id===params.get('product'));if(alive.current&&item){setProduct(item);setValues(productValues(item));return creativeRequest<ProductAsset[]>(`products/${item.id}/assets`).then(list=>{if(alive.current)setAssets(list);});}}).catch(err=>{if(alive.current)setError(err.message);});
    if(params.get('template'))creativeRequest<CreativeTemplate[]>('templates').then(items=>{const item=items.find(value=>value.id===params.get('template'));if(alive.current&&item){setTemplate(item);setSize(item.size);setCount(item.count);}}).catch(err=>{if(alive.current)setError(err.message);});
    return()=>{alive.current=false;};
  },[]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(()=>{if(!reference){setPreview('');return;}const url=URL.createObjectURL(reference);setPreview(url);return()=>URL.revokeObjectURL(url);},[reference]);
  async function submit(event:FormEvent){
    event.preventDefault();if(!selected||busy)return;const id=requestId.current||crypto.randomUUID();requestId.current=id;setBusy(true);setError('');let knownRejection=false;let sent=false;
    try{const form=new FormData();form.set('config_id',selected.config_id);form.set('model_name',selected.model_name);form.set('request_id',id);form.set('prompt',prompt);form.set('size',size);form.set('count',String(count));
      if(experienceProduct)form.set('experience_product_id',experienceProduct);
      if(reference)form.set('reference',reference);if(product)form.set('product',JSON.stringify({id:product.id,revision:product.revision,asset_id:assetId||null}));if(template)form.set('template',JSON.stringify({id:template.id,revision:template.revision,variables:values}));skill.append(form);
      sent=true;const response=await apiFetch('/api/image-jobs/batch',{method:'POST',body:form,signal:AbortSignal.timeout(30000)});knownRejection=response.status>=400&&response.status<500;
      const result=await response.json();if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'提交失败，请检查输入。');
      if(!alive.current)return;setTaskId(result[0]?.task_id||id);requestId.current=undefined;setUncertain(false);
    }catch(err){if(!alive.current)return;if(!sent)knownRejection=true;setError((err instanceof Error?err.message:'提交未完成')+(knownRejection?'':' 请先核对生成记录；重发会沿用同一提交标识。'));setUncertain(!knownRejection);if(knownRejection)requestId.current=undefined;}
    finally{if(alive.current)setBusy(false);}
  }
  return <section className="image-studio" aria-label="生图内容"><div className="studio-layout"><form className="studio-form" onSubmit={submit}>
    <div className="form-field"><label htmlFor="generation-config">图片模型</label><div className="input-with-action"><select id="generation-config" required disabled={locked} value={modelId} onChange={e=>setModelId(e.target.value)}><option value="">选择已配置模型</option>{models.map(item=><option key={item.id} value={item.id}>{item.model_name}</option>)}</select><button type="button" className="button-secondary" disabled={locked||reading} onClick={()=>void loadModels()}>{reading?'读取中…':'刷新'}</button></div>{!reading&&!models.length&&<small>先到<a href="#/settings">模型配置</a>保存模型连接。</small>}</div>
    <fieldset disabled={locked}>
      {!product&&<details className="workflow-options"><summary>关联产品经验（选填）</summary><label>产品<select value={experienceProduct} onChange={e=>setExperienceProduct(e.target.value)}><option value="">不关联产品</option>{products.map(item=><option key={item.id} value={item.id}>{item.title}</option>)}</select></label><p>参考此产品已生效的通用及匹配用途的经验；产品资料和参考图仍需自行提供。</p></details>}
      {(product||template)&&<div className="production-source"><span>已载入：{[product?.name,template?.name].filter(Boolean).join(' / ')}</span><a href="#/studio">清除已载入内容</a></div>}
      {product&&!!assets.length&&<div className="form-field"><label htmlFor="creative-asset">已载入产品的参考图</label><select id="creative-asset" value={assetId} onChange={e=>{setAssetId(e.target.value);setReference(undefined);if(input.current)input.current.value='';}}><option value="">选择参考图或临时上传</option>{assets.map(item=><option key={item.id} value={item.id}>{item.kind} · {item.name}</option>)}</select></div>}
      {template?.variables.map(name=><TemplateVariableField key={name} name={name} value={values[name]||''} product={product} onChange={value=>setValues(previous=>({...previous,[name]:value}))}/>)}
      {template&&<details><summary>已载入的制作要求</summary><p>{template.prompt}</p><p>{template.notes}</p></details>}
      <div className="form-field"><label htmlFor="generation-prompt">{template?'本次补充要求':'图片要求 / 提示词'}</label><textarea id="generation-prompt" rows={8} maxLength={8000} required={!template} value={prompt} onChange={e=>setPrompt(e.target.value)} placeholder="描述要生成的画面；有参考图时说明需要保留和修改的内容。"/></div>
      <div className="form-field"><label htmlFor="reference-image">参考图（选填）</label><input ref={input} id="reference-image" type="file" accept=".png,.jpg,.jpeg,.webp" onChange={e=>{const file=e.target.files?.[0];if(file&&file.size>20*1024*1024){setError('参考图不能超过 20 MB。');e.target.value='';return;}setReference(file);if(file)setAssetId('');}}/><small>{reference?`已选择：${reference.name}`:'参考图将随本次请求传入所选服务商。'}</small>{preview&&<div className="reference-preview"><img src={preview} alt="本次参考图"/><button type="button" onClick={()=>{setReference(undefined);if(input.current)input.current.value='';}}>移除</button></div>}</div>
      <ImageSizePicker id="generation-size" value={size} onChange={setSize}/><div className="form-field"><label htmlFor="generation-count">生成数量</label><select id="generation-count" value={count} onChange={e=>setCount(Number(e.target.value))}>{Array.from({length:16},(_,i)=><option key={i+1} value={i+1}>{i+1} 张</option>)}</select><small>同一要求生成多张候选图。不同图片用途请在图片策划中安排。</small></div>
    </fieldset>
    {error&&<p className="feedback feedback-error" role="alert">{error} <a href="#/library">核对生成记录</a></p>}
    {selected&&!selected.has_api_key&&<p className="feedback feedback-warning">请在<a href="#/settings">模型配置</a>重新填写 API Key。</p>}
    <div className="form-actions">{uncertain&&<button type="button" className="button-secondary" onClick={()=>{if(window.confirm('已核对生成记录，确定修改输入并允许建立新的提交吗？')){setUncertain(false);requestId.current=undefined;}}}>核对后修改输入</button>}<button type="submit" className="button-primary" disabled={busy||!selected?.has_api_key||!skill.ready||(!template&&!prompt.trim())||!!template?.variables.some(name=>!values[name]?.trim())}>{busy?'正在提交…':uncertain?'重发同一次提交':`生成 ${count} 张图片`}</button></div>
  </form><div className="studio-result">{taskId?<TaskResultsPanel taskId={taskId}/>:<div className="result-placeholder empty-result"><span className="step-icon">图片</span><h3>本次生成结果</h3><p>提交后显示图片、进度和日志。历史结果在生成记录中查看。</p></div>}</div></div></section>;
}
