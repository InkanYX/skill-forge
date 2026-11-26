import { useCallback, useEffect, useRef, useState } from 'react';
import { projectRequest, type Project, type Stage } from './creationProjectApi';
import { startTaskPolling } from './taskPolling';
import { useAuth } from './AuthGate';
import { rememberCreation } from './resumeCreation';

export function useCreationProject(id: string) {
  const {user}=useAuth();
  const [project,setProject]=useState<Project>(); const [loading,setLoading]=useState(!!id);
  const [busy,setBusy]=useState(false); const [error,setError]=useState(''); const [notice,setNotice]=useState('');
  const [readError,setReadError]=useState('');const inFlight=useRef<number|null>(null);
  const epoch=useRef(0); const requestIds=useRef<Record<string,string>>({});
  const poller=useRef<ReturnType<typeof startTaskPolling<Project>>|undefined>(undefined);
  useEffect(()=>{if(project && new URLSearchParams(window.location.hash.split('?')[1]).get('project')===project.id)rememberCreation(user.id,window.location.hash,project.title);},[project?.id,project?.revision,user.id]);
  useEffect(()=>{
    ++epoch.current;setProject(undefined);setError('');setReadError('');setNotice('');setBusy(false);
    if(!id){setLoading(false);return;}
    const current=epoch.current;
    const handle=startTaskPolling<Project>({load:signal=>projectRequest<Project>('/'+id,'GET',undefined,signal),pending:value=>value.busy||value.images.some(image=>['queued','running'].includes(image.status)),
      onData:value=>{if(current===epoch.current){setProject(previous=>previous&&previous.revision>value.revision?previous:value);setReadError('');}},
      onError:err=>{if(current===epoch.current)setReadError(err instanceof Error?err.message:'任务读取失败，请刷新。');},
      onLoading:value=>{if(current===epoch.current)setLoading(value);},interval:2200,timeout:15000});
    poller.current=handle;
    return()=>{++epoch.current;handle.stop();};
  },[id]);
  const mutate=useCallback(async(action:()=>Promise<Project>,message='')=>{
    if(inFlight.current===epoch.current)return;
    inFlight.current=epoch.current;
    const current=epoch.current;setBusy(true);setError('');setNotice('');
    try{const value=await action();if(current!==epoch.current)return;setProject(previous=>previous&&previous.revision>value.revision?previous:value);setNotice(message||'请求已提交，结果会自动更新。');if(value.busy)void poller.current?.refresh();return value;}
    catch(err){if(current===epoch.current){if(err instanceof MaterialUploadError)setProject(err.project);setError(err instanceof Error?err.message:'操作失败。');}}
    finally{if(inFlight.current===current)inFlight.current=null;if(current===epoch.current)setBusy(false);}
  },[]);
  async function run(stage:Stage,instruction:string,options:Record<string,unknown>={}){
    if(!project)return;
    const key=id+':'+stage+':'+JSON.stringify({instruction,options});const requestId=requestIds.current[key]||crypto.randomUUID();requestIds.current[key]=requestId;
    const value=await mutate(()=>projectRequest<Project>(`/${id}/stages/${stage}`,'POST',{revision:project.revision,request_id:requestId,instruction,...options}));
    if(value)delete requestIds.current[key];return value;
  }
  return {project,loading,busy,error:error||readError,notice,setError,setNotice,mutate,run,refresh:()=>poller.current?.refresh(),
    locked:busy||!!project?.busy||project?.can_edit===false};
}

export type UploadProgress=(done:number,total:number,name:string)=>void;
class MaterialUploadError extends Error{
  constructor(public project:Project,message:string){super(message);}
}
export async function uploadProjectMaterials(project:Project,files:File[],kind:string,onProgress?:UploadProgress){
  let value=project;let done=0;
  for(const file of files){
    onProgress?.(done,files.length,file.name);
    const body=new FormData();body.set('revision',String(value.revision));body.set('material_id',crypto.randomUUID());body.set('kind',kind);body.set('file',file);
    try{value=await projectRequest<Project>(`/${value.id}/materials`,'POST',body);done++;onProgress?.(done,files.length,file.name);}
    catch(err){throw new MaterialUploadError(value,`已保存 ${done} / ${files.length} 个文件。${file.name}：${err instanceof Error?err.message:'上传失败'}。请先刷新核对已上传资料，再补传剩余文件。`);}
  }
  return value;
}

export function useUnsavedChanges(dirty:boolean){
  useEffect(()=>{
    const unload=(event:BeforeUnloadEvent)=>{if(dirty)event.preventDefault();};
    const leave=(event:MouseEvent)=>{const link=event.target instanceof Element?event.target.closest('a'):null;if(dirty&&link?.getAttribute('href')?.startsWith('#/')&&!window.confirm('当前修改尚未保存，确定离开吗？'))event.preventDefault();};
    window.addEventListener('beforeunload',unload);document.addEventListener('click',leave,true);
    return()=>{window.removeEventListener('beforeunload',unload);document.removeEventListener('click',leave,true);};
  },[dirty]);
}
