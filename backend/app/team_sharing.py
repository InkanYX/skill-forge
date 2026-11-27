"""Versioned team snapshots. Personal APIs never read another owner's live rows."""
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.database import (TeamProjectShare, CreationProject, CreationDocument, CreationMaterial,
    CreationExecution, ImageJob, CreativeCase, ProductImageExperience, UserAccount)
from app.creation_materials import material_path
from app.image_jobs import artifact, now
from app.image_batches import visible_batches

STORAGE = WeakKeyDictionary()
SETTINGS = ('goal','style','visual_style','image_count','market','language','audience','selected_selling_points','sku','learning')


def clean(value):
    """Defense in depth; snapshots are assembled from explicit public fields."""
    if isinstance(value,dict):
        return {k:clean(v) for k,v in value.items() if not any(term in k.lower() for term in
            ('api_key','encrypted_key','base_url','authorization','password','diagnostic','response_body','config_id','provider_url'))}
    if isinstance(value,list): return [clean(v) for v in value]
    return value


def root(storage, identifier):
    return storage/'team-shares'/str(UUID(identifier))


def ready(session, project, data):
    if session.scalar(select(CreationExecution.id).where(CreationExecution.project_id==project.id,
            CreationExecution.status.in_(['queued','running']))): return False
    jobs=list(session.scalars(select(ImageJob).where(ImageJob.task_id==project.id,ImageJob.deleted_at.is_(None))))
    if any(j.status in ('queued','running') for j in jobs): return False
    if project.kind=='product': return bool(data.get('analysis_confirmed'))
    batches=visible_batches(data.get('batches',[]))
    if batches:
        latest=batches[-1];by_id={j.id:j for j in jobs}
        if not latest['job_ids'] or not all(i in by_id and by_id[i].status=='succeeded' for i in latest['job_ids']): return False
        # The submitted selection defines this set; unchecked planned shots are not pending orders.
        return True
    return any(j.status=='succeeded' for j in jobs) and not any(j.status=='unknown' for j in jobs)


def completion_signature(session, project):
    jobs=list(session.execute(select(ImageJob.id,ImageJob.status,ImageJob.updated_at,ImageJob.deleted_at)
        .where(ImageJob.task_id==project.id).order_by(ImageJob.id)))
    return hashlib.sha256(json.dumps([list(j) for j in jobs]).encode()).hexdigest()


