import { useEffect, useState, type MouseEvent } from 'react';
import { creativeRequest } from './creativeApi';

interface Version { id: string; image_url: string | null; status: string; created_at: string; edit_instruction: string }
interface History { ancestors: Version[]; current: Version; children: Version[]; has_more_ancestors: boolean; has_more_children: boolean }
export default function RevisionTrail({ jobId, onNavigate }: { jobId: string; onNavigate?: (event: MouseEvent<HTMLAnchorElement>) => void }) {
  const [history, setHistory] = useState<History>(); const [error, setError] = useState('');
  useEffect(() => { let active = true; setHistory(undefined); setError(''); creativeRequest<History>(`image-jobs/${jobId}/versions`).then(value => { if (active) setHistory(value); }).catch(() => { if (active) setError('版本记录暂时无法读取，可重新打开详情重试。'); }); return () => { active = false; }; }, [jobId]);
  const link = (item: Version, label: string) => <a key={item.id} className="revision-link" href={`#/library?job=${item.id}`} onClick={onNavigate}>{item.image_url && <img src={item.image_url} alt="版本预览" loading="lazy" />}<span><strong>{label}</strong><small>{item.edit_instruction || '最初的制作要求'} · {new Date(item.created_at).toLocaleString('zh-CN')}</small></span></a>;
  return <section className="revision-trail"><h3>修改记录</h3>{error && <p className="feedback feedback-warning">{error}</p>}{history && <>{history.has_more_ancestors && <p>以下显示最近 50 个来源版本。</p>}{history.ancestors.map((item, index) => link(item, index === history.ancestors.length - 1 ? '直接来源' : '更早版本'))}<p className="revision-current">当前作品 · {history.current.edit_instruction || '首次制作'}</p>{history.children.map(item => link(item, item.status === 'succeeded' ? '基于此图的新版本' : '基于此图的修改任务'))}{history.has_more_children && <p>仅展示最近 20 项修改，可在生成记录查找更多结果。</p>}{!history.ancestors.length && !history.children.length && <p>还没有修改记录。满意的构图可以保留，再继续调整细节。</p>}</>}</section>;
}
