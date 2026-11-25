"""Explicit mobile re-layout and immutable, credential-free workflow cases."""
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from uuid import UUID, uuid4
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.authorization import require_edit, owner_view
from app.database import (CreationProject, CreationMaterial, CreationDocument, CreationExecution,
                          ImageJob, WorkflowCase, CreativeCase)
from app.creation_projects import (load_project, check_idle, project_view, save_document,
    clone_materials, material_view, active_document, ProjectInput, touch, LOCK)
from app.creation_materials import material_path
from app.image_jobs import artifact, now

MAX_CASE_BYTES = 500 * 1024 * 1024


class MobileInput(BaseModel):
    revision: int = Field(ge=1)
    request_id: UUID
    batch_id: UUID
    image_model: str = Field(default='', max_length=200)


class CaseInput(BaseModel):
    revision: int = Field(ge=1)
    request_id: UUID
    title: str = Field(min_length=1, max_length=160)
    summary: str = Field(default='', max_length=8000)


class ReuseInput(BaseModel):
    request_id: UUID
    title: str = Field(min_length=1, max_length=120)
    product_id: UUID | None = None


def case_root(storage, identifier):
    return storage / 'workflow-cases' / str(UUID(identifier))


def case_view(row, detail=False):
    data = json.loads(row.content)
    return {'id': row.id, 'project_id': row.project_id, 'title': row.title, 'summary': row.summary,
        'created_at': row.created_at, **owner_view(row), 'image_count': sum(i['status']=='succeeded' for i in data['images']),
        'material_count': len(data['materials']), 'format_version': 1,
        **({'snapshot': data} if detail else {})}


def mobile_prompt(shot):
    return ('Edit the supplied desktop artwork into a newly composed mobile A+ finished image. '
        'Target layout 4:3, 1200x900 pixels (600x450 layout reference). '
        'Image 1 is the desktop editing target and campaign reference; remaining images are actual product identity references. '
        'Identity photos override generated artwork for geometry. Preserve the same SKU, color, parts, verified corrections, '
        'topic, campaign typography and exact copy, numbers, units and qualifications. '
        'Independently reposition the product, camera and text blocks for phone readability. '
        'Do not crop, stretch, shrink the desktop banner into borders, or reproduce desktop coordinates. '
        'Use a large complete scene with foreground/midground/background where appropriate; '
        'use readable large details for structural evidence and readable 2x2 steps for four-step content. '
        'Do not turn the scene into beige cards or remove essential warnings. '
        'Check legibility at a phone display width of 375 pixels. Render all approved text in the image.\n'
        f'Topic: {shot["name"]}\nObjective: {shot.get("objective", "")}\n'
        f'Verified selling point: {shot.get("selling_point", "")}\nExact copy:\n{shot.get("copy", "")}')


