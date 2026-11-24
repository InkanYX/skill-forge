import { apiFetch } from './apiFetch';

export interface SkillVersion {
  id: string; skill_id: string; version_label: string; status: string; compile_level: 'core' | 'full';
  content_sha256: string; compiled_sha256: string; compiled_chars: number; file_count: number;
  total_bytes: number; created_at: string; import_note: string; is_current?: boolean;
}

export interface SkillPackage {
  id: string; name: string; description: string; source: string; owner_id: string | null;
  is_readonly: boolean; created_at: string; updated_at: string; version_count: number;
  can_activate: boolean; can_edit: boolean; current_version: SkillVersion | null;
}

export interface SkillFile {
  path: string; kind: string; size: number; sha256: string; is_text: boolean;
}

export interface SkillFileList { version: SkillVersion; files: SkillFile[]; resources?: SkillFile[] }
export interface SkillText { path: string; offset: number; total_chars: number; content: string; truncated: boolean }

export interface ImportedSkill {
  resource_only?: boolean;
  root: string; name: string; description: string; version_label: string; file_count: number;
  total_bytes: number; content_sha256: string; compiled: { core_chars: number; full_chars: number };
  files: { path: string; kind: string; size: number }[];
  existing: { id: string; name: string; current_label: string | null } | null;
  same_content: boolean; reserved: boolean; is_upgrade: boolean;
}

export interface ImportPreview {
  upload_id: string; skills: ImportedSkill[];
  needs_entry?: boolean; entry_candidates?: {path: string; name: string}[];
  manifest: { present: boolean; ok: boolean; missing: string[]; mismatch: string[]; checked: number; message?: string };
  limits: Record<string, number>;
}

export interface ConfirmResult {
  id: string; name: string;
  status: 'created' | 'version_added' | 'unchanged';
  version: SkillVersion;
}

function detail(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value && typeof value === 'object' && 'detail' in value) {
    const raw = (value as { detail: unknown }).detail;
    if (typeof raw === 'string') return raw;
    if (Array.isArray(raw)) return raw.map(item => (item as { msg?: string }).msg || '输入格式错误').join('；');
  }
  return '请求失败，请稍后重试。';
}

export async function skillPackageRequest<T>(path = '', init?: RequestInit): Promise<T> {
  const response = await apiFetch(`/api/skill-packages${path}`, { cache: 'no-store', ...init });
  const value = await response.json().catch(() => null);
  if (!response.ok) throw new Error(detail(value));
  if (init?.method && init.method !== 'GET') window.dispatchEvent(new Event('skill-forge:skills-changed'));
  return value as T;
}

export function listPackages() {
  return skillPackageRequest<SkillPackage[]>('');
}

export function listVersions(id: string) {
  return skillPackageRequest<SkillVersion[]>(`/${id}/versions`);
}

export function activateVersion(id: string, versionId: string) {
  return skillPackageRequest<SkillPackage>(`/${id}/versions/${versionId}/activate`, { method: 'POST' });
}

export function listFiles(id: string, versionId: string) {
  return skillPackageRequest<SkillFileList>(`/${id}/versions/${versionId}/files`);
}

export function readFile(id: string, versionId: string, path: string) {
  const encoded = path.split('/').map(encodeURIComponent).join('/');
  return skillPackageRequest<SkillText>(`/${id}/versions/${versionId}/files/${encoded}`);
}

export function readResource(id: string, versionId: string, path: string) {
  const encoded = path.split('/').map(encodeURIComponent).join('/');
  return skillPackageRequest<SkillText>(`/${id}/versions/${versionId}/resources/${encoded}`);
}

export function fileUrl(id: string, versionId: string, path: string, download = false) {
  const encoded = path.split('/').map(encodeURIComponent).join('/');
  return `/api/skill-packages/${id}/versions/${versionId}/files/${encoded}${download ? '?download=1' : ''}`;
}

export function forkPackage(id: string) {
  return skillPackageRequest<SkillPackage>(`/${id}/fork`, { method: 'POST' });
}

export function uploadPackage(form: FormData) {
  return skillPackageRequest<ImportPreview>('/import', { method: 'POST', body: form });
}

export function choosePackageEntry(uploadId: string, path: string) {
  return skillPackageRequest<ImportPreview>('/import/entry', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({upload_id: uploadId, path}),
  });
}

export function confirmPackage(uploadId: string, selections: { name: string; root?: string; import_name?: string; description?: string; compile_level: 'core' | 'full' }[]) {
  return skillPackageRequest<ConfirmResult[]>('/import/confirm', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ upload_id: uploadId, selections }),
  });
}

export function importTextSkill(data: { name: string; description?: string; content: string; compile_level?: 'core' | 'full' }) {
  return skillPackageRequest<ConfirmResult>('/import/text', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ compile_level: 'core', ...data }),
  });
}
