"""Content planning modes and bounded, account-private plan comparisons."""
import json
import re

from fastapi import HTTPException
from sqlalchemy import select, or_

from app.database import CreationProject, CreationDocument
from app.image_purpose import main_shot_ids

LABELS={'optimize':'优化当前方案','replan':'重新策划一套','directed':'按指定方向策划'}
POLICIES={
    'optimize':'保留当前方案的图片数量、逐图 id、顺序与主题职责；优化卖点表达、证据展示、文案和构图，不重新分配每张图的主题。',
    'replan':'基于已确认产品事实重新策划。重新选择卖点组合、叙事主线、图序和证明方式；不是对旧方案逐图改写、换标题或换场景。',
    'directed':'基于已确认产品事实围绕本轮 direction 重新策划卖点组合、叙事顺序和展示方法；方向决定内容重点，不只是视觉风格。',
}
PLANNING_INSTRUCTIONS='''
brief 必须遵守 content_planning.mode_policy。本轮明确指令、已确认事实、图型规范、尺寸和用户明确指定的必选卖点优先。
历史方案只用于识别重复，不是新的产品事实、固定图序或必须沿用的模板。
optimize 时保留 current_draft 的逐图 id、顺序和主题；如用户想换整套主题，应选择重新策划。
replan/directed 时不沿用旧方案逐图主题；从已确认卖点池重新取舍，变化应体现在卖点组合、图位、叙事顺序、受众使用问题和证据展示方式。
真实产品功能可以重复，必要的商品主图、指定尺寸、合规模块及用户指定内容必须保留，不为求不同编造参数、功能或无依据卖点。
不要机械重复“场景→覆盖→网纱→面料→调高→搭设→收纳→附件”的固定顺序。
template 若有明确的主图职责、数量、尺寸或必需模块需保留；其示例主题顺序不应阻止重新组织内容，除非本轮用户明确要求保留。
planning_summary 用中文简要说明本轮的内容主线、卖点选择和图序理由；若有历史方案，指出相对最近方案的实际变化及必要保留项。
若证据或图片数量限制了差异，应如实说明，不宣称不存在的变化。
'''


def history_for(session, project, limit=6):
    related=(or_(CreationProject.id==project.id,CreationProject.source_product_id==project.source_product_id)
             if project.source_product_id else CreationProject.id==project.id)
    rows=session.execute(select(CreationDocument,CreationProject.title).join(CreationProject,
        CreationDocument.project_id==CreationProject.id).where(CreationProject.owner_id==project.owner_id,
        related,CreationDocument.stage=='brief').order_by(CreationDocument.created_at.desc(),
        CreationDocument.version.desc(),CreationDocument.id.desc()).limit(limit)).all()
    summaries=[];budget=24000
    for doc,title in rows:
        summary={'project_id':doc.project_id,'project_title':title,'document_id':doc.id,'version':doc.version,
            'shots':[{key:str(shot.get(key,'') or '')[:length] for key,length in
                [('id',80),('name',80),('objective',120),('selling_point',160),('content',180)]}
                for shot in json.loads(doc.content).get('shots',[])[:16]]}
        length=len(json.dumps(summary,ensure_ascii=False))
        if length>budget:break
        summaries.append(summary);budget-=length
    return summaries


def prepare_context(session, project, payload, mode, direction):
    mode=mode or ('optimize' if payload['current_draft'] else 'replan')
    if mode=='optimize' and not payload['current_draft']:
        raise HTTPException(409,'还没有当前图需，请选择重新策划一套或按指定方向策划。')
    if mode=='directed' and not direction.strip():
        raise HTTPException(422,'请填写本次策划方向，例如庭院生活、结构细节或使用便利。')
    if mode!='directed' and direction.strip():
        raise HTTPException(422,'填写策划方向时请选择“按指定方向策划”。')
    context={'mode':mode,'label':LABELS[mode],'direction':direction.strip(),'mode_policy':POLICIES[mode],
        'history':history_for(session,project),'history_policy':'仅作内容重复对照；不是产品事实或固定图序。',
        'constraints':'保留确认的产品事实、SKU、必选卖点、图型职责及明确尺寸；主图保护不计为内容重复。'}
    payload['content_planning']=context
    if mode!='optimize':
        payload['current_draft']=None
        # Past conversations can contain instructions about obsolete image slots.
        payload['conversation']=[]
    return context


def similarity(left,right):
    def tokens(value):
        text=re.sub(r'[^\w\u4e00-\u9fff]+','',value.lower())
        return {text[i:i+2] for i in range(len(text)-1)} if len(text)>1 else {text} if text else set()
    a,b=tokens(left),tokens(right)
    return 2*len(a&b)/(len(a)+len(b)) if a and b else 0.0


def theme_similarity(left,right):
    # Content matters independently of names: title-only rewrites should still be caught.
    point=similarity(left.get('selling_point',''),right.get('selling_point',''))
    purpose=similarity(left.get('objective','')+' '+left.get('name',''),right.get('objective','')+' '+right.get('name',''))
    content=similarity(left.get('content',''),right.get('content',''))
    if left.get('selling_point') and right.get('selling_point'):
        return point*.55+purpose*.2+content*.25
    return purpose*.35+content*.65


def review_plan(payload, result):
    context=payload.get('content_planning')
    if not context:return None
    current=result.get('shots',[])
    if context['mode']=='optimize':
        baseline=(payload.get('current_draft') or {}).get('shots',[])
        if [s['id'] for s in current]!=[s['id'] for s in baseline]:
            raise HTTPException(422,'优化当前方案需保留逐图编号和顺序；本次结果改变了图位，旧方案仍保留。请重新优化或选择重新策划。')
    protected=main_shot_ids(payload['settings'],result)
    comparisons=[];warnings=[]
    for old in context.get('history',[]):
        previous=old['shots'];old_protected=main_shot_ids(payload['settings'],{'shots':previous})
        comparable=[(i,s) for i,s in enumerate(current) if s['id'] not in protected]
        eligible_old=[s for s in previous if s['id'] not in old_protected]
        same=[i+1 for i,s in comparable if i<len(previous) and previous[i]['id'] not in old_protected and theme_similarity(s,previous[i])>=.65]
        # One-to-one matching prevents one old topic counting as several distinct matches.
        candidates=sorted([(theme_similarity(s,prior),i,j) for i,(_,s) in enumerate(comparable)
            for j,prior in enumerate(eligible_old)],reverse=True)
        used_new=set();used_old=set()
        for score,i,j in candidates:
            if score>=.65 and i not in used_new and j not in used_old:used_new.add(i);used_old.add(j)
        ratio=len(same)/len(comparable) if comparable else 0
        comparisons.append({'project_id':old['project_id'],'project_title':old['project_title'],'version':old['version'],
            'document_id':old['document_id'],'same_slots':same,'compared_slots':len(comparable),
            'same_slot_ratio':round(ratio,2),'reused_theme_count':len(used_new)})
        if context['mode']!='optimize' and comparable and ratio>=.7:
            warnings.append(f"与「{old['project_title']}」图需第 {old['version']} 版相比，第 { '、'.join(map(str,same)) } 张主题与图位仍较相似，请检查是否只是改写表达。")
    return {'mode':context['mode'],'label':context['label'],'direction':context['direction'],
        'history_count':len(comparisons),'protected_slots':[i+1 for i,s in enumerate(current) if s['id'] in protected],
        'summary':result.get('planning_summary',''),'comparisons':comparisons,'warnings':warnings,
        'method':'文字主题相似度与图位对照，不能代替人工语义审核；未额外调用模型。'}
