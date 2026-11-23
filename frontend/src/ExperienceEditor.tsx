import { useEffect, useState, type FormEvent } from 'react';
import { creativeRequest, type CreativeCase } from './creativeApi';

export default function ExperienceEditor({ jobId, onDirtyChange, onSavingChange, onSaved }: {
  jobId: string;
  onDirtyChange?: (dirty: boolean) => void;
  onSavingChange?: (busy: boolean) => void;
  onSaved?: (note: CreativeCase) => void;
}) {
  const [title, setTitle] = useState('');
  const [experience, setExperience] = useState('');
  const [issues, setIssues] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true); setLoadError(''); setMessage('');
    creativeRequest<CreativeCase | null>(`cases/${jobId}`).then(note => {
      if (!active) return;
      setTitle(note?.title || ''); setExperience(note?.experience || ''); setIssues(note?.issues || ''); setSaved(!!note);
    }).catch(err => { if (active) setLoadError(err instanceof Error ? err.message : '经验读取失败'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [jobId, attempt]);

  async function save(event: FormEvent) {
    event.preventDefault(); setBusy(true); onSavingChange?.(true); setMessage('');
    try {
      const note = await creativeRequest<CreativeCase>('cases', { job_id: jobId, title: title.trim() || '作品经验', experience, issues });
      setTitle(note.title); setExperience(note.experience); setSaved(true); setMessage('经验已保存，可在作品库筛选“有经验备注”查看。');
      onDirtyChange?.(false); onSaved?.(note);
    } catch (err) { setMessage(err instanceof Error ? err.message : '保存失败'); }
    finally { setBusy(false); onSavingChange?.(false); }
  }

  return <section className="case-editor" aria-label="作品经验">
    <h3>经验备注</h3><p>记录这张图有效的做法或需要改进的地方，方便自己和同事参考。</p>
    {loading && <p role="status">正在读取经验…</p>}
    {loadError && <p className="feedback feedback-error" role="alert">{loadError} <button type="button" className="button-secondary" onClick={() => setAttempt(value => value + 1)}>重试读取</button></p>}
    {!loading && !loadError && <form onSubmit={save} onChange={() => { onDirtyChange?.(true); setMessage(''); }}>
      <fieldset disabled={busy}>
        <div className="form-field"><label>经验内容<textarea required rows={3} maxLength={4000} value={experience} onChange={e => setExperience(e.target.value)} placeholder="例如：增加立柱连接处特写作为参考后，结构更准确。" /></label></div>
        <details><summary>标题与问题记录（可选）</summary>
          <div className="form-field"><label>备注标题<input maxLength={120} value={title} onChange={e => setTitle(e.target.value)} /></label></div>
          <div className="form-field"><label>问题与改进<textarea rows={3} maxLength={4000} value={issues} onChange={e => setIssues(e.target.value)} /></label></div>
        </details>
      </fieldset>
      <button className="button-primary" disabled={busy}>{busy ? '保存中…' : saved ? '更新经验' : '保存经验'}</button>
      <p role="status">{message}</p>
    </form>}
  </section>;
}