def build_delivery_router(store):
    router = APIRouter(prefix='/api', tags=['project-delivery'])

    def require_db():
        if store.engine is None: raise HTTPException(503, '请先配置数据库。')

    @router.post('/creation-projects/{project_id}/mobile', status_code=202)
    def mobile(project_id: UUID, value: MobileInput, request: Request):
        require_db()
        with LOCK, Session(store.engine) as session, session.begin():
            existing = session.get(CreationExecution, str(value.request_id))
            if existing:
                target, data = load_project(session, existing.project_id, request.state.image_owner)
                if data.get('mobile_source', {}).get('project_id') != str(project_id):
                    raise HTTPException(409, '提交标识已被使用。')
                return project_view(session, target)
            source, data = load_project(session, project_id, request.state.image_owner, value.revision)
            require_edit(source); check_idle(session, source.id)
            if data.get('mobile_source'):
                raise HTTPException(409, '当前已是手机版方案，请从桌面原方案发起。')
            batch = next((b for b in data.get('batches',[]) if b['execution_id']==str(value.batch_id)), None)
            if not batch or not batch['job_ids']: raise HTTPException(422, '请选择一个完整的桌面生成版本。')
            jobs = [session.get(ImageJob, identifier) for identifier in batch['job_ids']]
            if any(not j or j.task_id != source.id or j.deleted_at or j.status != 'succeeded' for j in jobs):
                raise HTTPException(409, '此版本尚未全部成功或有图片被删除，请先补齐桌面图片。')
            if any(j.size != '1464x600' for j in jobs):
                raise HTTPException(422, '此入口适用于1464×600的桌面A+版本。')
            current = store.get(request.state.image_owner)
            model = value.image_model or (current or {}).get('image_model_name')
            if not current or not current['has_api_key'] or model not in current['model_names']:
                raise HTTPException(409, '请先配置图片模型和运行时密钥。')
            profile = store.snapshot(request.state.image_owner, current['id'])
            if any(json.loads(j.execution_profile).get('base_url') != profile['base_url'] for j in jobs):
                raise HTTPException(409, '当前服务商与桌面图片来源不同，请先恢复原服务商连接。')
            profile.update(model=model, parameters=current.get('model_settings',{}).get(model,{}).get('request_parameters',{}),
                capabilities=current.get('model_settings',{}).get(model,{}).get('capabilities',{}))
            if current.get('auto_review'):
                profile['review_model'] = data['planning_model']
                profile['review_parameters'] = current.get('model_settings',{}).get(data['planning_model'],{}).get('vision_parameters',{})
            edit_capability = profile['capabilities'].get('edit', {})
            if edit_capability is False or isinstance(edit_capability,dict) and edit_capability.get('state') == 'unsupported':
                raise HTTPException(422, '所选模型未开启图片编辑能力。')
            verified_edit = isinstance(edit_capability,dict) and edit_capability.get('state') == 'supported'
            if not verified_edit and not all(j.mode == 'edit' and j.model_name == model for j in jobs):
                raise HTTPException(409, '请先在模型配置中确认该模型的图片编辑能力，再制作手机版。')
            original = json.loads(jobs[0].execution_profile)
            docs = original.get('source_documents') or data.get('active',{})
            brief = session.get(CreationDocument, docs.get('brief',''))
            prompt_doc = session.get(CreationDocument, docs.get('prompts',''))
            if not brief or not prompt_doc: raise HTTPException(409, '桌面版本缺少锁定的图需和提示词。')
            shots = {s['id']:s for s in json.loads(brief.content)['shots']}
            prompt_items = {p['shot_id']:p for p in json.loads(prompt_doc.content)['prompts']}
            shot_ids = batch.get('shot_ids') or list(prompt_items)
            if len(shot_ids) != len(jobs) or any(i not in shots or i not in prompt_items for i in shot_ids):
                raise HTTPException(409, '桌面版本图号映射不完整，无法安全批量适配。')
            target_id = str(uuid4())
            target = CreationProject(id=target_id,title=(source.title+' · 手机版')[:120],kind=source.kind,
                source_product_id=source.source_product_id,owner_id=request.state.image_owner,revision=1,
                content='{}',created_at=now(),updated_at=now())
            session.add(target)
            mapping = clone_materials(session,store.directory,source.id,target_id)
            target_data = json.loads(json.dumps(data))
            target_data['visual_style_snapshot'] = original.get('visual_style')
            target_data['visual_style'] = (original.get('visual_style') or {}).get('selection')
            target_data['learning'] = {**(data.get('learning') or {}),'device':'mobile','image_type':'a_plus'}
            target_data.update(active={},messages=[],batches=[],mobile_source={'project_id':source.id,
                'batch_id':str(value.batch_id),'job_ids':[j.id for j in jobs]}, image_count=len(jobs),
                image_model=model, stage='images',goal=data.get('goal','')+'\n手机版A+：4:3独立重排，保留桌面版本。')
            new_shots, new_prompts = [], []
            for shot_id, job in zip(shot_ids,jobs):
                shot = json.loads(json.dumps(shots[shot_id])); desktop = artifact(store.directory,job.id,'result.png')
                if not desktop.is_file(): raise HTTPException(409,'桌面原图文件缺失，未提交手机版任务。')
                raw = desktop.read_bytes(); ref_id = str(uuid4())
                path = material_path(store.directory,target_id,ref_id); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
                from app.creation_materials import inspect_material
                _, mime, pages = inspect_material(raw,desktop.name)
                session.add(CreationMaterial(id=ref_id,project_id=target_id,name=shot['name']+' · 桌面原图',kind='排版参考',
                    media_type=mime,digest=hashlib.sha256(raw).hexdigest(),size=len(raw),pages=pages,created_at=now()))
                identity_refs = [mapping[r] for r in prompt_items[shot_id]['reference_ids']]
                if len(identity_refs)>7: raise HTTPException(422,'单张参考图超过8张，请先缩减桌面方案参考范围。')
                shot.update(size='1200x900',reference_ids=[ref_id,*identity_refs],
                    layout='手机端4:3独立重排；大主体、清晰文案、保留场景纵深；不裁切桌面横幅。原图编排意图：'+shot.get('layout',''),
                    notes='基于桌面图片 '+job.id+'，桌面图作编辑目标及风格参考，实拍作商品身份依据。')
                new_shots.append(shot)
                style_rules = (target_data.get('visual_style_snapshot') or {}).get('rules','')
                new_prompts.append({'shot_id':shot_id,'prompt':mobile_prompt(shot)+'\nMobile layout intent: '+shot['layout']
                    + ('\nConfirmed campaign direction (adapt layout for mobile): '+style_rules if style_rules else ''),'reference_ids':shot['reference_ids']})
            analysis = session.get(CreationDocument,docs.get('analysis',''))
            previous = {'brief':{'shots':new_shots},'prompts':{'prompts':new_prompts}}
            if analysis: previous['analysis'] = json.loads(analysis.content)
            for stage in ('analysis','brief','prompts'):
                if stage not in previous: continue
                content = previous[stage]
                text = json.dumps(content,ensure_ascii=False)
                for old,new in mapping.items(): text=text.replace(old,new)
                doc=save_document(session,target,target_data,stage,json.loads(text)); doc.confirmed_at=now()
            target_data['stage']='images'; touch(target,target_data)
            session.flush()
            materials=[material_view(m) for m in session.scalars(select(CreationMaterial).where(CreationMaterial.project_id==target_id))]
            payload={'settings':{k:target_data[k] for k in ('goal','style','image_count','planning_model','image_model')},
                'skill_snapshot':original.get('skill_workflow') or data['skill_snapshot'], 'profile':profile,
                'previous':previous,'source_documents':dict(target_data['active']), 'materials':materials,
                'shot_ids':shot_ids,'drawing_experience':data.get('drawing_experience',{})}
            payload['settings']['visual_style'] = target_data.get('visual_style_snapshot')
            session.add(CreationExecution(id=str(value.request_id),project_id=target_id,stage='images',status='queued',
                input=json.dumps(payload,ensure_ascii=False),output='{}',error='',created_at=now(),updated_at=now()))
            session.flush()
            return project_view(session,target)

    @router.post('/creation-projects/{project_id}/cases', status_code=201)
    def archive_case(project_id: UUID, value: CaseInput, request: Request):
        require_db()
        with LOCK, Session(store.engine) as session, session.begin():
            prior=session.scalar(select(WorkflowCase).where(WorkflowCase.request_id==str(value.request_id)))
            if prior:
                require_edit(prior)
                if prior.project_id!=str(project_id): raise HTTPException(409,'提交标识已被使用。')
                return case_view(prior)
            project,data=load_project(session,project_id,request.state.image_owner,value.revision)
            require_edit(project); check_idle(session,project.id)
            desktop_id=data.get('mobile_source',{}).get('project_id',project.id)
            related=[]
            for candidate in session.scalars(select(CreationProject).where(CreationProject.owner_id==project.owner_id)):
                candidate_data=json.loads(candidate.content)
                if candidate.id==desktop_id or candidate_data.get('mobile_source',{}).get('project_id')==desktop_id:
                    check_idle(session,candidate.id)
                    related.append(candidate)
            if project.id not in [p.id for p in related]: related.append(project)
            project_ids=[p.id for p in related]
            jobs=list(session.scalars(select(ImageJob).where(ImageJob.task_id.in_(project_ids),ImageJob.deleted_at.is_(None)).order_by(ImageJob.created_at,ImageJob.task_index)))
            if not any(j.status=='succeeded' for j in jobs): raise HTTPException(409,'请先完成至少一张图片。')
            if any(j.status=='unknown' for j in jobs): raise HTTPException(409,'存在结果待确认的任务，请先核对后再归档。')
            identifier=str(uuid4()); root=case_root(store.directory,identifier)
            snapshot=project_view(session,project)
            snapshot['related_projects']=[project_view(session,p) for p in related if p.id!=project.id]
            all_views=[snapshot,*snapshot['related_projects']]
            snapshot['images']=[image for view in all_views for image in view['images']]
            snapshot['materials']=[material for view in all_views for material in view['materials']]
            snapshot['skill_snapshot']=data.get('skill_snapshot')
            snapshot['format_version']=1
            snapshot['guidance']=value.summary
            snapshot['files']=[]
            # Only public job views and explicit content fields; no config/credential columns.
            total=0
            def copy_file(source,relative):
                nonlocal total
                if not source.is_file(): raise HTTPException(409,'案例源文件缺失，未创建不完整案例。')
                total+=source.stat().st_size
                if total>MAX_CASE_BYTES: raise HTTPException(413,'案例超过500MB，请拆分方案后归档。')
                destination=root/relative; destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source,destination)
                snapshot['files'].append({'path':relative,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'bytes':destination.stat().st_size})
            try:
                for related_project in related:
                    for material in session.scalars(select(CreationMaterial).where(CreationMaterial.project_id==related_project.id)):
                        copy_file(material_path(store.directory,related_project.id,material.id),f'materials/{material.id}')
                for job in jobs:
                    if job.status=='succeeded':
                        copy_file(artifact(store.directory,job.id,'result.png'),f'images/{job.id}/original'+artifact(store.directory,job.id,'result.png').suffix)
                        preview=artifact(store.directory,job.id,'preview.jpg')
                        if preview.is_file(): copy_file(preview,f'images/{job.id}/preview.jpg')
                    for filename in ('reference.png','execution.json','prompt.txt','skill-read-log.json','material-read-log.json'):
                        source=artifact(store.directory,job.id,filename)
                        # execution.json may contain provider details; public execution_result is already in snapshot.
                        if filename=='execution.json': continue
                        if source.is_file(): copy_file(source,f'images/{job.id}/{filename}')
                    refs=json.loads(job.execution_profile).get('reference_manifest',[])
                    for index in range(2,len(refs)+1):
                        filename=f'reference-{index}.png'
                        copy_file(artifact(store.directory,job.id,filename),f'images/{job.id}/{filename}')
                for related_project in related:
                    for execution in session.scalars(select(CreationExecution).where(CreationExecution.project_id==related_project.id)):
                        directory=store.directory/'creation-projects'/related_project.id/'executions'/execution.id
                        for filename in ('skill-read-log.json','material-read-log.json','skill-context.md','skill-workflow.json'):
                            if (directory/filename).is_file(): copy_file(directory/filename,f'executions/{execution.id}/{filename}')
                from app.skill_packages import version_root
                skill_versions = {}
                for skill_snapshot in [data.get('skill_snapshot') or {}, *[
                        json.loads(job.execution_profile).get('skill_workflow') or {} for job in jobs]]:
                    for skill in [skill_snapshot.get('primary'), *skill_snapshot.get('catalog',[]), *skill_snapshot.get('companions',[])]:
                        if skill: skill_versions[skill['version_id']] = skill
                for skill in skill_versions.values():
                    raw = version_root(store.directory,skill['skill_id'],skill['version_id'])/'raw'
                    if not raw.is_dir(): raise HTTPException(409,'锁定技能资源缺失，请修复后归档。')
                    for path in raw.rglob('*'):
                        if path.is_file(): copy_file(path,f'skills/{skill["version_id"]}/'+path.relative_to(raw).as_posix())
                feedback=list(session.scalars(select(CreativeCase).where(CreativeCase.job_id.in_([j.id for j in jobs]))))
                from app.learning_feedback import read_learning
                snapshot['feedback']=[{**{k:getattr(f,k) for k in ('job_id','title','experience','issues','requested_change','outcome','revision')},
                    'learning':read_learning(next(job for job in jobs if job.id==f.job_id))} for f in feedback]
                (root/'snapshot.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
                row=WorkflowCase(id=identifier,project_id=project.id,owner_id=request.state.image_owner,title=value.title,
                    summary=value.summary,content=json.dumps(snapshot,ensure_ascii=False),request_id=str(value.request_id),created_at=now())
                session.add(row); session.flush()
                return case_view(row)
            except BaseException:
                shutil.rmtree(root,ignore_errors=True)
                raise

    @router.get('/workflow-cases')
    def cases(q: str=''):
        require_db()
        with Session(store.engine) as session:
            query=select(WorkflowCase)
            if q.strip(): query=query.where(WorkflowCase.title.icontains(q.strip(),autoescape=True)|WorkflowCase.summary.icontains(q.strip(),autoescape=True))
            return [case_view(c) for c in session.scalars(query.order_by(WorkflowCase.created_at.desc()).limit(100))]

    @router.get('/workflow-cases/{case_id}')
    def get_case(case_id: UUID):
        require_db()
        with Session(store.engine) as session:
            row=session.get(WorkflowCase,str(case_id))
            if not row: raise HTTPException(404,'案例不存在。')
            return case_view(row,True)

    @router.get('/workflow-cases/{case_id}/images/{job_id}')
    def case_image(case_id: UUID,job_id: UUID,preview: bool=True):
        require_db()
        with Session(store.engine) as session:
            row=session.get(WorkflowCase,str(case_id))
            if not row: raise HTTPException(404,'案例不存在。')
            files=json.loads(row.content)['files']
            prefix=f'images/{job_id}/'
            name=next((f['path'] for f in files if f['path']==prefix+'preview.jpg'),None) if preview else None
            name=name or next((f['path'] for f in files if f['path'].startswith(prefix+'original.')),None)
            if not name: raise HTTPException(404,'案例图片不存在。')
            return FileResponse(case_root(store.directory,str(case_id))/name,headers={'Cache-Control':'no-store'})

    @router.get('/workflow-cases/{case_id}/download')
    def download_case(case_id: UUID):
        require_db()
        with Session(store.engine) as session:
            row=session.get(WorkflowCase,str(case_id))
            if not row: raise HTTPException(404,'案例不存在。')
            snapshot=json.loads(row.content)
            handle=tempfile.NamedTemporaryFile(suffix='.zip',delete=False); temporary=Path(handle.name); handle.close()
            try:
                root=case_root(store.directory,str(case_id))
                with ZipFile(temporary,'w',ZIP_DEFLATED,compresslevel=1) as archive:
                    for item in snapshot['files']:
                        path=root/item['path']
                        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
                            raise HTTPException(409,'案例文件缺失或已改变，请检查备份。')
                        archive.write(path,item['path'])
                    archive.writestr('snapshot.json',json.dumps(snapshot,ensure_ascii=False,indent=2))
                    archive.writestr('展示说明.md',f'# {row.title}\n\n{row.summary}\n\n包含原始资料、分析、图需、提示词、图片版本、反馈与质检。\n复用时需重新确认产品事实、适用范围与参考授权。\n')
                return FileResponse(temporary,media_type='application/zip',filename=f'skill-forge-case-{case_id}.zip',
                    background=BackgroundTask(temporary.unlink,missing_ok=True),headers={'Cache-Control':'no-store'})
            except BaseException:
                temporary.unlink(missing_ok=True); raise

    @router.post('/workflow-cases/{case_id}/reuse',status_code=201)
    def reuse_case(case_id: UUID,value: ReuseInput,request: Request):
        require_db()
        with LOCK, Session(store.engine) as session,session.begin():
            row=session.get(WorkflowCase,str(case_id))
            if not row: raise HTTPException(404,'案例不存在。')
            target=session.get(CreationProject,str(value.request_id))
            if target:
                if target.owner_id!=request.state.image_owner or json.loads(target.content).get('case_reference',{}).get('id')!=row.id:
                    raise HTTPException(409,'提交标识已被使用。')
                return project_view(session,target)
            snapshot=json.loads(row.content)
            # Cases supply visual/production guidance, never another SKU's unconfirmed facts.
            if not value.product_id: raise HTTPException(422,'请选择已确认分析的目标产品。')
            source,source_data=load_project(session,value.product_id,request.state.image_owner,shared_product=True)
            analysis=active_document(session,source_data,'analysis',True)
            current=store.get(request.state.image_owner)
            if not current: raise HTTPException(409,'请先配置策划模型。')
            planner=current.get('planning_model_name','')
            if not planner or planner not in current['model_names']: raise HTTPException(422,'请选择已配置的策划模型。')
            from app.creation_skills import snapshot_for
            settings=snapshot['settings']
            reference={'id':row.id,'title':row.title,'guidance':row.summary,'style':settings.get('style',''),
                'layouts':[{'name':s['name'],'objective':s.get('objective',''),'layout':s.get('layout','')} for d in snapshot['history'] if d['stage']=='brief' for s in d['content'].get('shots',[])][-16:]}
            target=CreationProject(id=str(value.request_id),title=value.title,kind='plan',source_product_id=source.id,
                owner_id=request.state.image_owner,revision=1,content='{}',created_at=now(),updated_at=now())
            session.add(target)
            mapping=clone_materials(session,store.directory,source.id,target.id)
            for image in [i for i in snapshot['images'] if i['status']=='succeeded'][-3:]:
                item = next((f for f in snapshot['files'] if f['path'].startswith(f'images/{image["id"]}/original.')),None)
                if not item: raise HTTPException(409,'案例参考成图缺失。')
                original=case_root(store.directory,row.id)/item['path']
                raw=original.read_bytes()
                if hashlib.sha256(raw).hexdigest()!=item['sha256']: raise HTTPException(409,'案例参考成图已改变。')
                identifier=str(uuid4()); path=material_path(store.directory,target.id,identifier)
                path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
                from app.creation_materials import inspect_material
                _,mime,pages=inspect_material(raw,original.name)
                session.add(CreationMaterial(id=identifier,project_id=target.id,name=row.title+' · 仅作风格参考',kind='风格参考',
                    media_type=mime,digest=item['sha256'],size=len(raw),pages=pages,created_at=now()))
                reference.setdefault('style_material_ids',[]).append(identifier)
            data=ProjectInput(title=value.title,kind='plan',source_product_id=UUID(source.id),
                goal='参考案例的视觉和编排方法，为当前产品重新策划；只使用当前产品已确认事实。',
                style=settings.get('style',''),visual_style=settings.get('visual_style'),image_count=settings.get('image_count',4),planning_model=planner,
                image_model=current.get('image_model_name','')).model_dump(mode='json',exclude={'title','revision'})
            data.update(active={},messages=[],batches=[],stage='brief',case_reference=reference,
                source={'product_id':source.id,'title':source.title,'document_id':analysis.id,'version':analysis.version,'materials':mapping},
                skill_snapshot=snapshot_for(store.engine,store.directory,request.state.image_owner,data['goal'],data['skill']))
            data['visual_style_snapshot'] = snapshot.get('visual_style_snapshot')
            text=analysis.content
            for old,new in mapping.items(): text=text.replace(old,new)
            doc=save_document(session,target,data,'analysis',json.loads(text)); doc.confirmed_at=now()
            data['stage']='brief'; touch(target,data); session.flush()
            return project_view(session,target)
    return router
