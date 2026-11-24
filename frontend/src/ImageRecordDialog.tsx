import { apiFetch } from './apiFetch';
import { useEffect, useRef, useState } from 'react';
import { formatImageSize } from './ImageSizePicker';
import TaskCancel from './TaskCancel';
import ExperienceEditor from './ExperienceEditor';
import { DrawingExperienceUsed } from './ProductExperience';
import RevisionTrail from './RevisionTrail';
import SkillExecutionInfo from './SkillExecutionInfo';
import { taskLabels as labels, type ImageRecord } from './imageTaskApi';

export default function ImageRecordDialog({ item, onClose, onChanged }: { item?: ImageRecord; onClose: () => void; onChanged: () => void }) {
  const [selected, setSelected] = useState<ImageRecord>();
  const [caseDirty, setCaseDirty] = useState(false); const [caseBusy, setCaseBusy] = useState(false);
  const [favoriteBusy, setFavoriteBusy] = useState(false); const [favoriteError, setFavoriteError] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => { setSelected(item); setCaseDirty(false); setFavoriteError(''); }, [item]);
  useEffect(() => { if (selected) { if (!dialog.current?.open) dialog.current?.showModal(); } else dialog.current?.close(); }, [selected?.id]);
  function close() {
    if (caseBusy || favoriteBusy || (caseDirty && !window.confirm('图片反馈尚未保存，确定关闭吗？'))) return false;
    setSelected(undefined); setCaseDirty(false); onClose(); return true;
  }
  async function toggleFavorite() {
    if (!selected || favoriteBusy) return;
    const id = selected.id; const form = new FormData(); form.set('favorite', String(!selected.is_favorite));
    setFavoriteBusy(true); setFavoriteError('');
    try {
      const response = await apiFetch(`/api/image-jobs/${id}/favorite`, { method: 'POST', body: form, signal: AbortSignal.timeout(12000) });
      const value = await response.json();
      if (!response.ok) throw new Error(typeof value.detail === 'string' ? value.detail : '收藏未完成。');
      setSelected(previous => previous ? { ...previous, is_favorite: value.is_favorite } : previous); onChanged();
    } catch (err) { setFavoriteError(err instanceof Error ? err.message : '收藏未完成。'); }
    finally { setFavoriteBusy(false); }
  }
  return (
    <dialog ref={dialog} className="artwork-dialog" aria-labelledby="artwork-detail-title" onCancel={e => { e.preventDefault(); close(); }}>
      {selected && <><div className="product-dialog-heading"><h2 id="artwork-detail-title">图片详情</h2><button className="button-secondary" disabled={caseBusy || favoriteBusy} onClick={close}>关闭</button></div><div className="artwork-detail-layout"><div>
        {selected.image_url ? selected.parent_job_id && selected.reference_url ? <div className="revision-comparison"><figure><figcaption>修改前</figcaption><a href={selected.reference_url} target="_blank" rel="noreferrer"><img src={selected.reference_url} alt="修改前的来源图片" /></a></figure><figure><figcaption>修改后</figcaption><a href={selected.image_url} target="_blank" rel="noreferrer"><img src={selected.preview_url || selected.image_url} alt="修改后的新版本" /></a></figure></div> : <a href={selected.image_url} target="_blank" rel="noreferrer"><img className="artwork-detail-image" src={selected.preview_url || selected.image_url} alt="生成作品大图" /></a> : <div className="result-placeholder"><strong>{labels[selected.status]}</strong><p>{selected.message}</p></div>}
        <div className="result-actions">{selected.image_url && <a className="button-primary" href={`${selected.image_url}?download=true`}>下载 PNG</a>}{selected.reference_url && <a className="button-secondary" href={selected.reference_url} target="_blank" rel="noreferrer">查看参考图</a>}</div>
        <TaskCancel key={selected.id} jobId={selected.id} status={selected.status} onChanged={reply => { if (reply.status === "cancelled") setSelected(previous => previous ? { ...previous, status: "cancelled", message: reply.message || "已取消排队。" } : previous); onChanged(); }} />
        {selected.image_url && <p><a className="button-primary" href={`#/edit?source=${selected.id}`} onClick={e => { if (!close()) e.preventDefault(); }}>继续修改这张图</a></p>}
        {selected.status === 'unknown' && <p className="feedback feedback-warning">请先核对服务商的生成与计费记录。本任务不会自动重试。</p>}
        {selected.status === 'succeeded' && <><button type="button" className="button-secondary" aria-pressed={selected.is_favorite} disabled={favoriteBusy || selected.can_edit === false} onClick={toggleFavorite}>{favoriteBusy ? '保存中…' : selected.is_favorite ? '取消收藏' : '收藏这张图'}</button>{favoriteError && <p className="feedback feedback-error" role="alert">{favoriteError}</p>}<ExperienceEditor readOnly={selected.can_edit === false} key={selected.id} jobId={selected.id} onDirtyChange={setCaseDirty} onSavingChange={setCaseBusy} onSaved={note => { setSelected(previous => previous ? { ...previous, case_id: note.id } : previous); onChanged(); }} /></>}
      </div><div className="artwork-record"><span className={`job-status job-${selected.status}`}>{labels[selected.status]}</span><dl className="job-details"><div><dt>模型</dt><dd>{selected.config_name} · {selected.model_name}</dd></div><div><dt>创建时间</dt><dd>{new Date(selected.created_at).toLocaleString('zh-CN')}</dd></div><div><dt>制作方式</dt><dd>{selected.mode === 'edit' ? '参考图编辑' : '文字生图'}</dd></div><div><dt>{selected.execution_profile?.backend ? "目标画幅" : "请求尺寸"}</dt><dd>{selected.execution_profile?.backend ? formatImageSize(selected.size) : selected.size === "default" ? "自动（未指定尺寸）" : `${selected.size.replace("x", " × ")} 像素`}</dd></div></dl>
        <SkillExecutionInfo item={selected} />
        <DrawingExperienceUsed value={selected.execution_profile?.drawing_experience} />
        <details open><summary>完整制作要求</summary><p className="case-prompt">{selected.prompt}</p></details>
        {selected.product_snapshot.id && <details><summary>当时的产品资料 · {selected.product_snapshot.sku}</summary><p>{selected.product_snapshot.name} · 版本 {selected.product_snapshot.revision}</p><p>{selected.product_snapshot.color} · {selected.product_snapshot.dimensions}</p><p>{selected.product_snapshot.facts}</p><p>{selected.product_snapshot.notes}</p></details>}
        {selected.template_snapshot.id && <details><summary>当时的模板 · {selected.template_snapshot.name}</summary><p>版本 {selected.template_snapshot.revision}</p><p>{Object.entries(selected.template_snapshot.values || {}).map(([key, value]) => `${key}：${value}`).join('；')}</p><p>{selected.template_snapshot.prompt}</p><p>{selected.template_snapshot.skill_name && `Skill：${selected.template_snapshot.skill_name} · 版本 ${selected.template_snapshot.skill_revision}`}</p>{selected.template_snapshot.skill && <p>Skill：{selected.template_snapshot.skill}</p>}<p>{selected.template_snapshot.notes}</p></details>}
        {selected.edit_instruction && <p>本次修改：{selected.edit_instruction}</p>}
        {selected.set_id && <p>套图：{selected.set_name} · {selected.shot_name} <a className="button-secondary" href={`#/sets?set=${selected.set_id}`} onClick={e => { if (!close()) e.preventDefault(); }}>查看整套图片</a></p>}
        <RevisionTrail jobId={selected.id} onNavigate={e => { if (!close()) e.preventDefault(); }} />
      </div></div></>}
    </dialog>
  );
}
