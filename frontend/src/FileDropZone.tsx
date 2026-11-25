import { useRef, useState, type DragEvent } from 'react';

export default function FileDropZone({accept,disabled=false,hint,onFiles}:{
  accept:string;disabled?:boolean;hint:string;onFiles:(files:File[])=>void;
}) {
  const input=useRef<HTMLInputElement>(null);
  const depth=useRef(0);
  const [dragging,setDragging]=useState(false);
  function hasFiles(event:DragEvent<HTMLDivElement>) {
    return Array.from(event.dataTransfer.types).includes('Files');
  }
  return <div className={'file-drop-zone'+(dragging&&!disabled?' is-dragging':'')+(disabled?' is-disabled':'')}
    role="group" aria-label="文件上传区域" aria-disabled={disabled}
    onDragEnter={event=>{if(!hasFiles(event))return;event.preventDefault();depth.current+=1;if(!disabled)setDragging(true);}}
    onDragOver={event=>{if(!hasFiles(event))return;event.preventDefault();event.dataTransfer.dropEffect=disabled?'none':'copy';}}
    onDragLeave={event=>{event.preventDefault();depth.current=Math.max(0,depth.current-1);if(!depth.current)setDragging(false);}}
    onDrop={event=>{event.preventDefault();depth.current=0;setDragging(false);if(!disabled)onFiles(Array.from(event.dataTransfer.files));}}>
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M12 16V3m-5 5 5-5 5 5M4 14v6h16v-6"/></svg>
    <div className="file-drop-copy"><strong>{disabled?'暂时无法添加文件':dragging?'松开即可添加文件':'拖拽文件到这里'}</strong><small>{hint}</small></div>
    <button type="button" className="button-secondary" disabled={disabled} onClick={()=>input.current?.click()}>选择文件</button>
    <input ref={input} aria-label="上传文件" type="file" accept={accept} multiple disabled={disabled} hidden
      onChange={event=>{const files=Array.from(event.target.files||[]);event.target.value='';if(!disabled&&files.length)onFiles(files);}}/>
  </div>;
}
