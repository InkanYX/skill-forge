export interface CreativeTemplate {
  id: string; name: string; purpose: string; prompt: string; skill: string; notes: string;
  size: string; count: number; revision: number; updated_at: string; variables: string[];
}
export interface TemplateSnapshot extends Partial<CreativeTemplate> { values?: Record<string, string>; extra?: string }
export interface CreativeCase {
  id: string; job_id: string; title: string; experience: string; issues: string;
  image_url: string; prompt: string; model_name: string; template_snapshot: TemplateSnapshot;
}
export async function creativeRequest<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const response = await fetch(`/api/${path}`, { cache: 'no-store', signal: AbortSignal.timeout(12000), ...(body ? { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}) });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : `操作未完成（${response.status}）`);
  return value;
}
