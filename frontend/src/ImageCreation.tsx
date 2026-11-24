import ImageStudio from './ImageStudio';
import AgentStudio from './AgentStudio';
import ImageProduction from './ImageProduction';
import { CreationSkillPicker, useCreationSkill } from './CreationSkillContext';
import { useState } from 'react';
import PlanImportDialog from './PlanImportDialog';

export default function ImageCreation({route}:{route:string}){
  const skill=useCreationSkill();
  const [importing,setImporting]=useState(false);const [hasDraft,setHasDraft]=useState(false);const [submitting,setSubmitting]=useState(false);
  const params=new URLSearchParams(route.split('?')[1]);const projectId=params.get('project');const runId=params.get('run');
  return <section aria-labelledby="image-studio-heading"><div className="section-heading"><div><p className="eyebrow">GENERATE YOUR IMAGES</p><h2 id="image-studio-heading">图片创作</h2></div><div className="guided-actions">{!runId&&<button type="button" className="button-primary" disabled={submitting} onClick={()=>setImporting(true)}>{projectId?'更换策划内容':'导入策划内容'}</button>}<a className="button-secondary" href="#/library">查看生成记录</a></div></div>
    {runId?<><a href="#/studio">开始新的生图</a><AgentStudio key={runId} route={route} detailOnly/></>:projectId?<ImageProduction key={projectId} id={projectId}/>:<>
      <p className="settings-intro">直接填写要求生图，或点击“导入策划内容”，自动载入已确认方案的提示词和参考素材。</p>
      <details className="workflow-options"><summary>生图技能 · {skill.mode==='auto'?'自动选择':'已指定 '+skill.selectedIds.length+' 个'}</summary><p>直接生图时应用适用的制作技能；从策划带入的图片使用方案已确认的规范。</p><CreationSkillPicker/></details>
      <ImageStudio key={route} onDraftChange={setHasDraft} onSubmittingChange={setSubmitting}/>
    </>}
    <PlanImportDialog open={importing} currentId={projectId} hasDraft={!projectId&&hasDraft} onClose={()=>setImporting(false)} onImport={id=>{setImporting(false);setHasDraft(false);window.location.hash='#/studio?project='+encodeURIComponent(id);}}/>
  </section>;
}
