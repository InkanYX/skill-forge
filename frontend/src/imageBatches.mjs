// Batch membership comes from persisted submission IDs, never timestamp proximity.
export function imageBatches(items, batches = []) {
  const claimed = new Set();
  const groups = batches.map((batch, index) => {
    const ids = new Set(batch.job_ids);
    const members = items.filter(item => ids.has(item.id));
    members.forEach(item => claimed.add(item.id));
    return { id: batch.execution_id, label: `第 ${index + 1} 版`, created_at: batch.created_at,
      items: members.sort((a, b) => a.task_index - b.task_index) };
  });
  const ungrouped = items.filter(item => !claimed.has(item.id));
  const extra = new Map();
  for (const item of ungrouped) {
    const key = item.execution_profile?.creation_execution_id || 'legacy';
    if (!extra.has(key)) extra.set(key, []);
    extra.get(key).push(item);
  }
  for (const [id, members] of extra) groups.push({ id, label: id === 'legacy' ? '其他历史记录' : '正在提交的新版本',
    created_at: members[0].created_at, items: members.sort((a, b) => a.task_index - b.task_index) });
  return groups.sort((a, b) => b.created_at.localeCompare(a.created_at));
}
