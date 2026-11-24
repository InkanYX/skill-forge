import { apiFetch } from './apiFetch';
import { imageConfigRequest, type ImageConfiguration } from './imageConfigApi';
export interface ModelConfig {
  id: string;
  name: string;
  base_url: string;
  model_name: string;
  model_names: string[];
  has_api_key: boolean;
  updated_at: string;
}

export interface ConfigDraft {
  name: string;
  base_url: string;
  api_key: string;
  model_name: string;
  model_names: string[];
}

// id identifies a dropdown option; config_id remains the provider's API ID.
export interface ModelOption extends ModelConfig { config_id: string; generation_verified?: boolean; edit_verified?: boolean }

export interface ConnectionResult {
  status: 'ok' | 'error' | 'unsupported';
  message: string;
}

export interface ProbeResult extends ConnectionResult {
  models: string[];
}

async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await apiFetch(`/api/model-configs${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    cache: 'no-store',
    signal: AbortSignal.timeout(35000),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map((item: { msg?: string }) => item.msg || '输入格式错误').join('；')
      : `请求失败（HTTP ${response.status}），请检查后端是否已更新并启动。`;
    throw new Error(message);
  }
  if (data === null) throw new Error('接口返回格式错误');
  return data as T;
}

export const listConfigs = () => request<ModelConfig[]>('');
export const listModelOptions = async (): Promise<ModelOption[]> => {
  const config = await imageConfigRequest<ImageConfiguration | null>();
  return config ? [...new Set([config.model_name, ...config.model_names])].map(model => ({...config, model_name:model,
    config_id:config.id, id:JSON.stringify([config.id,model]),
    generation_verified:model===config.model_name && config.generation.status==='succeeded' && config.has_api_key,
    edit_verified:model===config.model_name && config.edit.status==='succeeded' && config.has_api_key})) : [];
};
export const saveConfig = (draft: ConfigDraft, id?: string) => request<ModelConfig>(id ? `/${encodeURIComponent(id)}` : '', id ? 'PUT' : 'POST', draft);
export const testConfig = (draft: ConfigDraft, id?: string) => request<ConnectionResult>('/test', 'POST', { ...draft, config_id: id || null });
export const readModels = (draft: ConfigDraft, id?: string) => request<ProbeResult>('/models', 'POST', { ...draft, config_id: id || null });
