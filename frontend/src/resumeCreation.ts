export interface ResumePoint { route: string; title: string; label: string; updatedAt: string }
const prefix = 'skill-forge:resume:v1:';
const memory = new Map<string, ResumePoint>();

export function creationLocation(route: string): Omit<ResumePoint, 'updatedAt'> | null {
  const [path, query] = route.split('?');
  const params = new URLSearchParams(query);
  const id = params.get('project');
  const base = id ? `?project=${encodeURIComponent(id)}` : '';
  if (path === '#/products' && id) {
    const tab=params.get('tab');
    return { route: path + base + (tab==='materials'||tab==='plans'?'&tab='+tab:''), title: '产品资料', label: tab==='plans'?'该产品的图片策划':'产品资料与卖点' };
  }
  if (path === '#/planning' && id && !params.has('view')) {
    const stage = params.get('stage') === 'brief' ? 'brief' : params.get('stage') === 'prompts' ? 'prompts' : '';
    return { route: path + base + (stage ? '&stage=' + stage : ''), title: '图片策划', label: stage === 'prompts' ? '图片提示词' : '整套图需' };
  }
  if (path === '#/studio') {
    if (id) return { route: path + base, title: '图片创作', label: '图片制作' };
    for (const key of ['task', 'run']) {
      const value = params.get(key);
      if (value) return { route: path + '?' + key + '=' + encodeURIComponent(value), title: '图片创作', label: '生成进度与结果' };
    }
  }
  if (path === '#/edit' && params.get('source')) return { route: path + '?source=' + encodeURIComponent(params.get('source')!), title: '继续修改图片', label: '图片修改' };
  return null;
}

export function readResume(userId: string): ResumePoint | null {
  try {
    const value = JSON.parse(localStorage.getItem(prefix + userId) || 'null');
    if (value && creationLocation(value.route) && typeof value.title === 'string' && typeof value.label === 'string' && typeof value.updatedAt === 'string') return value;
  } catch { /* Storage may be disabled; keep navigation usable in this session. */ }
  return memory.get(userId) || null;
}

export function rememberCreation(userId: string, route: string, title?: string): void {
  const location = creationLocation(route);
  if (!location) return;
  const previous = readResume(userId);
  const sameProject = new URLSearchParams(previous?.route.split('?')[1]).get('project');
  const project = new URLSearchParams(location.route.split('?')[1]).get('project');
  const value = { ...location, title: title || (previous && (previous.route === location.route || (project && project === sameProject)) ? previous.title : location.title), updatedAt: new Date().toISOString() };
  memory.set(userId, value);
  try { localStorage.setItem(prefix + userId, JSON.stringify(value)); } catch { /* Session fallback above. */ }
}
