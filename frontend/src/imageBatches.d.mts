import type { ImageRecord } from './imageTaskApi';
export interface ImageBatch { execution_id: string; job_ids: string[]; created_at: string }
export function imageBatches(items: ImageRecord[], batches?: ImageBatch[]): {
  id: string; label: string; created_at: string; items: ImageRecord[];
}[];
