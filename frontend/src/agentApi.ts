import { apiFetch } from './apiFetch';
import type { ImageRecord } from './imageTaskApi';

export interface AgentStep {
  index: number; kind: string; tool: string; arguments: string; result: string; created_at: string;
}

export interface AgentRun {
  id: string; status: string; goal: string; skill_id: string; skill_version_id: string; config_id: string;
  model_name: string; vision_model_name: string; steps_count: number; image_calls: number;
  image_model_name: string;
  max_steps: number; max_images: number; summary: string; error: string;
  created_at: string; updated_at: string; finished_at: string | null;
  steps: AgentStep[]; images: ImageRecord[];
}

export const agentStatusLabels: Record<string, string> = {
  queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败',
  unknown: '结果待确认', cancelled: '已取消',
};

export const toolLabels: Record<string, string> = {
  read_skill_file: '读取技能文件', write_prompt: '保存提示词', generate_image: '生成图片',
  edit_image: '修改图片', view_image: '视觉质检', lint_prompt: '提示词预检',
  count_copy: '统计文案', scan_copy: '扫描文案', make_checklist: '生成质检表',
  read_scenario: '查询场景', finish: '结束任务',
};

export function agentPending(run: AgentRun) {
  return ['queued', 'running'].includes(run.status);
}

export async function agentRequest<T>(path = '', init?: RequestInit): Promise<T> {
  const response = await apiFetch(`/api/agent${path}`, { cache: 'no-store', ...init });
  const value = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof value?.detail === 'string' ? value.detail : `请求失败（HTTP ${response.status}）`);
  return value as T;
}

export function listRuns() {
  return agentRequest<AgentRun[]>('/runs');
}

export function getRun(id: string) {
  return agentRequest<AgentRun>(`/runs/${id}`);
}

export function createRun(form: FormData) {
  return agentRequest<AgentRun>('/runs', { method: 'POST', body: form });
}

export function cancelRun(id: string) {
  return agentRequest<AgentRun>(`/runs/${id}/cancel`, { method: 'POST' });
}

export function reworkRun(id: string, instruction: string) {
  return agentRequest<AgentRun>(`/runs/${id}/rework`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ instruction }),
  });
}

export function promptUrl(runId: string, promptId: string) {
  return `/api/agent/runs/${runId}/prompts/${promptId}`;
}
