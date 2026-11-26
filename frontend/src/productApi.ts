import { createRequestId } from './requestId';
import { apiFetch } from './apiFetch';
export interface Product {
  owner_id?: string | null; can_edit?: boolean;
  id: string; sku: string; name: string; category: string; dimensions: string; color: string;
  facts: string; notes: string; revision: number; updated_at: string;
}
export interface ProductAsset { id: string; product_id: string; name: string; kind: string; image_url: string }
export interface ProductSnapshot extends Partial<Product> { asset?: ProductAsset }
type ProductVariableField = 'name' | 'sku' | 'color' | 'dimensions' | 'facts';
export const PRODUCT_VARIABLE_FIELDS: Record<string, ProductVariableField> = {
  产品名称: 'name', 产品: 'name', SKU: 'sku', 颜色: 'color', 尺寸: 'dimensions', 产品尺寸: 'dimensions', 材质与结构: 'facts',
};
export function productValues(product?: Product): Record<string, string> {
  return Object.fromEntries(Object.entries(PRODUCT_VARIABLE_FIELDS).map(([key, field]) => [key, product?.[field] || '']));
}
export async function uploadAsset(productId: string, file: File, kind: string): Promise<ProductAsset> {
  const body = new FormData(); body.set('asset_id', createRequestId()); body.set('image', file); body.set('kind', kind);
  const response = await apiFetch(`/api/products/${productId}/assets`, { method: 'POST', body, signal: AbortSignal.timeout(60000) });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '素材上传失败，请检查文件。');
  return value;
}
