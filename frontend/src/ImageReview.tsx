import { useEffect, useState, type FormEvent } from 'react';
import type { ImageRecord } from './imageTaskApi';
export default function ImageReview({item,onSaved,onDirtyChange,onSavingChange}:{item:ImageRecord;onSaved:()=>void;onDirtyChange:(dirty:boolean)=>void;onSavingChange:(busy:boolean)=>void}){
  const [status,setStatus]=useState(item.execution_result?.review?.status||'pending');
  const [notes,setNotes]=useState(item.execution_result?.review?.notes||'');
  const [dirty,setDirty]=useState(false);
  useEffect(()=>onDirtyChange(dirty),[dirty,onDirtyChange]);
  const [busy,setBusy]=useState(false);const [message,setMessage]=useState('');
  async function save(event:FormEvent){event.preventDefault();setBusy(true);onSavingChange(true);setMessage('');const body=new FormData();body.set('status',status);body.set('notes',notes);
    try{const response=await fetch(`/api/image-jobs/${item.id}/review`,{method:'POST',body,signal:AbortSignal.timeout(12000)});const value=await response.json();if(!response.ok)throw new Error(value.detail||'保存失败');setMessage('检查记录已保存。');setDirty(false);onSaved();}catch(err){setMessage(err instanceof Error?err.message:'保存失败。');}finally{setBusy(false);onSavingChange(false);}}
  return <form onSubmit={save} className="image-review"><h3>人工检查</h3><p className="form-footnote">对照参考图检查结构、比例、颜色和文字；记录检查结论。</p><div className="form-field"><label htmlFor={`review-status-${item.id}`}>检查状态</label><select id={`review-status-${item.id}`} value={status} onChange={e=>{setStatus(e.target.value);setDirty(true);}}><option value="pending">待检查</option><option value="passed">检查通过</option><option value="rework">需要修改</option></select></div><div className="form-field"><label htmlFor={`review-notes-${item.id}`}>检查备注</label><textarea id={`review-notes-${item.id}`} value={notes} maxLength={4000} rows={3} onChange={e=>{setNotes(e.target.value);setDirty(true);}} /></div><button className="button-secondary" disabled={busy}>{busy?'保存中…':'保存检查记录'}</button>{message&&<p role="status">{message}</p>}</form>;
}
