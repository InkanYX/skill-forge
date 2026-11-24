import { apiFetch } from './apiFetch';
import type { ImageRecord } from './imageTaskApi';

export type Stage = 'analysis' | 'brief' | 'prompts';
export const stageNames: Record<Stage | 'materials' | 'images', string> = { materials: '产品资料', analysis: '产品卖点', brief: '整套图需', prompts: '图片提示词', images: '图片制作' };
export interface Material { id: string; name: string; kind: string; media_type: string; pages: number; size: number }
export interface Shot { id: string; name: string; objective: string; selling_point: string; content: string; layout: string; copy: string; notes: string; size: string; reference_ids: string[] }
export interface Prompt { shot_id: string; prompt: string; reference_ids: string[] }
export interface DocumentContent { facts?: string; selling_points?: string; questions?: string; shots?: Shot[]; prompts?: Prompt[] }
export interface ProjectDocument { id: string; version: number; content: DocumentContent; confirmed_at: string | null }
export interface Project {
  id: string; title: string; revision: number; stage: Stage | 'images'; busy: boolean; created_at: string; updated_at: string;
  kind: 'product' | 'plan' | 'legacy'; source_product_id: string | null; analysis_confirmed: boolean; can_edit: boolean;
  legacy_product_id?: string | null;
  source?: { product_id: string; title: string; document_id: string; version: number }; source_updated?: boolean;
  settings: { goal: string; style: string; image_count: number; planning_model: string; image_model: string; market: string; language: string; audience: string; selected_selling_points: string; sku?: string };
  skill: Record<string, unknown>; documents: Record<Stage, ProjectDocument | null>;
  materials: Material[]; images: ImageRecord[];
  messages: { role: string; stage: string; content: string; created_at: string }[];
  executions: { id: string; stage: Stage | 'images'; status: string; error: string; created_at: string; updated_at: string; output: { diagnostic?: Record<string, unknown>; trace?: { used_skills?: { name: string }[]; materials?: { name: string; page: number; method: string }[]; files?: { path: string }[] } } }[];
  history: (ProjectDocument & { stage: Stage; created_at: string })[];
  batches: { execution_id: string; job_ids: string[]; created_at: string }[];
}
export interface PlanTemplate { id: string; name: string; description: string; style: string; shots: {name: string; objective: string; layout: string}[] }
export async function projectRequest<T>(path = '', method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await apiFetch('/api/creation-projects' + path, { method, cache: 'no-store', signal: signal || AbortSignal.timeout(20000),
    headers: body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? body instanceof FormData ? body : JSON.stringify(body) : undefined });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : Array.isArray(value.detail) ? value.detail.map((item: {msg: string}) => item.msg).join('；') : '请求失败，请刷新任务后重试。');
  return value;
}
export const materialUrl = (projectId: string, id: string) => `/api/creation-projects/${projectId}/materials/${id}`;