def publish(session, storage, share, project):
    from app.creation_projects import check_idle
    check_idle(session,project.id)
    data=json.loads(project.content)
    docs=list(session.scalars(select(CreationDocument).where(CreationDocument.project_id==project.id).order_by(CreationDocument.created_at)))
    materials=list(session.scalars(select(CreationMaterial).where(CreationMaterial.project_id==project.id)))
    jobs=list(session.scalars(select(ImageJob).where(ImageJob.task_id==project.id,ImageJob.deleted_at.is_(None)).order_by(ImageJob.created_at,ImageJob.task_index)))
    bundle=str(uuid4()); destination=root(storage,share.id)/bundle
    destination.mkdir(parents=True,exist_ok=False)
    files={}; total=0
    def copy(source,key):
        nonlocal total
        if not source.is_file(): raise HTTPException(409,'项目源文件缺失，共享版本未更新。')
        total+=source.stat().st_size
        if total>500*1024*1024: raise HTTPException(413,'共享项目超过500MB，请拆分后再共享。')
        target=destination/key;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        files[key]={'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'size':target.stat().st_size}
    try:
        for m in materials:
            source=material_path(storage,project.id,m.id)
            if source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest()!=m.digest:
                raise HTTPException(409,'原始资料已改变，共享版本未更新。')
            copy(source,'materials/'+m.id)
        images=[]
        for job in jobs:
            image={k:getattr(job,k) for k in ('id','shot_name','shot_index','task_index','model_name','size','status','prompt','parent_job_id','edit_instruction','created_at')}
            result=json.loads(job.execution_result or '{}')
            image['review']={k:result[k] for k in ('native_pixels','review','agent_review','human_feedback') if k in result}
            profile=json.loads(job.execution_profile or '{}')
            image['reference_roles']=clean(profile.get('reference_manifest',[]))
            image['purpose']={k:profile[k] for k in ('shot_role','image_type','visual_style') if k in profile}
            image['references']=[]
            if job.status=='succeeded':
                copy(artifact(storage,job.id,'result.png'),'images/'+job.id+'/original.png')
                preview=artifact(storage,job.id,'preview.jpg')
                if preview.is_file(): copy(preview,'images/'+job.id+'/preview.jpg')
            for index in range(1,9):
                filename='reference.png' if index==1 else f'reference-{index}.png'
                source=artifact(storage,job.id,filename)
                if source.is_file():
                    key='images/'+job.id+'/'+filename;copy(source,key);image['references'].append(key)
            images.append(image)
        feedback=[{k:getattr(note,k) for k in ('id','job_id','title','experience','issues','outcome','requested_change')}
            for note in session.scalars(select(CreativeCase).where(CreativeCase.job_id.in_([j.id for j in jobs])))]
        product_id=project.source_product_id or project.id
        experiences=[{'content':json.loads(e.content),'status':e.status} for e in session.scalars(
            select(ProductImageExperience).where(ProductImageExperience.product_id==product_id,ProductImageExperience.status=='active'))]
        snapshot=clean({'format_version':1,'bundle':bundle,'project_revision':project.revision,
            'settings':{k:data.get(k) for k in SETTINGS},'kind':project.kind,'stage':data.get('stage','analysis'),
            'active':data.get('active',{}),'analysis_confirmed':bool(data.get('analysis_confirmed')),
            'history':[{k:getattr(d,k) for k in ('id','stage','version','confirmed_at','created_at')}|{'content':json.loads(d.content)} for d in docs],
            'materials':[{k:getattr(m,k) for k in ('id','name','kind','media_type','digest','size','pages','created_at')} for m in materials],
            'images':images,'batches':visible_batches(data.get('batches',[])),'messages':data.get('messages',[]),
            'feedback':feedback,'experiences':experiences,'visual_style_snapshot':data.get('visual_style_snapshot'),'files':files})
        snapshot['completion_signature']=completion_signature(session,project)
        share.content=json.dumps(snapshot,ensure_ascii=False);share.version+=1
        share.source_revision=project.revision;share.title=project.title;share.kind=project.kind;share.updated_at=now()
    except BaseException:
        shutil.rmtree(destination);raise


def ensure_default_shares(session, identifiers, refresh_completed=False):
    storage=STORAGE.get(session.get_bind())
    for identifier in identifiers:
        project=session.get(CreationProject,identifier)
        if not project or project.deleted_at or not project.owner_id or not session.get(UserAccount,project.owner_id): continue
        share=session.scalar(select(TeamProjectShare).where(TeamProjectShare.project_id==project.id).with_for_update())
        if not share:
            share=TeamProjectShare(id=str(uuid4()),project_id=project.id,owner_id=project.owner_id,title=project.title,
                kind=project.kind,visibility='team',version=0,source_revision=0,content='{}',created_at=now(),updated_at=now())
            session.add(share)
        changed=share.version==0 or refresh_completed and json.loads(share.content).get('completion_signature')!=completion_signature(session,project)
        if storage and share.visibility=='team' and changed and ready(session,project,json.loads(project.content)):
            try: publish(session,storage,share,project)
            except (HTTPException,OSError):
                # A sharing problem must never turn a successfully paid image into a failed job.
                content=json.loads(share.content)
                content['publish_error']='自动共享尚未完成，请在团队共享页更新版本。'
                share.content=json.dumps(content,ensure_ascii=False)


def share_view(session,row,owner,detail=False):
    author=session.get(UserAccount,row.owner_id);data=json.loads(row.content)
    return {'id':row.id,'project_id':row.project_id,'title':row.title,'kind':row.kind,
        'author':{'id':row.owner_id,'name':author.display_name if author else '原作者'},'can_manage':row.owner_id==owner,
        'visibility':row.visibility,'version':row.version,'source_revision':row.source_revision,
        'created_at':row.created_at,'updated_at':row.updated_at,
        'image_count':sum(i['status']=='succeeded' for i in data.get('images',[])),
        'material_count':len(data.get('materials',[])),**({'snapshot':data} if detail else {})}


def file_path(storage,share,key):
    data=json.loads(share.content)
    item=data.get('files',{}).get(key)
    if not item: raise HTTPException(404,'共享文件不存在。')
    path=root(storage,share.id)/str(UUID(data['bundle']))/key
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
        raise HTTPException(409,'共享文件缺失或已改变。')
    return path


class ChangeSharing(BaseModel):
    version:int=Field(ge=0)
    visibility:str=Field(pattern='^(team|private)$')


class CopySharing(BaseModel):
    request_id:UUID
    title:str=Field(min_length=1,max_length=120)
    version:int=Field(ge=1)

    @field_validator('title')
    @classmethod
    def title_not_blank(cls,value):
        if not value.strip(): raise ValueError('副本名称不能为空。')
        return value.strip()


class AdoptExperience(BaseModel):
    request_id:UUID
    product_id:UUID
    version:int=Field(ge=1)
    index:int=Field(ge=0)


def build_team_router(store):
    if store.engine is not None: STORAGE[store.engine]=store.directory
    router=APIRouter(prefix='/api/team-shares',tags=['team-sharing'])
    def load(session,identifier,owner,manage=False):
        row=session.get(TeamProjectShare,str(identifier),with_for_update=manage)
        if not row or row.visibility=='deleted' or row.visibility!='team' and row.owner_id!=owner: raise HTTPException(404,'共享项目不存在。')
        if manage and row.owner_id!=owner: raise HTTPException(403,'只有作者可以管理共享版本。')
        return row
    def require_db():
        if store.engine is None: raise HTTPException(503,'请先配置数据库。')

    @router.get('')
    def listing(request:Request,mine:bool=False,q:str='',author:str='',kind:str=''):
        require_db()
        with Session(store.engine) as session:
            query=select(TeamProjectShare).where(TeamProjectShare.owner_id==request.state.image_owner if mine else TeamProjectShare.visibility=='team')
            query=query.where(TeamProjectShare.visibility!='deleted')
            if q.strip(): query=query.where(TeamProjectShare.title.icontains(q.strip(),autoescape=True))
            if author: query=query.where(TeamProjectShare.owner_id==author)
            if kind: query=query.where(TeamProjectShare.kind==kind)
            rows=list(session.scalars(query.order_by(TeamProjectShare.updated_at.desc()).limit(200)))
            return {'items':[share_view(session,r,request.state.image_owner) for r in rows]}

    @router.get('/{identifier}')
    def detail(identifier:UUID,request:Request):
        require_db()
        with Session(store.engine) as session:
            row=load(session,identifier,request.state.image_owner)
            return share_view(session,row,request.state.image_owner,True)

    @router.put('/{identifier}')
    def visibility(identifier:UUID,value:ChangeSharing,request:Request):
        require_db()
        with Session(store.engine) as session,session.begin():
            row=load(session,identifier,request.state.image_owner,True)
            if row.version!=value.version: raise HTTPException(409,'共享版本已更新，请刷新后操作。')
            row.visibility=value.visibility;row.updated_at=now()
            return share_view(session,row,request.state.image_owner,True)

    @router.post('/{identifier}/publish')
    def update(identifier:UUID,value:ChangeSharing,request:Request):
        require_db()
        from app.creation_projects import LOCK
        with LOCK,Session(store.engine) as session,session.begin():
            row=load(session,identifier,request.state.image_owner,True)
            if row.version!=value.version: raise HTTPException(409,'共享版本已更新，请刷新后操作。')
            project=session.get(CreationProject,row.project_id)
            if not project: raise HTTPException(404,'来源项目不存在。')
            publish(session,store.directory,row,project);row.visibility=value.visibility
            return share_view(session,row,request.state.image_owner,True)

    @router.get('/{identifier}/files/{key:path}')
    def read_file(identifier:UUID,key:str,request:Request,original:bool=False):
        require_db()
        with Session(store.engine) as session:
            row=load(session,identifier,request.state.image_owner)
            if key.endswith('/original.png') and not original:
                preview=key.removesuffix('original.png')+'preview.jpg'
                if preview in json.loads(row.content).get('files',{}): key=preview
            return FileResponse(file_path(store.directory,row,key),headers={'Cache-Control':'no-store'})

    @router.get('/{identifier}/download')
    def download(identifier:UUID,request:Request):
        require_db()
        with Session(store.engine) as session:
            row=load(session,identifier,request.state.image_owner);snapshot=json.loads(row.content)
            if not row.version: raise HTTPException(409,'首个共享版本尚未发布。')
            handle=tempfile.NamedTemporaryFile(suffix='.zip',delete=False);temporary=Path(handle.name);handle.close()
            try:
                with ZipFile(temporary,'w',ZIP_DEFLATED,compresslevel=1) as archive:
                    for key in snapshot['files']: archive.write(file_path(store.directory,row,key),key)
                    archive.writestr('snapshot.json',json.dumps(snapshot,ensure_ascii=False,indent=2))
                return FileResponse(temporary,media_type='application/zip',filename=f'team-project-{row.id}-v{row.version}.zip',
                    background=BackgroundTask(temporary.unlink,missing_ok=True),headers={'Cache-Control':'no-store'})
            except BaseException: temporary.unlink(missing_ok=True);raise

    @router.post('/{identifier}/copy',status_code=201)
    def copy(identifier:UUID,value:CopySharing,request:Request):
        require_db()
        from app.creation_projects import LOCK
        with LOCK,Session(store.engine) as session,session.begin():
            share=load(session,identifier,request.state.image_owner)
            existing=session.get(CreationProject,str(value.request_id))
            if existing:
                provenance=json.loads(existing.content).get('team_source',{})
                if provenance.get('id')!=share.id or provenance.get('version')!=value.version: raise HTTPException(409,'提交标识已被使用。')
                return {'id':existing.id,'kind':existing.kind}
            if share.version!=value.version or not share.version: raise HTTPException(409,'共享版本已变化，请刷新后重新复制。')
            return copy_snapshot(session,store,share,value,request.state.image_owner)
    @router.post('/{identifier}/experiences',status_code=201)
    def adopt(identifier:UUID,value:AdoptExperience,request:Request):
        require_db()
        with Session(store.engine) as session,session.begin():
            share=load(session,identifier,request.state.image_owner)
            if share.version!=value.version: raise HTTPException(409,'共享版本已变化，请刷新后操作。')
            product=session.get(CreationProject,str(value.product_id))
            if not product or product.kind!='product': raise HTTPException(404,'请选择自己的产品分析。')
            existing=session.get(ProductImageExperience,str(value.request_id))
            if existing:
                provenance=json.loads(existing.content).get('team_source',{})
                if provenance!={'id':share.id,'version':value.version,'index':value.index} or existing.product_id!=product.id:
                    raise HTTPException(409,'提交标识已被使用。')
                return {'id':existing.id,'product_id':product.id}
            experiences=json.loads(share.content).get('experiences',[])
            if value.index>=len(experiences): raise HTTPException(404,'共享经验不存在。')
            data={**experiences[value.index]['content'],'sources':[],
                'team_source':{'id':share.id,'version':value.version,'index':value.index}}
            row=ProductImageExperience(id=str(value.request_id),owner_id=request.state.image_owner,product_id=product.id,
                content=json.dumps(data,ensure_ascii=False),status='candidate',revision=1,created_at=now(),updated_at=now())
            session.add(row)
            return {'id':row.id,'product_id':product.id}
    return router


def copy_snapshot(session,store,share,value,owner):
    """Copy immutable files and public data. No configuration or pending paid jobs."""
    snapshot=json.loads(share.content);created=[]
    current=store.get(owner) or {}
    provenance={'id':share.id,'version':share.version,'author_id':share.owner_id,'title':share.title}
    target_id=str(value.request_id);product_id=str(uuid4()) if share.kind=='plan' else None
    material_mapping={};doc_mapping={};job_mapping={i['id']:str(uuid4()) for i in snapshot['images'] if i['status']=='succeeded'}
    def remap(data,mapping):
        text=json.dumps(data,ensure_ascii=False)
        for old,new in mapping.items(): text=text.replace(old,new)
        return json.loads(text)
    def add_project(identifier,kind,title):
        row=CreationProject(id=identifier,title=title,kind=kind,source_product_id=product_id if kind=='plan' else None,
            owner_id=owner,revision=1,content='{}',created_at=now(),updated_at=now());session.add(row)
        folder=store.directory/'creation-projects'/identifier
        if folder.exists(): raise HTTPException(409,'复制目标目录已存在，请重新提交。')
        folder.mkdir(parents=True);created.append(folder)
        return row
    def materials_for(identifier):
        mapping={}
        for item in snapshot['materials']:
            mid=str(uuid4());mapping[item['id']]=mid
            source=file_path(store.directory,share,'materials/'+item['id']);path=material_path(store.directory,identifier,mid)
            path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,path)
            session.add(CreationMaterial(id=mid,project_id=identifier,**{k:item[k] for k in ('name','kind','media_type','digest','size','pages')},created_at=now()))
        return mapping
    try:
        product=None
        if product_id:
            product=add_project(product_id,'product',(value.title+' · 产品资料')[:120])
            product_materials=materials_for(product_id)
        target=add_project(target_id,share.kind,value.title);material_mapping=materials_for(target_id)
        from app.creation_projects import ProjectInput
        from app.creation_skills import snapshot_for
        defaults=ProjectInput(title=value.title,kind='product').model_dump(mode='json',exclude={'title','revision','kind','source_product_id','template_id'})
        settings={**defaults,**{k:v for k,v in snapshot['settings'].items() if v is not None}}
        data={**settings,'planning_model':current.get('planning_model_name',''),'image_model':current.get('image_model_name',''),
            'skill':{'mode':'auto','skills':[],'allow_auto':True},'active':{},'batches':[], 'messages':[],
            'team_source':provenance,'stage':'analysis' if target.kind=='product' else 'brief',
            'analysis_confirmed':bool(snapshot.get('analysis_confirmed')),'visual_style_snapshot':snapshot.get('visual_style_snapshot')}
        data['skill_snapshot']=snapshot_for(store.engine,store.directory,owner,data['goal'],data['skill'])
        for document in snapshot['history']:
            doc_id=str(uuid4());doc_mapping[document['id']]=doc_id
            # Analysis belongs to the same product snapshot. Design drafts must be confirmed by the recipient.
            confirmed=document['confirmed_at'] if document['stage']=='analysis' else None
            doc=CreationDocument(id=doc_id,project_id=target_id,stage=document['stage'],version=document['version'],
                content=json.dumps(remap(document['content'],material_mapping),ensure_ascii=False),confirmed_at=confirmed,created_at=now());session.add(doc)
            if snapshot['active'].get(document['stage'])==document['id']: data['active'][document['stage']]=doc_id
        if product:
            product_data={**settings,'active':{},'batches':[],'messages':[],'team_source':provenance,
                'skill':data['skill'],'skill_snapshot':data['skill_snapshot'],'analysis_confirmed':False,'stage':'analysis','planning_model':data['planning_model'],'image_model':data['image_model']}
            for document in snapshot['history']:
                if document['stage']!='analysis': continue
                doc_id=str(uuid4())
                doc=CreationDocument(id=doc_id,project_id=product_id,stage='analysis',version=document['version'],
                    content=json.dumps(remap(document['content'],product_materials),ensure_ascii=False),confirmed_at=document['confirmed_at'],created_at=now());session.add(doc)
                if snapshot['active'].get('analysis')==document['id']:
                    product_data['active']['analysis']=doc_id;product_data['analysis_confirmed']=bool(doc.confirmed_at)
                    data['source']={'product_id':product_id,'title':product.title,'document_id':doc_id,'version':doc.version,'materials':{product_materials[k]:v for k,v in material_mapping.items()}}
            product.content=json.dumps(product_data,ensure_ascii=False)
        for image in snapshot['images']:
            if image['id'] not in job_mapping: continue
            jid=job_mapping[image['id']];folder=store.directory/'image-jobs'/jid
            folder.mkdir(parents=True,exist_ok=False);created.append(folder)
            shutil.copyfile(file_path(store.directory,share,'images/'+image['id']+'/original.png'),folder/'result.png')
            preview='images/'+image['id']+'/preview.jpg'
            if preview in snapshot['files']: shutil.copyfile(file_path(store.directory,share,preview),folder/'preview.jpg')
            for ref in image.get('references',[]): shutil.copyfile(file_path(store.directory,share,ref),folder/Path(ref).name)
            profile={'creation_project_id':target_id,'source_documents':data['active'],'imported_from_share':provenance,
                'reference_manifest':remap(image.get('reference_roles',[]),{**material_mapping,**doc_mapping,**job_mapping}),**image.get('purpose',{})}
            job=ImageJob(id=jid,request_id=jid,fingerprint=hashlib.sha256(jid.encode()).hexdigest(),owner_id=owner,
                config_id=current.get('id',''),config_name='共享项目副本',base_url='',encrypted_key='',model_name=image['model_name'],
                prompt=image['prompt'],size=image['size'],mode='edit' if image.get('references') else 'generate',status='succeeded',
                message='从团队共享复制，未调用生图接口。',created_at=now(),updated_at=now(),task_id=target_id,
                task_index=image.get('task_index',0),shot_name=image['shot_name'],shot_index=image.get('shot_index'),
                parent_job_id=job_mapping.get(image.get('parent_job_id')),edit_instruction=image.get('edit_instruction',''),
                execution_profile=json.dumps(profile,ensure_ascii=False),execution_result=json.dumps(remap(image.get('review',{}),job_mapping),ensure_ascii=False))
            session.add(job)
        for batch in snapshot.get('batches',[]):
            jobs=[job_mapping[j] for j in batch.get('job_ids',[]) if j in job_mapping]
            if jobs: data['batches'].append({**batch,'execution_id':str(uuid4()),'job_ids':jobs})
        feedback_mapping={note['id']:str(uuid4()) for note in snapshot.get('feedback',[]) if note['job_id'] in job_mapping}
        for note in snapshot.get('feedback',[]):
            if note['job_id'] not in job_mapping: continue
            session.add(CreativeCase(id=feedback_mapping[note['id']],job_id=job_mapping[note['job_id']],owner_id=owner,revision=1,
                **{k:note[k] for k in ('title','experience','issues','outcome','requested_change')},product_id=product_id or target_id,updated_at=now()))
        for experience in snapshot.get('experiences',[]):
            session.add(ProductImageExperience(id=str(uuid4()),product_id=product_id or target_id,owner_id=owner,
                content=json.dumps(remap(experience['content'],{**feedback_mapping,**job_mapping}),ensure_ascii=False),status='candidate',revision=1,created_at=now(),updated_at=now()))
        data['messages']=remap(snapshot.get('messages',[]),{**material_mapping,**doc_mapping,**job_mapping})
        target.content=json.dumps(data,ensure_ascii=False);session.flush()
        return {'id':target.id,'kind':target.kind,'source':provenance,'product_id':product_id}
    except BaseException:
        for folder in reversed(created): shutil.rmtree(folder)
        raise


def publish_completed_job(store, identifier):
    # Bulk worker updates do not pass through ORM dirty-record events.
    # Sharing runs separately so a file/publish error cannot fail paid work.
    import logging
    try:
        with Session(store.engine) as session,session.begin():
            job=session.get(ImageJob,identifier)
            if job and job.task_id: ensure_default_shares(session,[job.task_id],refresh_completed=True)
    except Exception:
        logging.getLogger(__name__).warning('Automatic team snapshot deferred for completed job %s',identifier)


def backfill(engine,storage):
    STORAGE[engine]=storage
    with Session(engine) as session,session.begin():
        ensure_default_shares(session,list(session.scalars(select(CreationProject.id))),refresh_completed=True)


if __name__=='__main__':
    from app.database import make_engine,database_url,data_directory
    engine=make_engine(database_url())
    backfill(engine,data_directory())
    print('Team sharing prepared; credentials were not included.')
