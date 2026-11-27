import type { ProductSnapshot } from './productApi';
import type { TemplateSnapshot } from './creativeApi';
import type { DrawingExperience } from './ProductExperience';

export interface ProviderDiagnostic {
  method: string; path: string; http_status: number | null; response_body?: string;
  provider_message: string; error_type: string; request_id: string;
  recorded_at?: string; elapsed_ms?: number;
}
export interface ImageRecord {
  owner_id?: string | null; can_edit?: boolean;
  preview_url?: string | null; execution_profile?: Record<string, unknown> & {
    drawing_experience?: Record<string, DrawingExperience[]>;
    skill_workflow?: {primary: {name: string; version: string; version_id: string}; companions: {name: string; version: string}[]; purpose: string};
  }; execution_result?: {
    revision_analysis?: {stage:string;source_job_id:string;user_instruction:string;text_model?:string;vision_model?:string;
      error?:string;visual_observations?:string;prompt_checks?:{severity:string;message:string}[];
      edit_reference?:{source_job_id:string;available:boolean;role:string};
      edit_reference_reads?:{crop:number[]|null;question:string;observation:string}[];
      materials?:{id:string;name:string;pages:number}[];
      material_reads?:{material_id:string;name:string;page:number;method:string;observation?:string}[];
      intent?:{user_issue:string;requested_changes:string[];preserve:string[]};
      plan?:{user_issue:string;observed_issues:string[];correction_steps:string[];preserve:string[];uncertainties:string[];prompt:string}};
    attempts?: {attempt:number;status:string;at:string;diagnostic?:ProviderDiagnostic;retryable?:boolean}[];
    skill_execution?: {method: string; used_skills: {name: string; version: string; skill_id: string}[];
      files: {path: string; method?: string; chars?: number; error?: string}[]; reused_preparation?: boolean};
    native_pixels?: number[]; review?: {status: string; notes?: string};
    agent_review?: {status: 'passed' | 'rework' | 'uncertain'; summary: string; method: string;
      compared_reference: boolean; updated_at: string; checks: {item: string; status: string; detail: string}[]};
  };
  id: string; task_id: string; task_index: number; config_name: string; model_name: string;
  status: string; message: string; prompt: string; size: string; mode: string;
  created_at: string; updated_at: string; image_url: string | null; reference_url: string | null;
  product_snapshot: ProductSnapshot; template_snapshot: TemplateSnapshot;
  parent_job_id: string | null; edit_instruction: string; case_id: string | null; is_favorite: boolean;
  set_id: string | null; set_name: string; shot_name: string; diagnostic: ProviderDiagnostic | null;
}
export interface ImageTask {
  agent_run_id?: string | null; turn_count?: number; agent_summary?: string;
  owner_id?: string | null; can_manage?: boolean;
  id: string; title: string; kind: string; status: string; model_name: string; config_name: string;
  created_at: string; updated_at: string; product_snapshot: ProductSnapshot; template_snapshot: TemplateSnapshot;
  counts: Record<string, number>; completed_job_ids: string[];
}
export interface ImageTaskDetail extends ImageTask { items: ImageRecord[]; batches?: {execution_id:string; job_ids:string[]; created_at:string}[] }
export interface ImageTaskPage { items: ImageTask[]; total: number; page: number; page_size: number }
export const taskLabels: Record<string, string> = { all: '全部状态', queued: '排队中', running: '生成中', paused: '已暂停', succeeded: '已完成', partial: '部分完成', failed: '生成失败', unknown: '结果待确认', cancelled: '已取消', needs_review: '待人工审核', needs_changes: '需要修改', limit_reached: '已达执行上限' };
export const kindLabels: Record<string, string> = { free: '自由创作', set: '成套制作', edit: '图片修改', skill: '图片创作' };
export const taskPending = (task: ImageTask) => ['queued', 'running', 'paused'].includes(task.status);
export function formatTaskTime(value: string) {
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
export function taskCounts(task: ImageTask) {
  return ['succeeded', 'failed', 'unknown', 'running', 'queued', 'paused', 'cancelled']
    .filter(status => task.counts[status] > 0).map(status => `${taskLabels[status]} ${task.counts[status]}`).join(' · ');
}
export async function readTaskResponse<T>(response: Response): Promise<T> {
  const value = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof value?.detail === 'string' ? value.detail : `请求失败（HTTP ${response.status}）`);
  return value;
}
