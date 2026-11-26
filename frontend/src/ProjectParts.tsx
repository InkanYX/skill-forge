import { useEffect, useRef, useState } from 'react';
import FileDropZone from './FileDropZone';
import { materialUrl, stageNames, type Project } from './creationProjectApi';
import { formatTaskTime } from './imageTaskApi';
import type { UploadProgress } from './useCreationProject';

export function ProjectFeedback({error,notice,loading,onRefresh,busy=false,working=false,dirty=false,updatedAt}:{error:string;notice:string;loading:boolean;onRefresh:()=>void;busy?:boolean;working?:boolean;dirty?:boolean;updatedAt?:string}){
  const [dismissed,setDismissed]=useState('');
  useEffect(()=>setDismissed(''),[error,notice,busy,working]);
  const message=error|| (busy?'正在提交，请稍候…':working?'任务执行中，进度会自动更新；可离开后返回。':notice);
  const visible=!!message&&(busy||message!==dismissed);
  return <><div className="operation-state" aria-label="内容保存状态"><span className={'save-state'+(dirty?' is-dirty':'')}>{busy?'正在处理…':dirty?'有未保存修改':updatedAt?'已保存 · '+formatTaskTime(updatedAt):loading?'正在读取…':'等待填写'}</span>{loading&&updatedAt&&<small>正在同步最新状态…</small>}</div>{visible&&<aside className={'operation-feedback '+(error?'is-error':busy||working?'is-pending':'is-success')} aria-label="操作反馈"><span className="operation-feedback-icon" aria-hidden="true">{error?'!':busy||working?<span className="upload-spinner"/>:'✓'}</span><div role={error?'alert':'status'}><strong>{error?'操作未完成':busy?'正在处理':working?'任务已启动':'操作成功'}</strong><p>{message}</p></div>{error&&<button type="button" disabled={loading||busy} onClick={onRefresh}>刷新状态</button>}{!busy&&<button type="button" aria-label="关闭操作反馈" onClick={()=>setDismissed(message)}>×</button>}</aside>}{loading&&!updatedAt&&<p role="status">正在读取…</p>}</>;
}
export function ProjectMaterials({project,locked,onUpload,onRemove,styleOnly=false,id}:{project:Project;locked:boolean;styleOnly?:boolean;id?:string;onUpload:(files:File[],kind:string,onProgress:UploadProgress)=>Promise<unknown>;onRemove:(id:string)=>void}){
  const [kind,setKind]=useState(styleOnly?'风格参考':'产品实拍');
  const [uploading,setUploading]=useState(0);
  const [uploadError,setUploadError]=useState('');
  const [progress,setProgress]=useState({done:0,total:0,name:''});
  const uploadInFlight=useRef(false);
  const busy=locked||uploading>0;
  async function choose(incoming:File[]){
    if(busy||uploadInFlight.current||!incoming.length)return;
    const allowed=styleOnly?/\.(png|jpe?g|webp)$/i:/\.(pdf|png|jpe?g|webp)$/i;
    const rejected:string[]=[];const files:File[]=[];
    for(const file of incoming){
      if(!allowed.test(file.name)){rejected.push(`${file.name}（格式不支持）`);continue;}
      if(file.size>20*1024*1024){rejected.push(`${file.name}（超过 20 MB）`);continue;}
      files.push(file);
    }
    setUploadError(rejected.length?`未上传 ${rejected.length} 个文件：${rejected.slice(0,3).join('、')}${rejected.length>3?' 等':''}`:'');
    if(!files.length)return;
    uploadInFlight.current=true;
    setUploading(files.length);
    setProgress({done:0,total:files.length,name:files[0].name});
    try{const result=await onUpload(files,kind,(done,total,name)=>setProgress({done,total,name}));if(!result)setUploadError('上传未完成，请先核对已上传资料，再补传剩余文件。');}
    catch{setUploadError('上传失败，请检查文件后重试。');}
    finally{uploadInFlight.current=false;setUploading(0);}
  }
  return <section className="guided-card" id={id} aria-busy={uploading>0}><h3>{styleOnly?'本次素材与风格参考':'产品资料'}</h3><p>{styleOnly?'产品素材沿用已确认的分析。可补充风格和排版参考图。':'上传说明书、规格书、实拍和产品图，供分析与后续制作共同使用。'}</p>
    <div className="guided-material-list">{project.materials.map(item=><article key={item.id}><a href={materialUrl(project.id,item.id)} target="_blank" rel="noreferrer">{item.media_type.startsWith('image/')&&<img src={materialUrl(project.id,item.id)+'?preview=true'} alt={item.name} loading="lazy"/>}<strong>{item.name}</strong></a><small>{item.kind}{item.media_type==='application/pdf'?' · '+item.pages+' 页':''}</small>{(!styleOnly||['风格参考','排版参考'].includes(item.kind))&&<button type="button" disabled={busy} onClick={()=>onRemove(item.id)}>移除</button>}</article>)}</div>
    {!project.materials.length&&uploading===0&&<p>还没有上传资料。</p>}
    <div className="material-upload-block"><span className="material-upload-title">上传资料</span><div className="material-uploader"><select aria-label="资料类型" title="资料类型" value={kind} disabled={busy} onChange={e=>setKind(e.target.value)}>{(styleOnly?['风格参考','排版参考']:['说明书','规格书','产品实拍','产品图','结构细节','其他']).map(value=><option key={value}>{value}</option>)}</select></div><FileDropZone disabled={busy} accept={styleOnly?'.png,.jpg,.jpeg,.webp':'.pdf,.png,.jpg,.jpeg,.webp'} hint={styleOnly?'支持多张 PNG、JPG、WebP，每张不超过 20 MB':'支持多个 PDF、PNG、JPG、WebP，每个不超过 20 MB'} onFiles={files=>void choose(files)}/></div>
    {uploading>0&&<div className="upload-progress" role="status" aria-live="polite"><span className="upload-spinner" aria-hidden="true"/><span>已上传 {progress.done} / {progress.total} · {progress.name}</span><progress value={progress.done} max={progress.total} aria-label="资料上传进度"/></div>}
    {uploadError&&<p className="feedback feedback-warning" role="alert">{uploadError}</p>}
    <small>单份最多 20 MB，每个产品或方案最多 30 份、合计 100 MB。PDF 最多 100 页。</small>
  </section>;
}
export function ProjectHistory({project,stages}:{project:Project;stages:('analysis'|'brief'|'prompts')[]}){
  const values=project.history.filter(item=>stages.includes(item.stage));
  return values.length?<details className="guided-card"><summary>历史版本 · {values.length} 份</summary>{values.slice().reverse().map(doc=><details key={doc.id}><summary>{stageNames[doc.stage]} · 版本 {doc.version} · {formatTaskTime(doc.created_at)}</summary><pre>{JSON.stringify(doc.content,null,2)}</pre></details>)}</details>:null;
}
export function ProjectLog({project,stages}:{project:Project;stages:('analysis'|'brief'|'prompts'|'images')[]}){
  const values=project.executions.filter(item=>stages.includes(item.stage));
  if(!values.length)return null;
  const labels:Record<string,string>={queued:'排队中',running:'执行中',succeeded:'已完成',failed:'失败',unknown:'结果待确认'};
  return <details className="guided-card guided-execution-log"><summary>运行日志 · {values.length} 次</summary>{values.slice().reverse().map(item=><details key={item.id} open={['failed','unknown'].includes(item.status)}><summary>{stageNames[item.stage]} · {labels[item.status]}<time>{formatTaskTime(item.created_at)}</time></summary>{item.error&&<p className="feedback feedback-error">{item.error}</p>}{item.output.diagnostic&&Object.keys(item.output.diagnostic).length>0&&<pre>{JSON.stringify(item.output.diagnostic,null,2)}</pre>}{item.output.trace&&<><p>已使用技能：{item.output.trace.used_skills?.map(skill=>skill.name).join('、')||'查看读取记录'}</p>{item.output.trace.materials?.map((value,i)=><p key={i}>{value.name} · 第 {value.page} 页 · {value.method==='image'?'查看图片':'读取文字'}</p>)}<details><summary>技能文件读取记录</summary>{item.output.trace.files?.map((file,i)=><p key={i}>{file.path}</p>)}</details></>}</details>)}</details>;
}
