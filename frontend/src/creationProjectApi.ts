import { apiFetch } from './apiFetch';
import type { ImageRecord } from './imageTaskApi';
import type { DrawingExperience } from './ProductExperience';

export type Stage = 'analysis' | 'brief' | 'prompts';
export const stageNames: Record<Stage | 'materials' | 'images', string> = { materials: '产品资料', analysis: '产品卖点', brief: '整套图需', prompts: '图片提示词', images: '图片制作' };
export interface Material { id: string; name: string; kind: string; media_type: string; pages: number; size: number }
export interface ShotDesign {style:string;composition:string;camera:string;depth:string;lighting:string;typography:string;rationale:string}
export interface Shot { id: string; name: string; objective: string; selling_point: string; content: string; layout: string; copy: string; notes: string; size: string; reference_ids: string[]; design?:ShotDesign }
export interface Prompt { shot_id: string; prompt: string; reference_ids: string[] }
export interface VisualStyle { preset: string; variation: 'steady'|'balanced'|'rich'; density: 'low'|'medium'|'high'; palette: string; campaign_treatment?:'adaptive'|'scene_editorial'|'light_gold' }
export interface VisualStyleSnapshot {version:string;selection:VisualStyle;name:string;rules:string;checks:string[]}
export interface LearningSettings {enabled:boolean;category:string;image_type:'any'|'listing'|'a_plus'|'detail';device:'any'|'desktop'|'mobile';excluded_ids:string[]}
export type BriefPlanningMode='optimize'|'replan'|'directed';
export interface BriefPlanningReport {mode:BriefPlanningMode;label:string;direction:string;history_count:number;summary:string;protected_slots:number[];warnings:string[];method:string;comparisons:{project_id:string;project_title:string;document_id:string;version:number;same_slots:number[];compared_slots:number;same_slot_ratio:number;reused_theme_count:number}[]}
export interface ResearchSettings {enabled:boolean;marketplace:string;own_asin:string;competitor_asins:string[];reviews_per_asin:number}
export interface ResearchReview {id:string;asin:string;role:'own'|'competitor';title:string;text:string;star:number|null;date:string;variant:string;source_id:string}
export interface ResearchReport {id:string;fingerprint:string;settings:ResearchSettings;created_at:string;updated_at:string;status:'ready'|'partial';cache_hit:boolean;planned_calls:number;review_count:number;warnings:string[];reviews:ResearchReview[];connection_error?:{message:string;phase?:string;error_type?:string;http_status?:number;elapsed_seconds?:number;business_query_started:boolean};sources:{id:string;tool:string;arguments:Record<string,unknown>;status:string;collected_at:string|null;data:unknown;error?:string|null}[]}
export interface ReviewMention {review_id:string;sentiment:'positive'|'negative'|'neutral'|'mixed';quote:string}
export interface ReviewGroupMetrics {sample_count:number;reviewed_count:number;mentions:number;mention_rate:number|null;positive:number;negative:number;neutral:number;mixed:number}
export interface ReviewMetrics {version:number;snapshot_id:string|null;status:'complete'|'partial'|'unannotated';groups:Record<'all'|'own'|'competitor',ReviewGroupMetrics>;own_negative_review_ids:string[]}
export interface RankedSellingPoint {id:string;title:string;priority:'P1'|'P2'|'P3'|'VERIFY';buyer_need:string;reason:string;product_evidence:string;material_ids:string[];uses_product_description:boolean;review_ids:string[];reviewed_review_ids?:string[];review_mentions?:ReviewMention[];review_metrics?:ReviewMetrics|null;display_suggestion:string;expression_limits:string}
export interface DocumentContent { facts?: string; selling_points?: string; questions?: string; market_summary?:string;ranked_selling_points?:RankedSellingPoint[];research_snapshot?:ResearchReport;art_direction?: string; planning_summary?:string; shots?: Shot[]; prompts?: Prompt[] }
export interface ProjectDocument { id: string; version: number; content: DocumentContent; confirmed_at: string | null }
export interface AnalysisPipeline {phase:'materials'|'research'|'reviews'|'ranking'|'saving'|'completed';status:'running'|'failed'|'completed';completed_batches:number;total_batches:number;document_id:string|null;updated_at:string;error:string;can_resume:boolean;materials_saved:boolean}
export interface Project {
  id: string; title: string; revision: number; stage: Stage | 'images'; busy: boolean; created_at: string; updated_at: string;
  kind: 'product' | 'plan' | 'legacy'; source_product_id: string | null; analysis_confirmed: boolean; can_edit: boolean;
  legacy_product_id?: string | null;
  drawing_experience?: Record<string, DrawingExperience[]>;
  visual_style_snapshot?: VisualStyleSnapshot|null;
  layout_warnings?: string[];
  mobile_source?: {project_id:string; batch_id:string; job_ids:string[]} | null;
  case_reference?: {id:string;title:string;guidance:string;style:string} | null;
  team_source?: {id:string;version:number;author_id:string;title:string}|null;
  research_settings?:ResearchSettings;market_research?:ResearchReport|null;
  analysis_pipeline?:AnalysisPipeline|null;
  source?: { product_id: string; title: string; document_id: string; version: number }; source_updated?: boolean;
  settings: { goal: string; style: string; visual_style?:VisualStyle|null; learning?:LearningSettings; image_count: number; planning_model: string; image_model: string; market: string; language: string; audience: string; selected_selling_points: string; sku?: string };
  skill: Record<string, unknown>; documents: Record<Stage, ProjectDocument | null>;
  materials: Material[]; images: ImageRecord[];
  messages: { role: string; stage: string; content: string; created_at: string }[];
  executions: { id: string; stage: Stage | 'images'; status: string; error: string; created_at: string; updated_at: string; output: {research_progress?:{snapshot_id:string;current:string;completed:number;total:number;warnings:string[]};diagnostic?: Record<string, unknown>; trace?: { document_id?:string;brief_planning?:BriefPlanningReport|null;used_skills?: { name: string }[]; materials?: { name: string; page: number; method: string }[]; files?: { path: string }[] } } }[];
  history: (ProjectDocument & { stage: Stage; created_at: string })[];
  batches: { execution_id: string; job_ids: string[]; created_at: string; version_number?: number }[];
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
