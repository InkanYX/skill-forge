export interface Product {
  id: string; sku: string; name: string; category: string; dimensions: string; color: string;
  facts: string; notes: string; revision: number; updated_at: string;
}
export interface ProductAsset { id: string; product_id: string; name: string; kind: string; image_url: string }
export interface ProductSnapshot extends Partial<Product> { asset?: ProductAsset }
export function productValues(product?: Product): Record<string, string> {
  return { 产品名称: product?.name || '', 产品: product?.name || '', SKU: product?.sku || '', 颜色: product?.color || '', 尺寸: product?.dimensions || '', 产品尺寸: product?.dimensions || '', 材质与结构: product?.facts || '' };
}
export async function uploadAsset(productId: string, file: File, kind: string): Promise<ProductAsset> {
  const body = new FormData(); body.set('asset_id', crypto.randomUUID()); body.set('image', file); body.set('kind', kind);
  const response = await fetch(`/api/products/${productId}/assets`, { method: 'POST', body, signal: AbortSignal.timeout(60000) });
  const value = await response.json();
  if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '素材上传失败，请检查文件。');
  return value;
}
