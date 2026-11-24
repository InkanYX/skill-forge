import { apiFetch } from './apiFetch';
export interface CreativeTemplate {
  owner_id?: string | null; can_edit?: boolean;
  id: string; name: string; purpose: string; prompt: string; skill: string; notes: string;
  size: string; count: number; revision: number; updated_at: string; variables: string[];
  skill_id?: string | null; skill_revision?: number; skill_name?: string;
}
export interface CreativeSkill { owner_id?: string | null; can_edit?: boolean; id: string; name: string; purpose: string; content: string; revision: number; updated_at: string }
export interface TemplateSnapshot extends Partial<CreativeTemplate> { values?: Record<string, string>; extra?: string }
import type { ProductSnapshot } from './productApi';
export interface CreativeCase {
  can_edit?: boolean; owner_id?: string | null;
  id: string; job_id: string; title: string; experience: string; issues: string;
  outcome: 'pending' | 'satisfied' | 'rework'; requested_change: string; revision: number;
  product_id?: string | null; product_name?: string; product_locked?: boolean; updated_at?: string;
  image_url: string; prompt: string; model_name: string; template_snapshot: TemplateSnapshot; product_snapshot?: ProductSnapshot;
}
export async function creativeRequest<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const response = await apiFetch(`/api/${path}`, { cache: 'no-store', signal: AbortSignal.timeout(12000), ...(body ? { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : Array.isArray(value.detail) ? value.detail.map((item: {msg?: string}) => item.msg || '输入格式不正确').join('；') : `操作未完成（${response.status}）`);
  return value;
}
