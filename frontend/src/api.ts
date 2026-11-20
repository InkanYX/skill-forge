export interface HealthResponse {
  status: 'ok';
  service: string;
  version: string;
  timestamp: string;
}

export interface StorageStatus {
  storage: 'file' | 'postgresql';
  status: 'ready' | 'unavailable';
  message: string;
}

export async function fetchStorage(signal: AbortSignal): Promise<StorageStatus> {
  const response = await fetch('/api/system/status', { signal, cache: 'no-store' });
  if (!response.ok) throw new Error('无法读取数据库状态');
  const data = await response.json();
  if (!['file', 'postgresql'].includes(data.storage) || !['ready', 'unavailable'].includes(data.status) || typeof data.message !== 'string') throw new Error('数据库状态格式错误');
  return data as StorageStatus;
}

export async function fetchHealth(signal: AbortSignal): Promise<HealthResponse> {
  const response = await fetch('/api/health', { signal, cache: 'no-store' });
  if (!response.ok) throw new Error(`健康检查失败（HTTP ${response.status}）`);
  const value: unknown = await response.json();
  if (!value || typeof value !== 'object') throw new Error('后端返回了无效数据');
  const data = value as Record<string, unknown>;
  if (data.status !== 'ok' || typeof data.service !== 'string' ||
      typeof data.version !== 'string' || typeof data.timestamp !== 'string' ||
      Number.isNaN(Date.parse(data.timestamp))) {
    throw new Error('后端健康检查格式不匹配');
  }
  return data as unknown as HealthResponse;
}
