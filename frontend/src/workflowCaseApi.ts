import { apiFetch } from './apiFetch';
import type { Project, ProjectDocument, Stage } from './creationProjectApi';
import type { ImageRecord } from './imageTaskApi';

export interface WorkflowCase {
  author?:{id:string;name:string};
  id:string; project_id:string; title:string; summary:string; created_at:string;
  image_count:number; material_count:number; can_edit:boolean;
  snapshot?: {
    settings:Project['settings']; images:ImageRecord[];
    history:(ProjectDocument & {stage:Stage;created_at:string})[];
    materials:Project['materials']; messages:Project['messages'];
    feedback:{job_id:string;issues:string;requested_change:string;outcome:string}[];
    related_projects?: Project[];
  };
}
export async function caseRequest<T>(path='',method='GET',body?:unknown):Promise<T> {
  const response=await apiFetch('/api/workflow-cases'+path,{method,cache:'no-store',
    headers:body?{'Content-Type':'application/json'}:undefined,body:body?JSON.stringify(body):undefined,
    signal:AbortSignal.timeout(120000)});
  const value=await response.json();
  if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'案例操作失败，请重试。');
  return value;
}
