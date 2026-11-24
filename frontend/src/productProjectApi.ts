import { apiFetch } from './apiFetch';
import type { ImageRecord } from './imageTaskApi';

export interface ProjectAsset {
  id: string; name: string; role: string; kind: 'pdf' | 'image'; sha256: string; bytes: number;
  analysis: string; pages?: { page: number; text: string; analysis: string; method: string }[];
}
export interface Claim { id: string; text: string; source_ids: string[]; status: string; boundary: string }
export interface Point {
  id: string; title: string; feature: string; benefit: string; claim_ids: string[]; status: string;
  visual: string; conditions: string; priority: string;
}
export interface PointsArtifact { summary: string; identity: string; claims: Claim[]; points: Point[]; unknowns: string[] }
export interface Shot {
  id: string; name: string; kind: string; question: string; point_ids: string[]; claim_ids: string[];
  scene: string; camera: string; composition: string; lighting: string; props: string;
  copy: {text: string; claim_ids: string[]}[]; typography: string; reference_asset_id: string;
  aspect_ratio: string; acceptance: string[]; information_gain: string;
}
export interface PlanArtifact { summary: string; visual_system: string; shots: Shot[] }
export interface ProjectOutput {
  id: string; shot_id: string; name: string; plan_version: number; points_version: number; job_id: string;
  prompt?: string; native_pixels?: number[]; human_review: string; human_notes?: string;
  qc: {status: string; report?: string; model?: string}; job?: ImageRecord; inherited_from?: string;
}
export interface ProjectSummary {id: string; title: string; status: string; updated_at: string}
export interface ProductProject extends ProjectSummary {
  revision: number; action: string; created_at: string; sku: string; brief: string; config_id: string;
  image_model_name: string; image_count: number; skill: {id: string; name: string; version_id: string; version_label: string};
  assets: ProjectAsset[]; messages: {id: string; role: string; content: string; at: string}[];
  points: PointsArtifact | null; plan: PlanArtifact | null; points_version: number; plan_version: number;
  plan_points_version: number;
  points_approval: number | null; plan_approval: number | null; approved_point_ids: string[];
  outputs: ProjectOutput[]; error: string; interrupted_action?: string;
  authorization: {receivers: Record<string, string>; purpose: string} | null;
  history: {at: string; kind: string; [key: string]: unknown}[];
}
export const projectStatus: Record<string, string> = {
  draft: '待上传资料', queued: '等待处理', running: 'AI 处理中', waiting_points: '待确认卖点',
  waiting_plan: '待规划 / 确认图需', generating: '制作与质检中', review: '待人工验收', completed: '已验收完成', blocked: '需要处理', cancelled: '已取消',
};
export const roleLabels: Record<string, string> = {
  manual: '说明书 PDF', specification: '规格书 PDF', product_identity: '产品身份图（实拍 / 商品图）',
  owned_artwork: '自有商品图（仅品牌风格）', approved_copy: '已批准文案图（仍需核对资料）',
};
export const evidenceLabels: Record<string, string> = {
  supported: '资料支持', photo_inference: '照片推测', needs_evidence: '待补证', conflict: '资料冲突',
};
export const projectBusy = (p: ProductProject) => ['queued', 'running', 'generating'].includes(p.status);

export async function projectRequest<T>(path = '', init?: RequestInit): Promise<T> {
  const response = await apiFetch(`/api/product-projects${path}`, {cache: 'no-store', ...init});
  const value = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof value?.detail === 'string' ? value.detail : Array.isArray(value?.detail)
    ? value.detail.map((e: {msg?: string}) => e.msg || '输入错误').join('；') : `请求失败（HTTP ${response.status}）`);
  return value as T;
}
export const jsonRequest = (body: unknown, method = 'POST'): RequestInit => ({method, headers: {'Content-Type':'application/json'}, body:JSON.stringify(body)});
