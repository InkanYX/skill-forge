import { useState } from 'react';
import { materialUrl, stageNames, type Project } from './creationProjectApi';
import { formatTaskTime } from './imageTaskApi';

export function ProjectFeedback({error,notice,loading,onRefresh}:{error:string;notice:string;loading:boolean;onRefresh:()=>void}){
  return <>{error&&<p className="feedback feedback-error" role="alert">{error} <button type="button" onClick={onRefresh}>刷新</button></p>}{notice&&<p className="feedback feedback-success" role="status">{notice}</p>}{loading&&<p role="status">正在读取…</p>}</>;
}
export function ProjectMaterials({project,locked,onUpload,onRemove,styleOnly=false}:{project:Project;locked:boolean;styleOnly?:boolean;onUpload:(files:File[],kind:string)=>Promise<unknown>;onRemove:(id:string)=>void}){
  const [kind,setKind]=useState(styleOnly?'风格参考':'产品实拍');
  return <section className="guided-card"><h3>{styleOnly?'本次素材与风格参考':'产品资料'}</h3><p>{styleOnly?'产品素材沿用已确认的分析。可补充风格和排版参考图。':'上传说明书、规格书、实拍和产品图，供分析与后续制作共同使用。'}</p>
    <div className="guided-material-list">{project.materials.map(item=><article key={item.id}><a href={materialUrl(project.id,item.id)} target="_blank" rel="noreferrer">{item.media_type.startsWith('image/')&&<img src={materialUrl(project.id,item.id)+'?preview=true'} alt={item.name} loading="lazy"/>}<strong>{item.name}</strong></a><small>{item.kind}{item.media_type==='application/pdf'?' · '+item.pages+' 页':''}</small>{(!styleOnly||['风格参考','排版参考'].includes(item.kind))&&<button type="button" disabled={locked} onClick={()=>onRemove(item.id)}>移除</button>}</article>)}</div>
    {!project.materials.length&&<p>还没有上传资料。</p>}
    <div className="guided-upload"><label>资料用途<select value={kind} disabled={locked} onChange={e=>setKind(e.target.value)}>{(styleOnly?['风格参考','排版参考']:['说明书','规格书','产品实拍','产品图','结构细节','其他']).map(value=><option key={value}>{value}</option>)}</select></label><label>添加文件<input type="file" accept={styleOnly?'.png,.jpg,.jpeg,.webp':'.pdf,.png,.jpg,.jpeg,.webp'} multiple disabled={locked} onChange={e=>{const files=Array.from(e.target.files||[]);e.target.value='';void onUpload(files,kind);}}/></label></div><small>单份最多 20 MB，每个产品或方案最多 30 份、合计 100 MB。PDF 最多 100 页。</small>
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
