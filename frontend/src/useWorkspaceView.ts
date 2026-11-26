import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';
import { useAuth } from './AuthGate';
import { readView, writeView } from './workspaceViewState';

export function useWorkspaceView<T>(key:string,fallback:T):[T,Dispatch<SetStateAction<T>>]{
  const {user}=useAuth();
  const [entry,setEntry]=useState(()=>({key,value:readView(user.id,key,fallback)}));
  const value=entry.key===key?entry.value:readView(user.id,key,fallback);
  useEffect(()=>{writeView(user.id,key,value);},[user.id,key,value]);
  return [value,update=>setEntry(previous=>({key,value:typeof update==='function'?(update as (previous:T)=>T)(previous.key===key?previous.value:readView(user.id,key,fallback)):update}))];
}

export function saveWorkspaceScroll(user:string,route:string){
  if(route)writeView(user,'scroll:'+route,window.scrollY);
}

export function useWorkspaceScroll(user:string,route:string){
  useEffect(()=>{
    const previous=window.history.scrollRestoration;window.history.scrollRestoration='manual';
    return()=>{window.history.scrollRestoration=previous;};
  },[]);
  useEffect(()=>{
    const stored=readView<unknown>(user,'scroll:'+route,0);
    const target=typeof stored==='number'&&Number.isFinite(stored)?Math.max(0,stored):0;
    let stopped=false;let frame=0;
    const stop=()=>{stopped=true;observer.disconnect();cancelAnimationFrame(frame);window.clearTimeout(timeout);};
    const restore=()=>{
      if(stopped)return;
      window.scrollTo({top:target,behavior:'instant'});
      if(Math.abs(window.scrollY-target)<2)stop();
    };
    const observer=new ResizeObserver(()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(restore);});
    observer.observe(document.body);
    const timeout=window.setTimeout(stop,8000);
    frame=requestAnimationFrame(restore);
    // Hand control back immediately when the user interacts with the page.
    const events=['wheel','touchstart','pointerdown','keydown'] as const;
    events.forEach(event=>window.addEventListener(event,stop,{passive:true}));
    const save=()=>saveWorkspaceScroll(user,route);
    window.addEventListener('pagehide',save);
    return()=>{stop();events.forEach(event=>window.removeEventListener(event,stop));window.removeEventListener('pagehide',save);};
  },[user,route]);
}
