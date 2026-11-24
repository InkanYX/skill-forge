import { useCallback, useEffect, useRef, useState } from 'react';
import { projectRequest, type Project, type Stage } from './creationProjectApi';
import { startTaskPolling } from './taskPolling';

export function useCreationProject(id: string) {
  const [project,setProject]=useState<Project>(); const [loading,setLoading]=useState(!!id);
  const [busy,setBusy]=useState(false); const [error,setError]=useState(''); const [notice,setNotice]=useState('');
  const epoch=useRef(0); const requestIds=useRef<Record<string,string>>({});
  const poller=useRef<ReturnType<typeof startTaskPolling<Project>>|undefined>(undefined);
  useEffect(()=>{
    ++epoch.current;setProject(undefined);setError('');setNotice('');
    if(!id){setLoading(false);return;}
    const current=epoch.current;
    const handle=startTaskPolling<Project>({load:signal=>projectRequest<Project>('/'+id,'GET',undefined,signal),pending:value=>value.busy,
      onData:value=>{if(current===epoch.current){setProject(previous=>previous&&previous.revision>value.revision?previous:value);setError('');}},
      onError:err=>{if(current===epoch.current)setError(err instanceof Error?err.message:'任务读取失败，请刷新。');},
      onLoading:value=>{if(current===epoch.current)setLoading(value);},interval:2200,timeout:15000});
    poller.current=handle;
    return()=>{++epoch.current;handle.stop();};
  },[id]);
  const mutate=useCallback(async(action:()=>Promise<Project>,message='')=>{
    const current=epoch.current;setBusy(true);setError('');setNotice('');
    try{const value=await action();if(current!==epoch.current)return;setProject(value);setNotice(message);if(value.busy)void poller.current?.refresh();return value;}
    catch(err){if(current===epoch.current)setError(err instanceof Error?err.message:'操作失败。');}
    finally{if(current===epoch.current)setBusy(false);}
  },[]);
  async function run(stage:Stage,instruction:string,options:Record<string,unknown>={}){
    if(!project)return;
    const key=id+':'+stage;const requestId=requestIds.current[key]||crypto.randomUUID();requestIds.current[key]=requestId;
    const value=await mutate(()=>projectRequest<Project>(`/${id}/stages/${stage}`,'POST',{revision:project.revision,request_id:requestId,instruction,...options}));
    if(value)delete requestIds.current[key];return value;
  }
  return {project,loading,busy,error,notice,setError,setNotice,mutate,run,refresh:()=>poller.current?.refresh(),
    locked:busy||!!project?.busy||project?.can_edit===false};
}

export async function uploadProjectMaterials(project:Project,files:File[],kind:string){
  let value=project;
  for(const file of files){
    const body=new FormData();body.set('revision',String(value.revision));body.set('material_id',crypto.randomUUID());body.set('kind',kind);body.set('file',file);
    value=await projectRequest<Project>(`/${value.id}/materials`,'POST',body);
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
