import { useEffect, useRef } from 'react';
import type { Project } from './creationProjectApi';
import { productionProgress } from './projectProgress.mjs';

type Step = 'materials'|'analysis'|'brief'|'prompts'|'images';
const steps: {id:Step;title:string}[] = [
  {id:'materials',title:'产品资料'}, {id:'analysis',title:'产品卖点'},
  {id:'brief',title:'整套图需'}, {id:'prompts',title:'图片提示词'}, {id:'images',title:'生图与交付'},
];
const descriptions: Record<Step,string> = {
  materials:'先保存产品信息，上传说明书、规格书与实拍，作为整套创作的依据。',
  analysis:'核对 AI 提炼的事实和卖点，确认后为这个产品建立图片策划。',
  brief:'先确定风格与本轮方向，再逐张检查内容、排版和参考图；确认后进入提示词。',
  prompts:'图需已确认。逐张检查完整提示词与参考图，确认后带入图片创作。',
  images:'在下方查看制作进度，重试失败图片或直接在原图上修改，满意后保存完整案例。',
};

export function focusSection(id:string) {
  const element=document.getElementById(id);
  element?.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});
  element?.focus({preventScroll:true});
}

export default function CreationFlow({project,current,dirty=false,onStep}:{project:Project;current:Step;dirty?:boolean;onStep?:(step:Step)=>void}) {
  const navigation=useRef<HTMLElement>(null);
  useEffect(()=>{
    const nav=navigation.current;
    if(!nav)return;
    const align=()=>{
      const active=nav.querySelector<HTMLElement>('[aria-current=step]');
      if(active)nav.scrollLeft=nav.scrollWidth>nav.clientWidth?Math.max(0,active.offsetLeft-nav.offsetLeft-12):0;
    };
    align();
    const observer=new ResizeObserver(align);observer.observe(nav);
    return ()=>observer.disconnect();
  },[current]);
  const product=project.kind==='product';
  const sourceId=product?project.id:project.source?.product_id||project.source_product_id;
  const progress=productionProgress(project);
  const isDone=(step:Step)=>step==='materials'?!!(project.materials.length||project.settings.goal?.trim()):step==='images'?progress.complete:!!project.documents[step]?.confirmed_at;
  const accessible=(step:Step)=>step==='materials'||step==='analysis'?!!sourceId:step==='brief'?!!project.documents.analysis?.confirmed_at:step==='prompts'?!product&&!!project.documents.brief?.confirmed_at:!product&&!!project.documents.prompts?.confirmed_at;
  const href=(step:Step)=>step==='materials'||step==='analysis'?`#/products?project=${encodeURIComponent(sourceId||'')}&tab=materials`:product?`#/products?project=${encodeURIComponent(project.id)}&tab=plans`:step==='images'?`#/studio?project=${encodeURIComponent(project.id)}`:`#/planning?project=${encodeURIComponent(project.id)}&stage=${step}`;
  const local=(step:Step)=>product?(step==='materials'||step==='analysis'):(current==='images'?step==='images':step==='brief'||step==='prompts');
  return <section className="creation-flow" aria-label="当前创作进度">
    <nav className="creation-flow-steps" ref={navigation} aria-label={product?'产品分析流程':current==='images'?'图片制作流程':'图片策划阶段'}>
      {steps.map((step,index)=>{
        const active=current===step.id;const done=isDone(step.id);const allowed=accessible(step.id)||active;
        const className=`creation-flow-step${active?' is-current':''}${done?' is-done':''}`;
        const content=<><span className="flow-step-number" aria-hidden="true">{done?'✓':String(index+1).padStart(2,'0')}</span><span><strong>{step.title}</strong><small>{active?'当前阶段':done?'已完成':allowed?'可继续':step.id==='brief'?'先确认卖点':step.id==='prompts'?'先确认图需':'先确认提示词'}</small></span></>;
        if(local(step.id))return <button key={step.id} type="button" className={className} aria-current={active?'step':undefined} disabled={!allowed} onClick={()=>onStep?.(step.id)}>{content}</button>;
        return allowed?<a key={step.id} className={className} href={href(step.id)} aria-current={active?'step':undefined}>{content}</a>:<span key={step.id} className={className} aria-disabled="true">{content}</span>;
      })}
    </nav>
    <div className="creation-flow-context"><p>{descriptions[current]}</p><span className={'save-state'+(dirty?' is-dirty':'')} role="status">{project.busy?'任务执行中 · 可稍后返回':dirty?'有未保存修改':'内容已保存'}</span></div>
  </section>;
}
