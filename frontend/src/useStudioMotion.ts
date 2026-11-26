import { useEffect } from 'react';

// Animate only new, visible sections. Data refreshes never hide existing content.
export function useStudioMotion(route:string){
  useEffect(()=>{
    const root=document.getElementById('workspace');
    if(!root)return;
    const preference=window.matchMedia('(prefers-reduced-motion: reduce)');
    const seen=new WeakSet<Element>();const animations=new Set<Animation>();
    const selector='.section-heading, .studio-product-hero, .workspace-hero, .guided-card, .workspace-panel, .resume-creation, .workflow-entry-grid, .product-plan-card, .product-library-card, .team-project-card, .model-config-card, .creation-flow, .plan-context';
    let observer:IntersectionObserver|undefined;let mutation:MutationObserver|undefined;
    function stop(){observer?.disconnect();mutation?.disconnect();animations.forEach(animation=>animation.cancel());animations.clear();}
    function start(){
      stop();
      if(preference.matches)return;
      observer=new IntersectionObserver(entries=>{
        let order=0;
        entries.forEach(entry=>{
          if(!entry.isIntersecting||seen.has(entry.target))return;
          seen.add(entry.target);observer?.unobserve(entry.target);
          const animation=entry.target.animate([
            {opacity:.55,translate:'0 14px'}, {opacity:1,translate:'0 0'},
          ],{duration:520,delay:Math.min(order++,5)*45,easing:'cubic-bezier(.2,.75,.25,1)'});
          animations.add(animation);animation.onfinish=()=>animations.delete(animation);
        });
      },{threshold:.04});
      const discover=(scope:ParentNode)=>{
        const targets=[...(scope instanceof Element&&scope.matches(selector)?[scope]:[]),...scope.querySelectorAll(selector)];
        targets.forEach(element=>{
          // Keep text fields steady while editing inside a larger section.
          if(!seen.has(element)&&!element.parentElement?.closest('.guided-card, .studio-product-hero'))observer?.observe(element);
        });
      };
      discover(root!);
      mutation=new MutationObserver(records=>records.forEach(record=>record.addedNodes.forEach(node=>{if(node instanceof Element)discover(node);})));
      mutation.observe(root!,{childList:true,subtree:true});
    }
    start();preference.addEventListener('change',start);
    return()=>{stop();preference.removeEventListener('change',start);};
  },[route]);
}
