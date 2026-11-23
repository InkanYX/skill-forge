import { apiFetch } from './apiFetch';
export interface ImageConfiguration {
  id: string; name: string; base_url: string; model_name: string; model_names: string[];
  text_model_name: string; text_config_id: string | null;
  has_api_key: boolean; updated_at: string;
  generation: {status: string; job_id: string | null; task_id: string | null; updated_at: string | null};
  edit: ImageConfiguration['generation'];
}
export async function imageConfigRequest<T>(path = '', body?: unknown): Promise<T> {
  const response = await apiFetch(`/api/image-configs${path}`, {cache:'no-store', signal:AbortSignal.timeout(15000),
    ...(body ? {method:path ? 'POST':'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)} : {})});
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : Array.isArray(value.detail) ? value.detail.map((item:{msg?:string}) => (item.msg || '输入格式错误').replace(/^Value error,\s*/, '')).join('；') : '请检查接口地址和输入格式。');
  return value;
}
