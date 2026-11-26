import { useEffect, useRef, useState, type FormEvent } from 'react';
import { apiFetch } from './apiFetch';
import { listModelOptions, type ModelOption } from './modelConfigApi';
import { readTaskResponse, taskLabels, type ImageRecord } from './imageTaskApi';
import { startTaskPolling } from './taskPolling';
import TaskCancel from './TaskCancel';

interface History { items: ImageRecord[]; has_more: boolean }
export default function InlineImageRevision({source, open, onClose, onDisplay, reload, canEdit = true}: {
  source:ImageRecord; open:boolean; onClose:()=>void;
  onDisplay:(rootId:string,item:ImageRecord)=>void; reload:number; canEdit?:boolean;
}) {
  const [history,setHistory]=useState<History>(); const [selectedId,setSelectedId]=useState('');
  const [models,setModels]=useState<ModelOption[]>([]); const [modelId,setModelId]=useState('');
  const [instruction,setInstruction]=useState(''); const [busy,setBusy]=useState(false);
  const [uncertain,setUncertain]=useState(false); const [error,setError]=useState('');
  const selected=history?.items.find(item=>item.id===selectedId)||source;
  const model=models.find(item=>item.id===modelId);
  const request=useRef<{id:string;body:FormData}|undefined>(undefined);
  const poller=useRef<ReturnType<typeof startTaskPolling<History>>|null>(null);
  const chosen=useRef(''); const notify=useRef(onDisplay); notify.current=onDisplay;
  const busyRef=useRef(false);
  useEffect(()=>{
    const current=startTaskPolling<History>({
      load:async signal=>readTaskResponse(await apiFetch(`/api/image-jobs/${source.id}/revisions`,{signal,cache:'no-store'})),
      pending:value=>value.items.some(item=>['queued','running'].includes(item.status)),
      onData:value=>{
        setHistory(value);
        const retry=value.items.filter(item=>item.execution_profile?.retry_source_job_id===chosen.current).at(-1);
        const next=retry||value.items.find(item=>item.id===chosen.current)||value.items.at(-1);
        if(next){chosen.current=next.id;setSelectedId(next.id);notify.current(source.id,next);}
      },
      onError:err=>setError(err instanceof Error?err.message:'修改记录读取失败，请刷新。'),
    });
    poller.current=current;
    return()=>{current.stop();poller.current=null;};
  },[source.id,reload]);
  useEffect(()=>{
    if(!open)return;
    let alive=true;
    listModelOptions().then(items=>{if(alive){setModels(items);setModelId(previous=>items.some(item=>item.id===previous)?previous:items.find(item=>item.model_name===selected.model_name)?.id||items[0]?.id||'');}})
      .catch(err=>{if(alive)setError(err instanceof Error?err.message:'模型读取失败');});
    return()=>{alive=false;};
  },[open,selected.model_name]);
  function choose(id:string){
    const item=history?.items.find(item=>item.id===id);if(!item)return;
    chosen.current=id;setSelectedId(id);notify.current(source.id,item);
  }
  async function submit(event:FormEvent){
    event.preventDefault();if(busyRef.current||(!uncertain&&(!model?.has_api_key||selected.status!=='succeeded')))return;
    busyRef.current=true;setBusy(true);setError('');let rejected=false;
    try{
      if(!request.current){
        const body=new FormData();const id=crypto.randomUUID();
        for(const [key,value] of Object.entries({request_id:id,config_id:model!.config_id,model_name:model!.model_name,
          source_job_id:selected.id,prompt:instruction.trim(),size:selected.size,count:'1'}))body.set(key,value);
        // Omit skill overrides so the backend inherits the source's frozen skill and evidence.
        request.current={id,body};
      }
      const response=await apiFetch('/api/image-jobs/batch',{method:'POST',body:request.current.body,signal:AbortSignal.timeout(30000)});
      rejected=response.status>=400&&response.status<500;
      const items=await readTaskResponse<ImageRecord[]>(response);
      if(!items[0])throw new Error('提交结果无法确认，请刷新核对修改记录。');
      const item=items[0];chosen.current=item.id;setSelectedId(item.id);
      setHistory(previous=>({items:[...(previous?.items||[source]).filter(row=>row.id!==item.id),item],has_more:previous?.has_more||false}));
      notify.current(source.id,item);setUncertain(false);request.current=undefined;setInstruction('');
      await poller.current?.refresh();
    }catch(err){
      setError((err instanceof Error?err.message:'提交失败')+(rejected?'':' 请先刷新核对记录；重发会复用同一次提交。'));
      setUncertain(!rejected);if(rejected)request.current=undefined;
    }finally{busyRef.current=false;setBusy(false);}
  }
  const pending=history?.items.some(item=>['queued','running'].includes(item.status));
  return <section className="inline-image-revision" aria-label="单张图片修改">
    {!!history&&history.items.length>1&&<label className="inline-revision-versions">图片修改记录<select aria-label="选择此图的修改版本" disabled={busy||uncertain} value={selectedId} onChange={event=>choose(event.target.value)}>
      {history.items.map((item,index)=><option key={item.id} value={item.id}>{index===0?'原图':`修改 ${index}`} · {taskLabels[item.status]||item.status}{item.edit_instruction?` · ${item.edit_instruction.slice(0,28)}`:''}</option>)}
    </select></label>}
    {history?.has_more&&<small>当前显示原图和最近 100 条修改记录。</small>}
    {pending&&<p role="status">正在处理这张图片的修改，进度会在原位置更新。</p>}
    {canEdit&&selected.id!==source.id&&<TaskCancel key={selected.id} jobId={selected.id} status={selected.status} onChanged={()=>void poller.current?.refresh()}/>}
    {error&&<p className="feedback feedback-error" role="alert">{error} <button type="button" className="button-secondary" onClick={()=>void poller.current?.refresh()}>刷新修改记录</button></p>}
    {open&&canEdit&&<form onSubmit={submit} className="inline-revision-form">
      <div className="section-heading"><strong>修改这张图</strong><button type="button" className="button-secondary" disabled={busy||uncertain} onClick={onClose}>收起修改</button></div>
      <p>沿用所选图片的产品资料、Skill 和尺寸。先理解要求、核对原图及资料，再整理提示词修改。</p>
      <fieldset disabled={busy||uncertain}>
        <label>生图模型<select required value={modelId} onChange={event=>setModelId(event.target.value)}><option value="">选择已配置模型</option>{models.map(item=><option key={item.id} value={item.id}>{item.model_name}</option>)}</select></label>
        <label>本次修改要求<textarea autoFocus required maxLength={8000} rows={4} value={instruction} onChange={event=>setInstruction(event.target.value)} placeholder="描述哪里有误、需要如何调整，以及需要保留的内容。"/></label>
      </fieldset>
      {model&&!model.has_api_key&&<p className="feedback feedback-warning">请先在模型配置中填写 API Key。</p>}
      {selected.status!=='succeeded'&&<p>当前选择的修改尚未成功，可切回原图或已完成的修改继续编辑；失败任务可使用上方重试入口。</p>}
      <button type="submit" className="button-primary" disabled={busy||(!uncertain&&(!model?.has_api_key||!instruction.trim()||selected.status!=='succeeded'||!!pending))}>{busy?'正在提交…':uncertain?'重发同一次修改':'分析并修改这张图'}</button>
      <small>原图和历次修改保留；修改结果在此卡片查看，模型调用会消耗相应额度。</small>
    </form>}
  </section>;
}
