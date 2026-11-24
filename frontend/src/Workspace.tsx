import { apiFetch } from './apiFetch';
import { useEffect, useState } from 'react';
import TaskCancel from './TaskCancel';
import SystemStatus from './SystemStatus';
import WorkflowOverview from './WorkflowOverview';

interface JobSummary { id: string; title: string; sku: string; model_name: string; status: string; message: string; brief: string; created_at: string; image_url: string | null; set_id: string | null; set_name: string }
interface Overview {
  updated_at: string; jobs: Record<string, number>;
  resources: { products: number; templates: number; skills: number; cases: number; model_configs: number; available_models: number };
  today: { date: string; timezone: string; submitted: number; completed: number };
  active_jobs: JobSummary[]; attention_jobs: JobSummary[]; recent_images: JobSummary[];
  recent_products: { id: string; sku: string; name: string }[];
  recent_templates: { id: string; name: string; purpose: string; revision: number }[];
}
const labels: Record<string, string> = { queued: '排队中', running: '生成中', failed: '未完成', unknown: '结果待确认' };
export default function Workspace() {
  const [data, setData] = useState<Overview>(); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0); const [notice, setNotice] = useState(''); const [diagnostics, setDiagnostics] = useState(false);
  useEffect(() => {
    let active = true; let timer: number; let controller: AbortController;
    setLoading(true);
    async function load() {
      controller = new AbortController(); const timeout = window.setTimeout(() => controller.abort(), 12000);
      try {
        const response = await apiFetch('/api/workspace', { signal: controller.signal, cache: 'no-store' }); const value = await response.json();
        if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '工作台数据读取失败。');
        if (active) { setData(value); setError(''); }
      } catch (err) { if (active) setError(err instanceof Error && err.name !== 'AbortError' ? err.message : '读取超时，请检查本机后端服务。'); }
      finally { window.clearTimeout(timeout); if (active) { setLoading(false); timer = window.setTimeout(load, 15000); } }
    }
    void load(); return () => { active = false; window.clearTimeout(timer); controller?.abort(); };
  }, [attempt]);
  const stats = [{ key: 'queued', label: '排队中', hint: '尚未开始，可取消' }, { key: 'running', label: '生成中', hint: '查看当前制作进度' }, { key: 'succeeded', label: '累计完成', hint: '查看与导出图片' }, { key: 'unknown', label: '结果待确认', hint: '先核对服务商记录' }];
  return <section className="workspace-home"><div className="page-heading"><div><p className="eyebrow">YOUR CREATIVE WORKSPACE</p><h1>我的工作台</h1><p className="subtitle">从产品素材开始制作，让有效的方法和满意的作品留得下来。</p></div><div className="workspace-shortcuts"><a className="button-primary" href="#/products?new=1">新建产品</a><a className="button-secondary" href="#/studio">直接生图</a></div></div>
    <WorkflowOverview />
    <div className="workspace-refresh"><p role="status">{data ? `北京时间 ${data.today.date} · 今日提交 ${data.today.submitted} 项，完成 ${data.today.completed} 张` : loading ? '正在读取工作台…' : '工作台数据暂不可用'}</p><button type="button" className="button-secondary" disabled={loading} onClick={() => setAttempt(value => value + 1)}>{loading ? '读取中…' : '刷新数据'}</button></div>
    {error && <p className="feedback feedback-error" role="alert">{error}{data ? ' 当前显示上次成功读取的数据。' : ' 请展开底部“服务状态”检查连接。'}</p>}{notice && <p className="feedback feedback-success" role="status">{notice}</p>}
    <div className="workspace-stats">{stats.map(item => <a href={`#/library?status=${item.key}`} key={item.key} className="workspace-stat"><span>{item.label}</span><strong>{data ? data.jobs[item.key] || 0 : '—'}</strong><small>{item.hint}</small></a>)}</div>
    <div className="workspace-columns"><section className="workspace-panel"><div className="section-heading"><h2>进行中的任务</h2><a href="#/library?status=all">查看全部任务</a></div>{data?.active_jobs.map(job => <article key={job.id} className="workspace-task"><div className="workspace-task-top"><a href={`#/library?job=${job.id}`}><strong>{job.title}</strong><small>{job.sku || job.model_name} · {new Date(job.created_at).toLocaleString('zh-CN')}</small></a><span className={`job-status job-${job.status}`}>{labels[job.status]}</span></div><p>{job.message}</p><TaskCancel jobId={job.id} status={job.status} onChanged={reply => { setNotice(reply.status === 'cancelled' ? reply.message || '已取消排队。' : ''); setAttempt(value => value + 1); }} /></article>)}{data && !data.active_jobs.length && <p className="workspace-empty">当前没有排队或生成中的任务，可以开始新的创作。</p>}{!data && <p className="workspace-empty">{loading ? '读取任务中…' : '连接恢复后展示任务。'}</p>}</section>
    <section className="workspace-panel"><div className="section-heading"><h2>需要关注</h2><a href="#/library?status=failed">查看未完成任务</a></div>{data?.attention_jobs.map(job => <a href={`#/library?job=${job.id}`} key={job.id} className="workspace-attention"><div className="workspace-task-top"><strong>{job.title}</strong><span className={`job-status job-${job.status}`}>{labels[job.status]}</span></div><p>{job.message}</p><small>{job.status === 'unknown' ? '先核对服务商生成和计费记录，避免重复提交。' : '查看制作记录，检查模型、参数或素材后再安排创作。'}</small></a>)}{data && !data.attention_jobs.length && <p className="workspace-empty">暂无未完成或结果待确认的任务。</p>}{!data && <p className="workspace-empty">连接后展示需要处理的任务。</p>}</section></div>
    <section className="workspace-panel"><div className="section-heading"><h2>最近生成结果</h2><a href="#/library">打开生成记录</a></div><div className="workspace-images">{data?.recent_images.map(job => <a key={job.id} href={`#/library?job=${job.id}`}><img src={job.image_url!} alt={job.title} loading="lazy" /><strong>{job.title}</strong><small>{job.sku || job.model_name}</small></a>)}</div>{data && !data.recent_images.length && <p className="workspace-empty">完成第一张图片后，会自动展示在这里。<a href="#/studio">去创作图片</a></p>}{!data && <p className="workspace-empty">连接后展示最近完成的图片。</p>}</section>
    <p className="form-footnote">{data ? `数据更新时间：${new Date(data.updated_at).toLocaleString('zh-CN')}。` : ''}工作台每 15 秒自动刷新。</p>
    <details className="workspace-diagnostics" onToggle={e => setDiagnostics(e.currentTarget.open)}><summary>服务状态 · 排查连接问题</summary>{diagnostics && <SystemStatus />}</details>
  </section>;
}
