// Evaluate the latest submitted version; historical failures belong to history.
export function productionProgress(project) {
  const images = project.images || [];
  const batches = project.batches || [];
  const latest = batches.at(-1);
  const byId = new Map(images.map(image => [image.id, image]));
  const current = latest ? [...new Set(latest.job_ids)].map(id => byId.get(id)) : images;
  const result = { total: current.length, succeeded: 0, pending: 0, failed: 0, unknown: 0, complete: false };
  for (const image of current) {
    if (!image || ['queued', 'running'].includes(image.status)) result.pending++;
    else if (image.status === 'succeeded') result.succeeded++;
    else if (['failed', 'cancelled'].includes(image.status)) result.failed++;
    else result.unknown++;
  }
  result.complete = result.total > 0 && result.succeeded === result.total;
  return result;
}

export function projectDestination(project) {
  const id = encodeURIComponent(project.id);
  if (project.kind === 'product') return `#/products?project=${id}`;
  if (project.images?.length || project.batches?.length || project.documents?.prompts?.confirmed_at) return `#/studio?project=${id}`;
  return `#/planning?project=${id}&stage=${project.documents?.brief?.confirmed_at ? 'prompts' : 'brief'}`;
}

export function projectStatus(project) {
  if (project.busy) return { key: 'busy', label: '正在执行' };
  if (project.kind === 'product') return project.analysis_confirmed
    ? { key: 'ready', label: '卖点已确认' } : { key: 'draft', label: '待分析 / 确认' };
  const progress = productionProgress(project);
  if (progress.pending) return { key: 'busy', label: `制作中 · ${progress.succeeded}/${progress.total}` };
  if (progress.failed || progress.unknown) return { key: 'attention', label: `待处理 · ${progress.failed + progress.unknown} 张` };
  if (progress.complete) return { key: 'complete', label: `本轮已完成 · ${progress.succeeded} 张` };
  if (project.documents?.prompts?.confirmed_at) return { key: 'ready', label: '待生图' };
  if (project.documents?.brief?.confirmed_at) return { key: 'draft', label: '待编写 / 确认提示词' };
  return { key: 'draft', label: '待编写 / 确认图需' };
}
