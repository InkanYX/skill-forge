import { useEffect, useState, type FormEvent } from 'react';
import { creativeRequest, type CreativeCase } from './creativeApi';
import { projectRequest, type Project } from './creationProjectApi';
import LearningFeedbackFields from './LearningFeedbackFields';

export default function ExperienceEditor({ jobId, onDirtyChange, onSavingChange, onSaved, readOnly = false }: {
  jobId: string; readOnly?: boolean;
  onDirtyChange?: (dirty: boolean) => void; onSavingChange?: (busy: boolean) => void; onSaved?: (note: CreativeCase) => void;
}) {
  const [note, setNote] = useState<CreativeCase>(); const [products, setProducts] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true); const [loadError, setLoadError] = useState('');
  const [attempt, setAttempt] = useState(0); const [busy, setBusy] = useState(false); const [message, setMessage] = useState('');
  const locked = readOnly || note?.can_edit === false;
  useEffect(() => {
    let active = true; setLoading(true); setLoadError(''); setMessage('');
    creativeRequest<CreativeCase>(`cases/${jobId}?feedback=true`).then(value => { if (active) setNote(value); })
      .catch(err => { if (active) setLoadError(err.message); }).finally(() => { if (active) setLoading(false); });
    projectRequest<Project[]>('?kind=product').then(value => { if (active) setProducts(value); }).catch(() => {});
    return () => { active = false; };
  }, [jobId, attempt]);
  function change(value: Partial<CreativeCase>) { setNote(previous => previous ? {...previous, ...value} : previous); setMessage(''); onDirtyChange?.(true); }
  async function save(event: FormEvent) {
    event.preventDefault(); if (!note) return; setBusy(true); onSavingChange?.(true); setMessage('');
    try {
      const value = await creativeRequest<CreativeCase>('cases', {job_id: jobId, title: note.title || '图片反馈',
        experience: note.experience, issues: note.issues, outcome: note.outcome, requested_change: note.requested_change,
        product_id: note.product_id || null, revision: note.revision, learning:note.learning});
      setNote(value); setMessage(value.product_id ? '反馈已保存，可到产品页整理为作图经验。' : '反馈已保存。关联产品后，可汇总为该产品的作图经验。');
      onDirtyChange?.(false); onSaved?.(value);
    } catch (err) { setMessage(err instanceof Error ? err.message : '保存失败'); }
    finally { setBusy(false); onSavingChange?.(false); }
  }
  return <section className="case-editor" aria-label="图片反馈"><h3>图片反馈</h3>
    <p>记录这张图的效果与改进要求，产品经验由运营整理确认后再复用。</p>
    {locked && <p className="shared-readonly">团队共享图片，仅作者或管理员可以修改反馈。</p>}
    {loading && <p role="status">正在读取反馈…</p>}
    {loadError && <p className="feedback feedback-error" role="alert">{loadError} <button onClick={() => setAttempt(value => value + 1)}>重新读取</button></p>}
    {!loading && !loadError && note && <form onSubmit={save}><fieldset disabled={busy || locked}>
      <label>效果评价<select value={note.outcome} onChange={e => change({outcome:e.target.value as CreativeCase['outcome']})}><option value="pending">待评价</option><option value="satisfied">采用，可参考</option><option value="rework">需要修改</option><option value="discarded">淘汰，仅供总结避坑</option></select></label>
      <LearningFeedbackFields note={note} onChange={learning=>change({learning})}/>
      <label>有效的做法<textarea rows={3} maxLength={4000} value={note.experience} onChange={e => change({experience:e.target.value})} placeholder="例如：使用连接处特写作参考后，立柱结构更准确。"/></label>
      <label>存在的问题<textarea rows={3} maxLength={4000} value={note.issues} onChange={e => change({issues:e.target.value})} placeholder="例如：横梁数量不对；文字遮住了主体。"/></label>
      <label>希望如何修改<textarea rows={3} maxLength={4000} value={note.requested_change} onChange={e => change({requested_change:e.target.value})} placeholder="说明应保留什么、调整什么，以及仅适用于本图的要求。"/></label>
      {note.product_locked ? <p>关联产品：{note.product_name}</p> : <label>关联产品（选填）<select value={note.product_id || ''} onChange={e => change({product_id:e.target.value || null})}><option value="">暂不关联产品</option>{products.map(product => <option key={product.id} value={product.id}>{product.title}</option>)}</select></label>}
    </fieldset><button className="button-primary" disabled={busy || locked || (![note.experience,note.issues,note.requested_change,note.learning?.reason||''].some(value => value.trim())&&!Object.values(note.learning?.ratings||{}).some(Boolean))}>{busy ? '保存中…' : '保存反馈'}</button>
      {note.updated_at && <small className="feedback-updated">更新于 {new Date(note.updated_at).toLocaleString('zh-CN')}</small>}
      {message && <p role="status">{message} {note.product_id && <a href={`#/products?project=${note.product_id}`}>查看产品作图经验 →</a>}</p>}
    </form>}
  </section>;
}
