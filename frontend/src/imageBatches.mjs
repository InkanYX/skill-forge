// Batch membership comes from persisted submission IDs, never timestamp proximity.
export function imageBatches(items, batches = []) {
  const claimed = new Set();
  const byId = new Map(items.map(item => [item.id, item]));
  const groups = batches.map((batch, index) => {
    const members = batch.job_ids.map(id => byId.get(id)).filter(Boolean);
    const history = Object.values(batch.retry_history || {}).flat().map(id => byId.get(id)).filter(Boolean);
    members.forEach(item => claimed.add(item.id));
    history.forEach(item => claimed.add(item.id));
    return { id: batch.execution_id, label: `第 ${batch.version_number || index + 1} 版`, created_at: batch.created_at,
      items: members, history };
  });
  const ungrouped = items.filter(item => !claimed.has(item.id));
  const extra = new Map();
  for (const item of ungrouped) {
    const key = item.execution_profile?.creation_execution_id || 'legacy';
    if (!extra.has(key)) extra.set(key, []);
    extra.get(key).push(item);
  }
  for (const [id, members] of extra) groups.push({ id, label: id === 'legacy' ? '其他历史记录' : '正在提交的新版本',
    created_at: members[0].created_at, items: members.sort((a, b) => a.task_index - b.task_index), history: [] });
  return groups.sort((a, b) => b.created_at.localeCompare(a.created_at));
}
